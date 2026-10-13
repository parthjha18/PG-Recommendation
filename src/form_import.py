"""
src/form_import.py
───────────────────
Turns exported Google Form responses (the form built by
scripts/create_pg_form.gs) into rows in the SAME schema as the main PG
dataset, so real, collected PGs can be loaded and recommended exactly like
the generated ones.

Shape of the conversion
  - One form response = one PG. The dataset stores one row per
    (PG, sharing type), so a PG with 2- and 3-sharing rooms becomes 2 rows.
  - PG_IDs for real rows start at 10001 and are derived from the response's
    position by timestamp, so they stay stable as more responses arrive and
    can never collide with the generated PGs (ratings/reviews in Postgres
    are keyed by PG_ID alone).
  - Coordinates come from the Google Maps link; if that can't be resolved
    the address is geocoded instead; if neither works the response is
    skipped with a warning rather than guessed.
  - Nothing is invented: anything unparseable is skipped or left blank and
    reported in the returned warnings.
"""

import re
import time
from urllib.parse import unquote

import pandas as pd
import requests

from src.commute import HTTP_HEADERS, NOMINATIM_URL, _haversine_km

# The generated dataset measures Distance_From_Center_KM from Hebbal
# (Hebbal rows are 0.0 there), so real rows are measured from the same point.
CITY_CENTER = (13.035, 77.597)

REAL_ID_BASE = 10000

SHARING_SLOTS = [  # (form label, dataset Sharing value)
    ("1 Sharing", "Single"),
    ("2 Sharing", "Double"),
    ("3 Sharing", "Triple"),
    ("4 Sharing", "Quad"),
]

FACILITY_NEEDLES = {   # dataset column -> text inside the grid column header
    "WiFi": "[wi-fi]", "AC": "[ac]", "Laundry": "[washing", "Parking": "[parking]",
    "Housekeeping": "[housekeeping", "Lift": "[lift]", "Security": "[security",
    "CCTV": "[cctv]", "Power_Backup": "[power backup]", "Drinking_Water": "[drinking water",
}
RULE_NEEDLES = {
    "Pets_Allowed": "[pets", "Visitors_Allowed": "[visitors", "Smoking_Area": "[smoking",
}

OUTPUT_COLUMNS = [
    "PG_ID", "Location", "Latitude", "Longitude", "Distance_From_Center_KM", "Rent",
    "Sharing", "Gender", "Meals_Per_Day", "Weekend_Food", "WiFi", "AC", "Laundry",
    "Parking", "Housekeeping", "Lift", "Security", "CCTV", "Power_Backup",
    "Drinking_Water", "Floors", "Food_Type", "Pets_Allowed", "Visitors_Allowed",
    "Smoking_Area", "Curfew_Time", "Available_From", "Availability",
    "PG_Name", "Address", "Source",
]

_COORD_PATTERNS = [
    r"@(-?\d+\.\d+),(-?\d+\.\d+)",
    r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)",
    r"[?&](?:q|ll|query|center|destination)=(-?\d+\.\d+)(?:,|%2C)(-?\d+\.\d+)",
]

_last_osm_call = 0.0


# ─────────────────────────────────────────────────────────────
# LOCATION RESOLUTION
# ─────────────────────────────────────────────────────────────

def coords_from_text(text: str):
    """Pull (lat, lon) out of a Google Maps URL string, or None."""
    text = unquote(str(text))
    for pattern in _COORD_PATTERNS:
        m = re.search(pattern, text)
        if m:
            lat, lon = float(m.group(1)), float(m.group(2))
            if 5 < lat < 40 and 60 < lon < 100:   # sanity: somewhere in India
                return lat, lon
    return None


def _osm_get(url, params):
    """Nominatim allows ~1 request/second; space our calls out."""
    global _last_osm_call
    wait = 1.1 - (time.time() - _last_osm_call)
    if wait > 0:
        time.sleep(wait)
    _last_osm_call = time.time()
    resp = requests.get(url, params=params, headers=HTTP_HEADERS, timeout=10)
    resp.raise_for_status()
    return resp.json()


def resolve_location(maps_url: str, address: str):
    """
    Best-effort coordinates for a PG: Maps link first (directly, then by
    following a short-link redirect), then geocoding the address.
    Returns {"lat", "lon", "how"} or None.
    """
    maps_url = (maps_url or "").strip()
    if maps_url and maps_url.lower() != "nan":
        found = coords_from_text(maps_url)
        if found:
            return {"lat": found[0], "lon": found[1], "how": "maps link"}
        try:
            r = requests.get(maps_url, headers=HTTP_HEADERS, timeout=10, allow_redirects=True)
            for candidate in [r.url] + [h.headers.get("Location", "") for h in r.history]:
                found = coords_from_text(candidate)
                if found:
                    return {"lat": found[0], "lon": found[1], "how": "maps short-link redirect"}
        except requests.RequestException:
            pass

    if address and str(address).lower() != "nan":
        try:
            hits = _osm_get(NOMINATIM_URL, {
                "q": address, "format": "json", "limit": 1, "countrycodes": "in",
            })
            if hits:
                return {"lat": float(hits[0]["lat"]), "lon": float(hits[0]["lon"]), "how": "address geocode"}
        except (requests.RequestException, ValueError, KeyError):
            pass
    return None


def reverse_locality(lat: float, lon: float) -> str:
    """Neighbourhood name for coordinates (used when the form's area was 'Other')."""
    try:
        data = _osm_get("https://nominatim.openstreetmap.org/reverse", {
            "lat": lat, "lon": lon, "format": "json", "zoom": 16, "addressdetails": 1,
        })
        addr = data.get("address", {})
        for key in ("suburb", "neighbourhood", "quarter", "city_district", "village"):
            if addr.get(key):
                return addr[key].strip().lower()
    except (requests.RequestException, ValueError):
        pass
    return "other"


# ─────────────────────────────────────────────────────────────
# FIELD PARSERS
# ─────────────────────────────────────────────────────────────

def _find_col(columns, *needles):
    for c in columns:
        low = str(c).strip().lower()
        if all(n in low for n in needles):
            return c
    return None


def _clean(value) -> str:
    s = "" if value is None else str(value).strip()
    return "" if s.lower() == "nan" else s


def parse_rent(value):
    s = re.sub(r"[₹,\s]|rs\.?", "", _clean(value), flags=re.I)
    if not s:
        return None
    try:
        rent = int(round(float(s)))
        return rent if rent > 0 else None
    except ValueError:
        return None


def yes_no(value) -> str:
    return "Yes" if _clean(value).lower().startswith("y") else "No"


def parse_curfew(value):
    """Map the form's curfew answer onto the dataset's four values, or None."""
    s = _clean(value).lower()
    if not s:
        return None
    if "no curfew" in s or s in ("none", "no", "nil", "na", "n/a"):
        return "No Curfew"
    m = re.search(r"(\d{1,2})(?::\d{2})?\s*(am|pm)?", s)
    if not m:
        return None
    hour = int(m.group(1))
    if m.group(2) == "am" or hour == 12 or hour == 0:
        hour = 11   # midnight-ish closing: loosest bucket we model
    return f"{min(max(hour, 9), 11)}:00 PM"


def parse_available_from(value, dayfirst: bool):
    s = _clean(value)
    if not s:
        return ""
    ts = pd.to_datetime(s, dayfirst=dayfirst, errors="coerce")
    return "" if pd.isna(ts) else ts.strftime("%Y-%m-%d")


# ─────────────────────────────────────────────────────────────
# MAIN CONVERSION
# ─────────────────────────────────────────────────────────────

def build_real_dataset(responses: pd.DataFrame, dayfirst: bool = True,
                       resolver=resolve_location, locality_lookup=reverse_locality):
    """
    Convert form responses into dataset rows.

    Args:
        responses:       DataFrame read from the exported responses CSV.
        dayfirst:        Whether dates in the export are DD/MM/YYYY (India) or MM/DD/YYYY.
        resolver:        resolve_location-compatible callable (injectable for tests).
        locality_lookup: reverse_locality-compatible callable (injectable for tests).

    Returns:
        (DataFrame with OUTPUT_COLUMNS, list of warning strings)
    """
    warnings = []
    cols = list(responses.columns)

    c_ts = _find_col(cols, "timestamp")
    c_name = _find_col(cols, "pg name")
    c_addr = _find_col(cols, "full address")
    c_area = _find_col(cols, "area")
    c_maps = _find_col(cols, "google maps")
    c_gender = _find_col(cols, "gender")
    c_vac = _find_col(cols, "vacancy", "right now")
    c_next = _find_col(cols, "next vacancy")
    c_meals = _find_col(cols, "meals per day")
    c_weekend = _find_col(cols, "weekends")
    c_ftype = _find_col(cols, "food type")
    c_curfew = _find_col(cols, "curfew")
    c_floors = _find_col(cols, "floors")
    rent_cols = [_find_col(cols, label.lower(), "rent") for label, _ in SHARING_SLOTS]
    fac_cols = {k: _find_col(cols, "facilities", n) for k, n in FACILITY_NEEDLES.items()}
    rule_cols = {k: _find_col(cols, "rules", n) for k, n in RULE_NEEDLES.items()}

    missing = [n for n, c in [("PG Name", c_name), ("Full Address", c_addr), ("Gender", c_gender),
                              ("Meals per day", c_meals), ("Floors", c_floors)] if c is None]
    missing += [f"facility:{k}" for k, c in fac_cols.items() if c is None]
    if missing:
        raise ValueError(f"Responses file is missing expected columns: {missing}. "
                         "Was it exported from the PG Details form?")

    work = responses.copy()
    if c_ts:
        work["_ts"] = pd.to_datetime(work[c_ts], dayfirst=dayfirst, errors="coerce")
        work = work.sort_values("_ts", kind="stable")
    work = work.reset_index(drop=True)

    rows = []
    for idx, resp in work.iterrows():
        label = _clean(resp[c_name]) or f"response #{idx + 1}"
        address = _clean(resp[c_addr])

        loc = resolver(_clean(resp[c_maps]) if c_maps else "", address)
        if not loc:
            warnings.append(f"SKIPPED '{label}': couldn't get coordinates from the Maps link or the address.")
            continue

        area = _clean(resp[c_area]) if c_area else ""
        if not area or area.lower().startswith("other"):
            locality = locality_lookup(loc["lat"], loc["lon"])
        else:
            locality = area.lower()

        meals_match = re.search(r"\d", _clean(resp[c_meals]))
        meals = int(meals_match.group()) if meals_match else None
        if meals is None:
            warnings.append(f"SKIPPED '{label}': meals per day missing.")
            continue

        floors_val = parse_rent(resp[c_floors])   # same "whole number" parsing
        curfew = parse_curfew(resp[c_curfew]) if c_curfew else None
        if curfew is None:
            warnings.append(f"'{label}': curfew '{_clean(resp[c_curfew]) if c_curfew else ''}' not understood; left blank.")

        vacancy_text = _clean(resp[c_vac]).lower() if c_vac else ""
        base = {
            "Location": locality,
            "Latitude": round(loc["lat"], 6),
            "Longitude": round(loc["lon"], 6),
            "Distance_From_Center_KM": round(_haversine_km(*CITY_CENTER, loc["lat"], loc["lon"]), 2),
            "Gender": _clean(resp[c_gender]),
            "Meals_Per_Day": meals,
            "Weekend_Food": yes_no(resp[c_weekend]) if c_weekend else "No",
            "Floors": floors_val if floors_val is not None else "",
            "Food_Type": _clean(resp[c_ftype]) if c_ftype else "",
            "Curfew_Time": curfew or "",
            "Available_From": parse_available_from(resp[c_next], dayfirst) if c_next else "",
            "PG_Name": _clean(resp[c_name]),
            "Address": address,
            "Source": "form",
        }
        for col, src in fac_cols.items():
            base[col] = yes_no(resp[src])
        for col, src in rule_cols.items():
            base[col] = yes_no(resp[src]) if src else "No"

        made_any = False
        for slot_no, ((slot_label, sharing), rent_col) in enumerate(zip(SHARING_SLOTS, rent_cols), start=1):
            if rent_col is None:
                continue
            rent = parse_rent(resp[rent_col])
            if rent is None:
                continue
            made_any = True
            rows.append({
                **base,
                "PG_ID": REAL_ID_BASE + (idx + 1) * 10 + slot_no,
                "Rent": rent,
                "Sharing": sharing,
                "Availability": "Available" if slot_label.lower() in vacancy_text else "Full",
            })
        if not made_any:
            warnings.append(f"SKIPPED '{label}': no valid rent for any sharing type.")

    out = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    if not out.empty:
        # Same PG submitted twice (e.g. two friends): keep the latest entry.
        key = out[["PG_Name", "Address", "Sharing"]].apply(lambda s: s.str.lower().str.strip())
        dup = key.duplicated(keep="last")
        if dup.any():
            warnings.append(f"{int(dup.sum())} duplicate PG/sharing row(s) dropped (kept the latest submission).")
        out = out[~dup].reset_index(drop=True)
    return out, warnings
