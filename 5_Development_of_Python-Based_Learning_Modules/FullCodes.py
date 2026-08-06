from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable

try:
    import matplotlib.pyplot as plt
    import pandas as pd
    import requests
except ModuleNotFoundError as error:
    raise SystemExit(
        "Missing dependency: "
        f"{error.name}. Install the requirements first with "
        "python -m pip install -r requirements.txt"
    ) from error


API_URL = "https://api.vam.ac.uk/v2/objects/search"
IIIF_THUMBNAIL = (
    "https://framemark.vam.ac.uk/collections/"
    "{image_id}/full/!100,100/0/default.jpg"
)
MISSING_LABELS = {
    "title": "Untitled object",
    "creator": "Unknown maker",
    "date": "Unknown date",
    "place": "Unknown place",
    "object_type": "Unknown type",
}


def request_parameters(query: str, page_size: int) -> dict[str, Any]:
    """Build the documented search parameters for the V&A endpoint."""
    if not 1 <= page_size <= 100:
        raise ValueError("page_size must be between 1 and 100")
    return {
        "q": query,
        "page_size": page_size,

        "response_format": "json",
    }


def fetch_response(query: str, page_size: int) -> dict[str, Any]:
    """Send the request, check its status, and decode the JSON response."""
    params = request_parameters(query, page_size)
    response = requests.get(API_URL, params=params, timeout=30)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict) or "records" not in data:
        raise ValueError("The API response does not contain a records field")
    return data


def inspect_response(data: dict[str, Any]) -> None:
    """Module 1: expose the endpoint response structure to the learner."""
    info = data.get("info", {})
    records = data.get("records", [])
    print("\nModule 1: Understanding APIs and JSON")
    print(f"Returned records: {len(records)}")
    if isinstance(info, dict):
        print(f"API record count: {info.get('record_count', 'not provided')}")
    if records:
        first = records[0]
        print("First record keys:", ", ".join(sorted(first.keys())))
        print("First record title:", first.get("_primaryTitle") or "<missing>")


def save_json(value: Any, path: Path) -> None:
    """Save a JSON value with Unicode preserved and readable indentation."""
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def thumbnail_url(item: dict[str, Any]) -> str | None:
    """Use the API thumbnail when present, otherwise construct a IIIF URL."""
    images = item.get("_images") or {}
    if isinstance(images, dict) and images.get("_primary_thumbnail"):
        return images["_primary_thumbnail"]
    image_id = item.get("_primaryImageId")
    if image_id:
        return IIIF_THUMBNAIL.format(image_id=image_id)
    return None


def extract_records(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Module 3: map V&A fields to a smaller shared project schema."""
    records: list[dict[str, Any]] = []
    for item in data.get("records", []):
        maker = item.get("_primaryMaker") or {}
        if not isinstance(maker, dict):
            maker = {}
        system_number = item.get("systemNumber") or ""
        records.append(
            {
                "title": item.get("_primaryTitle"),
                "creator": maker.get("name"),
                "date": item.get("_primaryDate"),
                "place": item.get("_primaryPlace"),
                "object_type": item.get("objectType"),
                "image_url": thumbnail_url(item),
                "landing_page": (
                    "https://collections.vam.ac.uk/item/"
                    f"{system_number}/"
                    if system_number
                    else None
                ),
            }
        )
    return records


def usable_value(value: Any) -> bool:
    """Return whether a value should count as present metadata."""
    if value is None or pd.isna(value):
        return False
    if isinstance(value, str):
        return value.strip().lower() not in {"", "unknown", "n/a", "none"}
    return True


def coverage_summary(records: Iterable[dict[str, Any]]) -> pd.DataFrame:
    """Module 4: calculate field coverage before display cleaning."""
    rows = list(records)
    total = len(rows)
    values = []
    for field in ["title", "creator", "date", "place", "object_type", "image_url", "landing_page"]:
        present = sum(usable_value(record.get(field)) for record in rows)
        values.append(
            {
                "field": field,
                "present_records": present,
                "total_records": total,
                "coverage_percent": round((present / total * 100) if total else 0, 1),
            }
        )
    return pd.DataFrame(values)


def clean_records(records: list[dict[str, Any]]) -> pd.DataFrame:
    """Module 4: create explicit display values without hiding missingness."""
    df = pd.DataFrame(records)
    for field, label in MISSING_LABELS.items():
        if field not in df.columns:
            df[field] = pd.NA
        # Empty strings are missing values, not meaningful catalogue terms.
        df[field] = df[field].replace(r"^\s*$", pd.NA, regex=True)
        df[field] = df[field].fillna(label).astype(str).str.strip()
    for field in ["image_url", "landing_page"]:
        if field not in df.columns:
            df[field] = pd.NA
    return df


def write_summaries(df: pd.DataFrame, output_dir: Path) -> None:
    """Write the working table and the two categorical frequency tables."""
    df.to_csv(output_dir / "cleaned_records.csv", index=False)
    df["object_type"].value_counts().rename_axis("object_type").reset_index(name="records").to_csv(
        output_dir / "object_type_counts.csv", index=False
    )
    df["place"].value_counts().rename_axis("place").reset_index(name="records").to_csv(
        output_dir / "place_counts.csv", index=False
    )


def save_chart(counts: pd.Series, title: str, ylabel: str, path: Path) -> None:
    """Module 5: create a labelled horizontal bar chart."""
    top = counts.head(10).sort_values()
    fig, ax = plt.subplots(figsize=(8, 5))
    top.plot(kind="barh", ax=ax)
    ax.set_xlabel("Number of records")
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def run_workflow(query: str, page_size: int, output_dir: Path) -> None:
    """Run Modules 1-5 and prepare the files used by Module 6."""
    output_dir.mkdir(parents=True, exist_ok=True)

    data = fetch_response(query, page_size)
    inspect_response(data)
    save_json(data, output_dir / "raw_response.json")

    records = extract_records(data)
    save_json(records, output_dir / "mapped_records.json")

    coverage = coverage_summary(records)
    coverage.to_csv(output_dir / "metadata_coverage.csv", index=False)
    print("\nModule 4: Metadata coverage")
    print(coverage.to_string(index=False))

    df = clean_records(records)
    write_summaries(df, output_dir)

    save_chart(
        df["object_type"].value_counts(),
        f"Top object types in the V&A sample ({query})",
        "Object type",
        output_dir / "object_type_counts.png",
    )
    save_chart(
        df["place"].value_counts(),
        f"Top catalogue place values in the V&A sample ({query})",
        "Place value",
        output_dir / "place_counts.png",
    )

    print("\nModule 6: Independent mini-project materials")
    print(f"Saved {len(df)} cleaned records to {output_dir}")
    print("Use the saved JSON, CSV files and charts to write a short interpretation.")
    print("Record the query, retrieval date, selected fields and cleaning decisions in the report.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Chapter 5 V&A learning workflow")
    parser.add_argument("--query", default="porcelain", help="V&A search keyword")
    parser.add_argument("--page-size", type=int, default=20, help="Number of records to request (1-100)")
    parser.add_argument("--output-dir", type=Path, default=Path("vam_learning_output"))
    return parser.parse_args([]) # Pass an empty list to parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    run_workflow(arguments.query, arguments.page_size, arguments.output_dir)
