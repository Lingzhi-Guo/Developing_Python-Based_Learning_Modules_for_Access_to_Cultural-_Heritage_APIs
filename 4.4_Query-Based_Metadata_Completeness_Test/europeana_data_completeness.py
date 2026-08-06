
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import requests


QUERY = "porcelain"
LIMIT = 50

COMMON_FIELDS = [
    "title",
    "creator",
    "date",
    "place",
    "object_type",
    "image_url",
    "rights",
    "landing_page",
]


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, float) and pd.isna(value):
        return False
    if isinstance(value, str):
        return value.strip() != ""
    if isinstance(value, (list, tuple, set)):
        return len(value) > 0 and any(is_present(v) for v in value)
    if isinstance(value, dict):
        return len(value) > 0 and any(is_present(v) for v in value.values())
    return True


def first_present(*values: Any) -> Any:
    for value in values:
        if is_present(value):
            return value
    return None


def first_value(value: Any) -> Any:
    if isinstance(value, list):
        for item in value:
            if is_present(item):
                return first_value(item)
        return None

    if isinstance(value, dict):
        for key in ["displayDate", "name", "title", "value", "def", "en"]:
            if key in value and is_present(value[key]):
                return first_value(value[key])
        return value

    return value


def join_values(value: Any, separator: str = "; ") -> Optional[str]:
    if not is_present(value):
        return None

    if isinstance(value, list):
        parts = []
        for item in value:
            simplified = join_values(item, separator=separator)
            if simplified:
                parts.append(simplified)
        return separator.join(parts) if parts else None

    if isinstance(value, dict):
        for key in ["displayDate", "name", "title", "value", "def", "en"]:
            if key in value and is_present(value[key]):
                return join_values(value[key], separator=separator)
        return json.dumps(value, ensure_ascii=False)

    text = str(value).strip()
    return text if text else None


def field_is_present(item: Dict[str, Any], field: str) -> bool:
    value = item.get(field)

    # Numeric permission levels are useful source-specific metadata,
    # but they are not readable rights/licence statements.
    if field == "rights" and isinstance(value, (int, float)):
        return False

    return is_present(value)


def calculate_coverage(items: List[Dict[str, Any]]) -> pd.DataFrame:
    rows = []
    total = len(items)

    for field in COMMON_FIELDS:
        present = sum(1 for item in items if field_is_present(item, field))
        missing = total - present
        coverage = round((present / total) * 100, 2) if total else 0.0

        rows.append({
            "field": field,
            "present": present,
            "missing": missing,
            "coverage_percent": coverage,
        })

    return pd.DataFrame(rows)


def safe_get(url: str, params: Optional[Dict[str, Any]] = None, timeout: int = 30) -> Dict[str, Any]:
    headers = {"User-Agent": "Mozilla/5.0 metadata completeness research script"}
    response = requests.get(url, params=params, headers=headers, timeout=timeout)
    response.raise_for_status()
    return response.json()


def print_item_status(items: List[Dict[str, Any]]) -> None:
    total = len(items)

    for index, item in enumerate(items, start=1):
        object_id = item.get("object_id") or "unknown_id"
        missing = [
            field for field in COMMON_FIELDS
            if not field_is_present(item, field)
        ]

        if missing:
            print(
                f"({index}/{total}) ID: {object_id}  "
                f"Missing: {', '.join(missing)}"
            )
        else:
            print(f"({index}/{total}) ID: {object_id}  Complete")


def save_outputs(
    *,
    api_key: str,
    items: List[Dict[str, Any]],
    output_dir: Path,
    metadata_filename: str,
    coverage_filename: str,
    sample_filename: str,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    metadata_df = pd.DataFrame(items)
    coverage_df = calculate_coverage(items)

    metadata_path = output_dir / metadata_filename
    coverage_path = output_dir / coverage_filename
    sample_path = output_dir / sample_filename

    metadata_df.to_csv(metadata_path, index=False, encoding="utf-8-sig")
    coverage_df.to_csv(coverage_path, index=False, encoding="utf-8-sig")

    sample_doc = {
        "api_key": api_key,
        "query": QUERY,
        "requested_limit": LIMIT,
        "returned_count": len(items),
        "retrieved_at_utc": now_utc(),
        "common_fields": COMMON_FIELDS,
        "field_completeness": coverage_df.to_dict(orient="records"),
        "sample_items_first_10": items[:10],
    }

    with sample_path.open("w", encoding="utf-8") as f:
        json.dump(sample_doc, f, ensure_ascii=False, indent=2)

    print("\nSaved files:")
    print(f"- {metadata_path}")
    print(f"- {coverage_path}")
    print(f"- {sample_path}")


# You can replace this with your own key if needed.
EUROPEANA_API_KEY = os.getenv("EUROPEANA_API_KEY") or "idallwometac"
OUTPUT_DIR = Path("europeana_output")


def fetch_europeana(query: str = QUERY, limit: int = LIMIT) -> List[Dict[str, Any]]:
    endpoint = "https://api.europeana.eu/record/v2/search.json"
    params = {
        "wskey": EUROPEANA_API_KEY,
        "query": query,
        "rows": limit,
        "profile": "rich",
        "media": "true",
        "thumbnail": "true",
    }

    raw = safe_get(endpoint, params=params)
    docs = raw.get("items", [])

    items = []

    for idx, doc in enumerate(docs, start=1):
        items.append({
            "position": idx,
            "object_id": doc.get("id"),
            "title": join_values(first_present(doc.get("title"), doc.get("dcTitleLangAware"))),
            "creator": join_values(first_present(doc.get("dcCreator"), doc.get("dcCreatorLangAware"), doc.get("creator"))),
            "date": join_values(first_present(doc.get("year"), doc.get("dcDate"), doc.get("timestamp_created"))),
            "place": join_values(first_present(doc.get("country"), doc.get("edmCountry"), doc.get("dctermsSpatial"))),
            "object_type": join_values(first_present(doc.get("type"), doc.get("dcType"), doc.get("dcTypeLangAware"))),
            "image_url": join_values(first_present(doc.get("edmPreview"), doc.get("edmIsShownBy"))),
            "rights": join_values(first_present(doc.get("rights"), doc.get("edmRights"))),
            "landing_page": join_values(first_present(doc.get("guid"), doc.get("edmIsShownAt"))),
            "source_specific": {
                "provider": join_values(doc.get("provider")),
                "data_provider": join_values(doc.get("dataProvider")),
                "language": join_values(doc.get("language")),
                "score": doc.get("score"),
            },
        })

    return items


def main() -> None:
    print(f"Fetching Europeana records for query: {QUERY!r}")
    items = fetch_europeana()
    print_item_status(items)

    save_outputs(
        api_key="europeana",
        items=items,
        output_dir=OUTPUT_DIR,
        metadata_filename="europeana_metadata.csv",
        coverage_filename="europeana_coverage.csv",
        sample_filename="europeana_first_10_sample.json",
    )


main()
