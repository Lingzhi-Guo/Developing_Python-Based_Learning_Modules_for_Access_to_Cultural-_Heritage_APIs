import time
import requests
import pandas as pd


SEARCH_URL = "https://data.rijksmuseum.nl/search/collection"

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


# ============================================================
# Basic helpers
# ============================================================

def is_present(value):
    """Check whether a field should count as present."""
    if value is None:
        return False
    if isinstance(value, float) and pd.isna(value):
        return False
    if isinstance(value, str):
        return value.strip() != ""
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) > 0
    return True


def first_present(*values):
    """Return the first non-empty value."""
    for value in values:
        if is_present(value):
            return value
    return None


def get_json(url, params=None, timeout=30, retries=3, verbose=False):
    """
    Request JSON with retry.

    verbose=False keeps terminal output clean.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 metadata research script"
    }

    last_error = None

    for attempt in range(1, retries + 1):
        try:
            response = requests.get(
                url,
                params=params,
                timeout=timeout,
                allow_redirects=True,
                headers=headers,
            )
            response.raise_for_status()
            return response.json()

        except Exception as error:
            last_error = error
            if verbose:
                print(f"  Request failed ({attempt}/{retries}): {url} | {error}")
            time.sleep(1)

    raise last_error


def to_data_uri(uri):
    """Convert id.rijksmuseum.nl URI to data.rijksmuseum.nl URI."""
    if not isinstance(uri, str):
        return None
    return uri.replace("https://id.rijksmuseum.nl/", "https://data.rijksmuseum.nl/")


def get_nested(data, path):
    """Safely get nested value from dict/list."""
    current = data

    for key in path:
        if isinstance(current, dict) and key in current:
            current = current[key]
        elif isinstance(current, list) and isinstance(key, int) and len(current) > key:
            current = current[key]
        else:
            return None

    return current


def unique_keep_order(values):
    """Remove duplicates while keeping order."""
    seen = set()
    unique = []

    for item in values:
        if not is_present(item):
            continue

        marker = repr(item)

        if marker not in seen:
            seen.add(marker)
            unique.append(item)

    return unique


def extract_uri_last_part(uri):
    """Extract final ID part from a URI."""
    if not isinstance(uri, str):
        return None
    return uri.rstrip("/").split("/")[-1].split("?")[0]


# ============================================================
# Recursive JSON helpers
# ============================================================

def collect_strings(obj, keys):
    """
    Recursively collect string values for selected keys from JSON-LD.

    This broad strategy works well for Rijksmuseum metadata fields such as
    creator, date, place, object_type, and rights.
    """
    results = []

    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in keys:
                if isinstance(value, str):
                    results.append(value)

                elif isinstance(value, dict):
                    label = first_present(
                        value.get("content"),
                        value.get("value"),
                        value.get("_label"),
                        value.get("label"),
                        value.get("title"),
                        value.get("id"),
                    )
                    if is_present(label):
                        results.append(label)

                elif isinstance(value, list):
                    for item in value:
                        if isinstance(item, str):
                            results.append(item)

                        elif isinstance(item, dict):
                            label = first_present(
                                item.get("content"),
                                item.get("value"),
                                item.get("_label"),
                                item.get("label"),
                                item.get("title"),
                                item.get("id"),
                            )
                            if is_present(label):
                                results.append(label)

            results.extend(collect_strings(value, keys))

    elif isinstance(obj, list):
        for item in obj:
            results.extend(collect_strings(item, keys))

    return unique_keep_order(results)


def find_values_for_key(obj, target_key):
    """Recursively collect values for a selected key."""
    results = []

    if isinstance(obj, dict):
        for key, value in obj.items():
            if key == target_key:
                results.append(value)
            results.extend(find_values_for_key(value, target_key))

    elif isinstance(obj, list):
        for item in obj:
            results.extend(find_values_for_key(item, target_key))

    return results


def find_dicts_by_type(obj, wanted_type):
    """Recursively find dictionaries whose type equals wanted_type."""
    found = []

    if isinstance(obj, dict):
        obj_type = obj.get("type")

        if isinstance(obj_type, str):
            if obj_type == wanted_type or obj_type.endswith("/" + wanted_type):
                found.append(obj)

        for value in obj.values():
            found.extend(find_dicts_by_type(value, wanted_type))

    elif isinstance(obj, list):
        for item in obj:
            found.extend(find_dicts_by_type(item, wanted_type))

    return found


def find_any_iiif_urls(obj):
    """Recursively find all iiif.micr.io URLs anywhere in a JSON object."""
    urls = []

    if isinstance(obj, dict):
        for value in obj.values():
            urls.extend(find_any_iiif_urls(value))

    elif isinstance(obj, list):
        for item in obj:
            urls.extend(find_any_iiif_urls(item))

    elif isinstance(obj, str):
        if "iiif.micr.io" in obj:
            urls.append(obj)

    return unique_keep_order(urls)


# ============================================================
# Search and metadata resolving
# ============================================================

def search_rijksmuseum(query="porcelain", limit=50):
    """
    Search Rijksmuseum Data Services and return object identifiers.

    No API key is required.
    """
    object_ids = []
    next_url = SEARCH_URL
    params = {
        "description": query,
        "imageAvailable": "true",
    }

    while len(object_ids) < limit and next_url:
        data = get_json(next_url, params=params)

        items = data.get("orderedItems", [])
        for item in items:
            object_id = item.get("id")
            if object_id:
                object_ids.append(object_id)

                if len(object_ids) >= limit:
                    break

        next_page = data.get("next", {})
        next_url = next_page.get("id")

        # After first request, next_url already contains parameters.
        params = None

    return object_ids[:limit]


def resolve_object_metadata(object_id):
    """
    Resolve object metadata.

    Important:
    Use id.rijksmuseum.nl with la/edm/schema profiles for metadata.
    Do not replace this with data.rijksmuseum.nl + la-framed for metadata,
    because that can cause creator/place/rights to disappear.
    """
    candidate_urls = [
        object_id + "?_profile=la&_mediatype=application/ld+json",
        object_id + "?_profile=edm&_mediatype=application/ld+json",
        object_id + "?_profile=schema&_mediatype=application/ld+json",
        object_id + "?_mediatype=application/ld+json",
        object_id + "?_profile=alt",
    ]

    headers = {"User-Agent": "Mozilla/5.0 metadata research script"}

    for url in candidate_urls:
        try:
            response = requests.get(
                url,
                timeout=30,
                allow_redirects=True,
                headers=headers,
            )

            if response.status_code != 200:
                continue

            content_type = response.headers.get("content-type", "")
            body = response.text.strip()

            if "json" in content_type or body.startswith(("{", "[")):
                return response.json(), response.url

        except Exception:
            continue

    return {}, object_id


# ============================================================
# IIIF image extraction
# ============================================================

def is_valid_image_url(url):
    """Return True only for real image URLs."""
    if not isinstance(url, str):
        return False

    if "iiif.micr.io" in url:
        return True

    clean_url = url.split("?")[0].lower()

    return clean_url.endswith((".jpg", ".jpeg", ".png", ".webp", ".gif"))


def normalise_iiif_image_url(url, size="max"):
    """
    Convert a Micrio/IIIF URL into a direct image URL.

    If access_point is already:
    https://iiif.micr.io/xxxxx/full/max/0/default.jpg
    return it directly.
    """
    if not isinstance(url, str) or "iiif.micr.io" not in url:
        return None

    if "/full/" in url and is_valid_image_url(url):
        return url

    try:
        identifier = url.split("iiif.micr.io/")[1].split("/")[0]
        if not identifier:
            return None
        return f"https://iiif.micr.io/{identifier}/full/{size}/0/default.jpg"

    except Exception:
        return None


def extract_image_url_from_access_points(obj, size="max"):
    """
    Recursively search access_point values and return a IIIF image URL.
    """
    access_point_values = find_values_for_key(obj, "access_point")
    candidates = []

    for value in access_point_values:
        if isinstance(value, dict):
            candidates.append(value.get("id"))

        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    candidates.append(item.get("id"))
                elif isinstance(item, str):
                    candidates.append(item)

        elif isinstance(value, str):
            candidates.append(value)

    for candidate in candidates:
        if isinstance(candidate, str) and "iiif.micr.io" in candidate:
            return normalise_iiif_image_url(candidate, size=size)

    return None


def extract_any_iiif_url(obj, size="max"):
    """
    Fallback: recursively find any iiif.micr.io URL anywhere.
    """
    for url in find_any_iiif_urls(obj):
        image_url = normalise_iiif_image_url(url, size=size)
        if image_url:
            return image_url

    return None


def extract_iiif_image_url_from_object(object_id, size="max"):
    """
    Extract image URL through Rijksmuseum IIIF chain.

    Correct chain:
    Object -> VisualItem -> DigitalObject -> access_point
    """
    data_object_uri = to_data_uri(object_id)

    if not data_object_uri:
        return None

    try:
        object_record = get_json(data_object_uri, params={"_profile": "la-framed"})
    except Exception:
        return None

    # 1. Direct access_point or any IIIF URL in object record.
    image = first_present(
        extract_image_url_from_access_points(object_record, size=size),
        extract_any_iiif_url(object_record, size=size),
    )
    if image:
        return image

    checked_digital_uris = set()

    # 2. Try DigitalObject found anywhere in object record.
    for digital_object in find_dicts_by_type(object_record, "DigitalObject"):
        image = first_present(
            extract_image_url_from_access_points(digital_object, size=size),
            extract_any_iiif_url(digital_object, size=size),
        )
        if image:
            return image

        digital_uri = to_data_uri(digital_object.get("id"))

        if not digital_uri or digital_uri in checked_digital_uris:
            continue

        checked_digital_uris.add(digital_uri)

        try:
            digital_record = get_json(digital_uri, params={"_profile": "la-framed"})
            image = first_present(
                extract_image_url_from_access_points(digital_record, size=size),
                extract_any_iiif_url(digital_record, size=size),
            )
            if image:
                return image

        except Exception:
            continue

    # 3. Follow VisualItem from shows.
    visual_items = []

    shows = object_record.get("shows", [])
    if isinstance(shows, dict):
        shows = [shows]

    if isinstance(shows, list):
        visual_items.extend([item for item in shows if isinstance(item, dict)])

    # Also recursively find VisualItem just in case.
    visual_items.extend(find_dicts_by_type(object_record, "VisualItem"))

    checked_visual_uris = set()

    for visual_item in visual_items:
        visual_uri = to_data_uri(visual_item.get("id"))

        if not visual_uri or visual_uri in checked_visual_uris:
            continue

        checked_visual_uris.add(visual_uri)

        try:
            visual_record = get_json(visual_uri, params={"_profile": "la-framed"})

            image = first_present(
                extract_image_url_from_access_points(visual_record, size=size),
                extract_any_iiif_url(visual_record, size=size),
            )
            if image:
                return image

        except Exception:
            continue

        # Follow DigitalObject from digitally_shown_by.
        digital_objects = []

        digitally_shown_by = visual_record.get("digitally_shown_by", [])
        if isinstance(digitally_shown_by, dict):
            digitally_shown_by = [digitally_shown_by]

        if isinstance(digitally_shown_by, list):
            digital_objects.extend([item for item in digitally_shown_by if isinstance(item, dict)])

        digital_objects.extend(find_dicts_by_type(visual_record, "DigitalObject"))

        for digital_object in digital_objects:
            image = first_present(
                extract_image_url_from_access_points(digital_object, size=size),
                extract_any_iiif_url(digital_object, size=size),
            )
            if image:
                return image

            digital_uri = to_data_uri(digital_object.get("id"))

            if not digital_uri or digital_uri in checked_digital_uris:
                continue

            checked_digital_uris.add(digital_uri)

            try:
                digital_record = get_json(digital_uri, params={"_profile": "la-framed"})

                image = first_present(
                    extract_image_url_from_access_points(digital_record, size=size),
                    extract_any_iiif_url(digital_record, size=size),
                )
                if image:
                    return image

            except Exception:
                continue

    return None


def extract_possible_image_from_metadata(metadata):
    """
    Strict fallback image extraction from metadata only.

    Only returns true image URLs. Never returns Rijksmuseum object pages.
    """
    image_candidates = []

    image_candidates += collect_strings(
        metadata,
        keys={
            "image",
            "image_url",
            "primaryImage",
            "edmPreview",
            "isShownBy",
            "access_point",
        },
    )

    for candidate in image_candidates:
        if isinstance(candidate, str) and "iiif.micr.io" in candidate:
            return normalise_iiif_image_url(candidate)

        if is_valid_image_url(candidate):
            return candidate

    return None


# ============================================================
# Metadata extraction
# ============================================================

def extract_title(metadata):
    """Extract a human-readable title without using object number as title."""
    title_candidates = []

    if isinstance(metadata, dict):
        title_candidates.append(metadata.get("_label"))
        title_candidates.append(metadata.get("title"))
        title_candidates.append(metadata.get("name"))

    identified_by = metadata.get("identified_by", []) if isinstance(metadata, dict) else []

    if isinstance(identified_by, list):
        name_candidates = []
        other_candidates = []

        for item in identified_by:
            if not isinstance(item, dict):
                continue

            content = item.get("content")
            if not is_present(content):
                continue

            item_type = item.get("type", "")

            item_labels = " ".join(
                str(x).lower()
                for x in collect_strings(
                    item.get("classified_as", []),
                    {"_label", "label", "name"}
                )
            )

            if item_type == "Name" or item_type.endswith("/Name"):
                name_candidates.append(content)
            elif "object number" not in item_labels and "identifier" not in item_labels:
                other_candidates.append(content)

        title_candidates += name_candidates
        title_candidates += other_candidates

    title_candidates += collect_strings(
        metadata,
        keys={"title", "prefLabel", "label", "name"},
    )

    clean_candidates = [
        item for item in title_candidates
        if is_present(item) and not (isinstance(item, str) and item.startswith("http"))
    ]

    return first_present(*clean_candidates)


def extract_rijksmuseum_metadata(metadata, resolved_url, object_id):
    """
    Extract comparable metadata fields.

    Metadata fields use the first high-coverage logic.
    Image URL uses the IIIF chain.
    """
    title = extract_title(metadata)

    # creator / maker
    creator_candidates = []

    produced_by = metadata.get("produced_by", {}) if isinstance(metadata, dict) else {}

    if isinstance(produced_by, dict):
        carried_out_by = produced_by.get("carried_out_by", [])
        if isinstance(carried_out_by, list):
            for actor in carried_out_by:
                if isinstance(actor, dict):
                    creator_candidates.append(
                        first_present(
                            actor.get("_label"),
                            actor.get("label"),
                            actor.get("name"),
                            actor.get("content"),
                            actor.get("id"),
                        )
                    )

    creator_candidates += collect_strings(
        metadata,
        keys={"creator", "maker", "artist", "principalMaker", "carried_out_by"},
    )

    creator = first_present(*creator_candidates)

    # date
    date_candidates = []

    timespan = get_nested(metadata, ["produced_by", "timespan"])
    if isinstance(timespan, dict):
        date_candidates.append(timespan.get("_label"))
        date_candidates.append(timespan.get("begin_of_the_begin"))
        date_candidates.append(timespan.get("end_of_the_end"))

    date_candidates += collect_strings(
        metadata,
        keys={
            "date",
            "created",
            "creationDate",
            "period",
            "begin_of_the_begin",
            "end_of_the_end",
        },
    )

    date = first_present(*date_candidates)

    # place
    place_candidates = []

    took_place_at = get_nested(metadata, ["produced_by", "took_place_at"])
    if isinstance(took_place_at, list):
        for place in took_place_at:
            if isinstance(place, dict):
                place_candidates.append(
                    first_present(
                        place.get("_label"),
                        place.get("label"),
                        place.get("name"),
                        place.get("content"),
                        place.get("id"),
                    )
                )

    place_candidates += collect_strings(
        metadata,
        keys={"place", "country", "culture", "spatial", "took_place_at"},
    )

    place = first_present(*place_candidates)

    # object type
    object_type_candidates = []

    classified_as = metadata.get("classified_as", []) if isinstance(metadata, dict) else []
    if isinstance(classified_as, list):
        for item in classified_as:
            if isinstance(item, dict):
                object_type_candidates.append(
                    first_present(
                        item.get("_label"),
                        item.get("label"),
                        item.get("name"),
                        item.get("content"),
                        item.get("id"),
                    )
                )

    object_type_candidates += collect_strings(
        metadata,
        keys={"type", "objectType", "classification", "classified_as"},
    )

    object_type = first_present(*object_type_candidates)

    # image URL
    image_url = extract_iiif_image_url_from_object(object_id, size="max")

    # Only run fallback if IIIF chain fails.
    if not is_present(image_url):
        image_url = extract_possible_image_from_metadata(metadata)

    # rights
    rights_candidates = collect_strings(
        metadata,
        keys={"rights", "license", "rightsStatement", "usageTerms"},
    )

    rights = first_present(*rights_candidates)

    # landing page
    landing_candidates = collect_strings(
        metadata,
        keys={"homepage", "landing_page", "isShownAt", "url"},
    )

    if isinstance(resolved_url, str) and "rijksmuseum.nl" in resolved_url and "/collectie/" in resolved_url:
        landing_candidates.insert(0, resolved_url)

    landing_page = first_present(*landing_candidates, object_id)

    return {
        "source_id": object_id,
        "object_number_or_uri_id": extract_uri_last_part(object_id),
        "title": title,
        "creator": creator,
        "date": date,
        "place": place,
        "object_type": object_type,
        "image_url": image_url,
        "rights": rights,
        "landing_page": landing_page,
    }


# ============================================================
# Coverage and main
# ============================================================

def calculate_coverage(df):
    """Calculate field coverage percentage."""
    coverage = {}
    total = len(df)

    for field in COMMON_FIELDS:
        if field not in df.columns:
            coverage[field] = 0.0
            continue

        present = df[field].apply(is_present).sum()
        coverage[field] = round(present / total * 100, 1) if total else 0.0

    return pd.DataFrame(
        [{"field": field, "coverage_percent": percent} for field, percent in coverage.items()]
    )


def main():
    query = "porcelain"
    limit = 50

    print(f"Searching Rijksmuseum for {limit} objects with query: {query!r}")
    object_ids = search_rijksmuseum(query=query, limit=limit)
    print(f"Found {len(object_ids)} object identifiers.\n")

    records = []

    for index, object_id in enumerate(object_ids, start=1):
        try:
            metadata, resolved_url = resolve_object_metadata(object_id)

            record = extract_rijksmuseum_metadata(
                metadata,
                resolved_url,
                object_id
            )

            records.append(record)

            missing = [
                field for field in COMMON_FIELDS
                if not is_present(record.get(field))
            ]

            object_no = record["object_number_or_uri_id"]

            if missing:
                print(
                    f"({index}/{len(object_ids)}) ID: {object_no}  "
                    f"Missing: {', '.join(missing)}"
                )
            else:
                print(
                    f"({index}/{len(object_ids)}) ID: {object_no}  "
                    f"Complete"
                )

        except Exception as error:
            print(
                f"({index}/{len(object_ids)}) ID: {object_id}  "
                f"Error: {error}"
            )

        time.sleep(0.2)

    df = pd.DataFrame(records)
    coverage_df = calculate_coverage(df)

    df.to_csv("rijksmuseum_porcelain_metadata.csv", index=False, encoding="utf-8-sig")
    coverage_df.to_csv("rijksmuseum_porcelain_coverage.csv", index=False, encoding="utf-8-sig")

    print("\nCoverage result:")
    print(coverage_df)

    print("\nSaved files:")
    print("- rijksmuseum_porcelain_metadata.csv")
    print("- rijksmuseum_porcelain_coverage.csv")


if __name__ == "__main__":
    main()
