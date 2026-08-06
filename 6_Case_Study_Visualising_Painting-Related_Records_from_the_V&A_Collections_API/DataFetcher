import json
import re
import time
import colorsys
import math
from collections import Counter, defaultdict
from io import BytesIO
from pathlib import Path

import requests
from PIL import Image, ImageOps


API_URL = "https://api.vam.ac.uk/v2/objects/search"

QUERY = "painting"
TARGET_COUNT = 400
PAGE_SIZE = 100
MAX_PAGES = 40
MAX_IMAGES_FOR_COLOUR = 400

OUTPUT_FILE = Path("data.json")

# Colour-extraction settings
COLOUR_ANALYSIS_SIZE = 300
QUANTIZED_COLOURS = 16
EDGE_FRACTION = 0.08


SESSION = requests.Session()
SESSION.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 (compatible; VAM-Painting-Colour-Extractor/2.0; "
            "+https://www.vam.ac.uk/)"
        )
    }
)


def clean_text(value, fallback="Unknown"):
    if value is None:
        return fallback
    if isinstance(value, str):
        value = value.strip()
        return value if value else fallback
    return str(value)


def is_painting_related(item):
    object_type = clean_text(item.get("objectType"), "").lower()
    title = clean_text(item.get("_primaryTitle"), "").lower()

    painting_terms = [
        "painting",
        "oil painting",
        "watercolour",
        "watercolor",
        "portrait",
        "landscape",
        "miniature",
        "panel painting",
        "screen painting",
    ]

    return any(term in object_type for term in painting_terms) or any(
        term in title for term in ["painting", "portrait", "landscape"]
    )


def extract_year(date_text):
    if not date_text:
        return None

    text = str(date_text).lower()

    match = re.search(r"\b(1[0-9]{3}|20[0-2][0-9])\b", text)
    if match:
        return int(match.group(1))

    century_match = re.search(r"(\d{1,2})(st|nd|rd|th)\s+century", text)
    if century_match:
        century = int(century_match.group(1))
        return (century - 1) * 100 + 50

    return None


def century_label(year):
    if not year:
        return "Unknown"

    century = ((year - 1) // 100) + 1
    start = (century - 1) * 100 + 1
    end = century * 100

    return f"{start}-{end}"


def extract_thumbnail_url(item, size="!300,300"):
    images = item.get("_images") or {}

    if images.get("_primary_thumbnail"):
        return images["_primary_thumbnail"]

    image_id = item.get("_primaryImageId")
    if image_id:
        return f"https://framemark.vam.ac.uk/collections/{image_id}/full/{size}/0/default.jpg"

    return None


def extract_large_image_url(item, size="!900,900"):
    image_id = item.get("_primaryImageId")
    if image_id:
        return f"https://framemark.vam.ac.uk/collections/{image_id}/full/{size}/0/default.jpg"

    return extract_thumbnail_url(item)


def _resampling_filter():
    """Return a Pillow resampling filter compatible with old and new versions."""
    try:
        return Image.Resampling.LANCZOS
    except AttributeError:
        return Image.LANCZOS


def _quantize_method():
    """Return Pillow's median-cut quantisation method compatibly."""
    try:
        return Image.Quantize.MEDIANCUT
    except AttributeError:
        return Image.MEDIANCUT


def _no_dither():
    try:
        return Image.Dither.NONE
    except AttributeError:
        return Image.NONE


def _palette_rgb(palette, index):
    start = index * 3
    colour = palette[start:start + 3]
    if len(colour) != 3:
        return None
    return tuple(colour)


def _is_background_like(r, g, b):
    """
    Reject obvious scanning/background tones.

    This is deliberately broader than the former pure-white/pure-black rule,
    but it does not remove every pale colour because pale paint can be real
    artwork content.
    """
    h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)

    # Very light, low-saturation paper/scanner background.
    if v > 0.90 and s < 0.16:
        return True

    # Almost black image borders or empty pixels.
    if v < 0.055:
        return True

    return False


def extract_dominant_colour(image_url):
    """
    Extract one representative colour while preserving the original JSON shape.

    Method:
    1. Analyse the larger artwork image rather than the tiny thumbnail.
    2. Resize to at most 300 x 300 pixels.
    3. Quantise the image to 16 colours with Pillow median cut.
    4. Score each colour using:
       - overall pixel share,
       - extra weight for pixels near the image centre,
       - saturation and mid-tone preference,
       - a penalty for colours concentrated around the image border.
    5. Exclude obvious near-white/near-black background colours.

    The returned dictionary keeps exactly the same keys as the previous script:
    hex, rgb, hue, saturation and value.
    """
    if not image_url:
        return None

    try:
        response = SESSION.get(image_url, timeout=30)
        response.raise_for_status()

        image = Image.open(BytesIO(response.content))
        image = ImageOps.exif_transpose(image).convert("RGB")
        image.thumbnail(
            (COLOUR_ANALYSIS_SIZE, COLOUR_ANALYSIS_SIZE),
            _resampling_filter(),
        )

        if image.width < 2 or image.height < 2:
            return None

        quantized = image.quantize(
            colors=QUANTIZED_COLOURS,
            method=_quantize_method(),
            dither=_no_dither(),
        )

        palette = quantized.getpalette()
        indices = list(quantized.getdata())

        if not palette or not indices:
            return None

        width, height = quantized.size
        raw_counts = Counter(indices)
        weighted_counts = defaultdict(float)
        border_counts = Counter()

        edge_x = max(1, round(width * EDGE_FRACTION))
        edge_y = max(1, round(height * EDGE_FRACTION))

        total_weight = 0.0
        total_border_pixels = 0

        for y in range(height):
            for x in range(width):
                index = indices[y * width + x]

                # Centre weighting: centre pixels count up to twice as much as
                # corner pixels. This reduces the influence of borders/mounts.
                nx = abs(((x + 0.5) / width) - 0.5) * 2
                ny = abs(((y + 0.5) / height) - 0.5) * 2
                radial_distance = min(1.0, math.sqrt(nx * nx + ny * ny) / math.sqrt(2))
                centre_weight = 1.0 + (1.0 - radial_distance)

                weighted_counts[index] += centre_weight
                total_weight += centre_weight

                is_border = (
                    x < edge_x
                    or x >= width - edge_x
                    or y < edge_y
                    or y >= height - edge_y
                )
                if is_border:
                    border_counts[index] += 1
                    total_border_pixels += 1

        total_pixels = width * height
        candidates = []

        for index, count in raw_counts.items():
            rgb = _palette_rgb(palette, index)
            if rgb is None:
                continue

            r, g, b = rgb
            h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)

            if _is_background_like(r, g, b):
                continue

            pixel_share = count / total_pixels
            weighted_share = weighted_counts[index] / total_weight
            border_share = (
                border_counts[index] / total_border_pixels
                if total_border_pixels
                else 0.0
            )

            # Favour colours with some chroma without completely rejecting
            # genuinely muted paintings.
            saturation_factor = 0.58 + (0.42 * s)

            # Avoid selecting extreme highlights/shadows when a stronger
            # mid-tone cluster is available.
            midtone = max(0.0, 1.0 - abs(v - 0.55) / 0.55)
            brightness_factor = 0.78 + (0.22 * midtone)

            # Penalise clusters disproportionately concentrated around the
            # outer edge, especially neutral clusters typical of paper/mounts.
            border_penalty = 1.0
            if border_share > 0.28:
                border_penalty *= max(0.28, 1.0 - (border_share - 0.28) * 1.7)
            if s < 0.20 and border_share > pixel_share * 1.35:
                border_penalty *= 0.55

            score = (
                (0.45 * pixel_share + 0.55 * weighted_share)
                * saturation_factor
                * brightness_factor
                * border_penalty
            )

            candidates.append((score, count, r, g, b, h, s, v))

        if not candidates:
            # Conservative fallback: retain the old behaviour if every cluster
            # was excluded by the stronger background checks.
            for index, count in raw_counts.most_common():
                rgb = _palette_rgb(palette, index)
                if rgb is None:
                    continue
                r, g, b = rgb
                if r > 248 and g > 248 and b > 248:
                    continue
                if r < 8 and g < 8 and b < 8:
                    continue
                h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
                candidates.append((0.0, count, r, g, b, h, s, v))
                break

        if not candidates:
            return None

        # Highest visual score wins; pixel count is a stable tie-breaker.
        _, _, r, g, b, h, s, v = max(candidates, key=lambda item: (item[0], item[1]))

        return {
            "hex": f"#{r:02x}{g:02x}{b:02x}",
            "rgb": [r, g, b],
            "hue": round(h * 360, 2),
            "saturation": round(s, 3),
            "value": round(v, 3),
        }

    except Exception as error:
        print(f"Colour extraction failed: {image_url} | {error}")
        return None


def fetch_raw_records():
    selected_records = []
    page = 1

    while len(selected_records) < TARGET_COUNT and page <= MAX_PAGES:
        params = {
            "q": QUERY,
            "page_size": PAGE_SIZE,
            "page": page,
            "response_format": "json",
        }

        print(f"Fetching V&A page {page}...")
        response = SESSION.get(API_URL, params=params, timeout=30)
        response.raise_for_status()

        data = response.json()
        records = data.get("records", [])

        if not records:
            break

        for item in records:
            if is_painting_related(item):
                selected_records.append(item)

            if len(selected_records) >= TARGET_COUNT:
                break

        print(f"Selected records so far: {len(selected_records)}")
        page += 1
        time.sleep(0.2)

    return selected_records[:TARGET_COUNT]


def normalise_records(raw_records):
    cleaned = []
    colour_counter = 0

    for index, item in enumerate(raw_records, start=1):
        maker = item.get("_primaryMaker") or {}
        system_number = clean_text(item.get("systemNumber"), "")

        title = clean_text(item.get("_primaryTitle"), "Untitled object")
        creator = clean_text(maker.get("name"), "Unknown maker")
        date_text = clean_text(item.get("_primaryDate"), "Unknown date")
        place = clean_text(item.get("_primaryPlace"), "Unknown place")
        object_type = clean_text(item.get("objectType"), "Unknown type")

        year = extract_year(date_text)
        thumbnail_url = extract_thumbnail_url(item)
        image_url = extract_large_image_url(item)

        dominant_colour = None

        # Important change: analyse the larger image URL, not the tiny thumbnail.
        if image_url and colour_counter < MAX_IMAGES_FOR_COLOUR:
            print(
                f"Extracting colour {colour_counter + 1}/{MAX_IMAGES_FOR_COLOUR}: "
                f"{system_number}"
            )
            dominant_colour = extract_dominant_colour(image_url)
            colour_counter += 1

        record = {
            "object_id": system_number,
            "title": title,
            "creator": creator,
            "date": date_text,
            "year": year,
            "century": century_label(year),
            "place": place,
            "object_type": object_type,
            "thumbnail_url": thumbnail_url,
            "image_url": image_url,
            "landing_page": (
                f"https://collections.vam.ac.uk/item/{system_number}/"
                if system_number
                else None
            ),
            "dominant_colour": dominant_colour,
        }

        cleaned.append(record)

    return cleaned


def build_summary(records):
    return {
        "total_records": len(records),
        "records_with_year": sum(1 for r in records if r.get("year")),
        "records_with_image": sum(1 for r in records if r.get("image_url")),
        "records_with_dominant_colour": sum(
            1 for r in records if r.get("dominant_colour")
        ),
        "unique_centuries": len(
            set(r["century"] for r in records if r["century"] != "Unknown")
        ),
        "unique_places": len(
            set(r["place"] for r in records if r["place"] != "Unknown place")
        ),
    }


def main():
    raw_records = fetch_raw_records()
    cleaned_records = normalise_records(raw_records)

    output = {
        "metadata": {
            "api_name": "V&A Collections API v2",
            "endpoint": API_URL,
            "query": QUERY,
            "requested_count": TARGET_COUNT,
            "returned_count": len(cleaned_records),
            "colour_extraction_limit": MAX_IMAGES_FOR_COLOUR,
            "note": (
                "This is a query-based sample of painting-related records from the V&A Collections API. "
                "The dataset was filtered for painting-related records and should not be treated as a random "
                "sample of the full V&A collection."
            ),
        },
        "summary": build_summary(cleaned_records),
        "records": cleaned_records,
    }

    with OUTPUT_FILE.open("w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\nSaved: {OUTPUT_FILE.resolve()}")
    print(json.dumps(output["summary"], indent=2))


if __name__ == "__main__":
    main()
