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

import json
import os
import re
import time
from urllib.parse import unquote, unquote_plus

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
    "PG_Name", "Address", "Source", "Location_Accuracy",
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


_PLACE_PIN = r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)"

# Bengaluru metro box; address-geocoded results outside it are rejected as wrong-city matches.
BENGALURU_BOX = (12.70, 13.30, 77.30, 77.90)   # lat_min, lat_max, lon_min, lon_max


def _first_coords(pattern: str, text: str):
    m = re.search(pattern, unquote(str(text)))
    if m:
        lat, lon = float(m.group(1)), float(m.group(2))
        if 5 < lat < 40 and 60 < lon < 100:   # sanity: somewhere in India
            return lat, lon
    return None


def coords_from_page(final_url: str, redirect_urls, body: str):
    """
    EXACT coordinates for a Google Maps place reached through a short link,
    or None. Only trusted sources are used:
      1. the place's own pin (!3d..!4d..) in a URL;
      2. that same pin in the page body, but only if the page holds exactly
         ONE distinct pin (otherwise it may belong to a related place);
      3. the map viewport centre (@lat,lng) in a URL - slightly offset from the pin.
    The page body's generic "center=" / [null,null,lat,lng] values are
    deliberately NOT used: Google serves the same default map centre in them
    for every place, which silently put different PGs at one identical spot.
    """
    urls = [final_url, *redirect_urls]
    for u in urls:
        hit = _first_coords(_PLACE_PIN, u)
        if hit:
            return hit
    pins = {m for m in re.findall(_PLACE_PIN, unquote(body or ""))}
    if len(pins) == 1:
        lat, lon = map(float, next(iter(pins)))
        if 5 < lat < 40 and 60 < lon < 100:
            return lat, lon
    for u in urls:
        hit = coords_from_text(u)
        if hit:
            return hit
    return None


def address_candidates_from_maps_url(url: str):
    """
    Geocodable address strings from a Maps place URL that carries no coordinates,
    e.g. .../maps/place/NAME,+Street,+Area,+Bengaluru,+Karnataka+560037/... or
    ...?daddr=NAME,+Street,+Area,... Most specific first; the business name
    (first part) is dropped in later candidates because geocoders rarely know it.
    """
    url = str(url or "")
    text = ""
    if "/maps/place/" in url:
        text = url.split("/maps/place/", 1)[1].split("/", 1)[0].split("?", 1)[0]
    else:
        m = re.search(r"[?&](?:daddr|q|destination)=([^&]+)", url)
        if m:
            text = m.group(1)
    text = unquote_plus(text).strip()
    parts = [p.strip() for p in text.split(",") if p.strip()]
    if len(parts) < 2:
        return []
    # full text, then drop leading parts one at a time (business name first, then
    # street, ...) but never go coarser than the last three parts (area, city, pin).
    candidates = [parts] + [parts[i:] for i in range(1, len(parts)) if len(parts) - i >= 3]
    out = []
    for cand in candidates:
        s = ", ".join(cand)
        if s and s not in out:
            out.append(s)
    return out


def _in_bengaluru(lat, lon) -> bool:
    return BENGALURU_BOX[0] <= lat <= BENGALURU_BOX[1] and BENGALURU_BOX[2] <= lon <= BENGALURU_BOX[3]


def geocode_text(query: str):
    """Nominatim lookup biased to Bengaluru; (lat, lon) or None. Wrong-city hits are rejected."""
    try:
        hits = _osm_get(NOMINATIM_URL, {
            "q": query, "format": "json", "limit": 1, "countrycodes": "in",
            "viewbox": "77.30,13.30,77.90,12.70", "bounded": 0,
        })
        if hits:
            lat, lon = float(hits[0]["lat"]), float(hits[0]["lon"])
            if _in_bengaluru(lat, lon):
                return lat, lon
    except (requests.RequestException, ValueError, KeyError):
        pass
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
            redirects = [h.headers.get("Location", "") for h in r.history]
            found = coords_from_page(r.url, redirects, r.text)
            if found:
                return {"lat": found[0], "lon": found[1], "how": "maps short-link page"}
            # No exact pin: geocode the street address Google shows in the place URL.
            for u in [r.url, *redirects]:
                for query in address_candidates_from_maps_url(u):
                    hit = geocode_text(query)
                    if hit:
                        return {"lat": hit[0], "lon": hit[1], "how": "address from maps link (approximate)"}
        except requests.RequestException:
            pass

    if address and str(address).lower() != "nan":
        hit = geocode_text(address) or geocode_text(", ".join(address.split(",")[-4:]))
        if hit:
            return {"lat": hit[0], "lon": hit[1], "how": "typed address geocode (approximate)"}
    return None


# Centroids of the dataset's 15 localities (the generated data uses one point per locality).
AREA_CENTROIDS = {
    "bagalur": (13.12, 77.65), "hebbal": (13.035, 77.597), "hennur": (13.05, 77.64),
    "horamavu": (13.03, 77.67), "jakkur": (13.08, 77.60), "kalyan nagar": (13.025, 77.64),
    "kammanahalli": (13.02, 77.635), "kodigehalli": (13.07, 77.58), "kothanur": (13.06, 77.65),
    "nagawara": (13.04, 77.62), "rt nagar": (13.022, 77.594), "sahakar nagar": (13.06, 77.58),
    "thanisandra": (13.05, 77.62), "vidyaranyapura": (13.08, 77.55), "yelahanka": (13.10, 77.596),
}
AREA_TRUST_RADIUS_KM = 6.0   # a dropdown pick farther than this from the PG's coordinates is distrusted


def _clean_locality(name: str) -> str:
    """'AECS Layout A Block' -> 'aecs layout' (block/stage/phase suffixes are too fine-grained)."""
    n = name.strip().lower()
    return re.sub(r"\s+(?:[a-z]\s+block|\d+(?:st|nd|rd|th)?\s+(?:block|stage|phase)|block\s*\d+)$", "", n).strip()


def locality_from_address(addr: dict) -> str:
    """
    Pick a human neighbourhood name from a Nominatim address dict. Real
    neighbourhood names are preferred over BBMP administrative labels
    ('Priyadarshini Ward', 'EPIP Zone'), which are only a last resort.
    """
    def admin(n):
        return n.strip().lower().endswith(("ward", "zone"))

    if addr.get("quarter"):
        return _clean_locality(addr["quarter"])
    if addr.get("suburb") and not admin(addr["suburb"]):
        return _clean_locality(addr["suburb"])
    for key in ("neighbourhood", "city_district", "village"):
        if addr.get(key) and not admin(addr[key]) and "city corporation" not in addr[key].lower():
            return _clean_locality(addr[key])
    if addr.get("suburb"):
        return _clean_locality(addr["suburb"])
    return "other"


def reverse_locality(lat: float, lon: float) -> str:
    """Neighbourhood name for coordinates (see locality_from_address)."""
    try:
        data = _osm_get("https://nominatim.openstreetmap.org/reverse", {
            "lat": lat, "lon": lon, "format": "json", "zoom": 16, "addressdetails": 1,
        })
        return locality_from_address(data.get("address", {}))
    except (requests.RequestException, ValueError):
        return "other"


def choose_locality(area: str, lat: float, lon: float, locality_lookup) -> str:
    """
    The form's dropdown area is used when it is plausible for the PG's
    coordinates (people often pick the nearest listed area even when it is
    kilometres away); otherwise the coordinates decide.
    """
    area = (area or "").strip().lower()
    if area and not area.startswith("other") and area in AREA_CENTROIDS:
        if _haversine_km(lat, lon, *AREA_CENTROIDS[area]) <= AREA_TRUST_RADIUS_KM:
            return area
    looked_up = locality_lookup(lat, lon)
    if looked_up and looked_up != "other":
        return looked_up
    return area if area and not area.startswith("other") else "other"


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
            warnings.append(
                f"SKIPPED '{label}': couldn't work out its location. Ask them to search the PG in "
                "Google Maps, tap Share -> Copy link, and re-submit (links starting with share.google don't work).")
            continue

        area = _clean(resp[c_area]) if c_area else ""
        locality = choose_locality(area, loc["lat"], loc["lon"], locality_lookup)

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
            # exact = the place's own pin; approximate = geocoded from an address
            "Location_Accuracy": "approximate" if "approximate" in loc.get("how", "") else "exact",
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


# ─────────────────────────────────────────────────────────────
# LOOKUP CACHE
# ─────────────────────────────────────────────────────────────

class CachedLocator:
    """
    Remembers successful coordinate / locality lookups on disk, so re-importing
    the sheet only geocodes responses that are NEW. Failed lookups are never
    cached (they may be a temporary network problem), and a PG whose Maps link
    or address is edited gets a fresh lookup because the cache key changes.
    """

    def __init__(self, path=None, resolver=resolve_location, locality_lookup=reverse_locality):
        self.path = path
        self._resolver = resolver
        self._locality = locality_lookup
        self.lookups = 0          # network lookups actually performed (for tests / logging)
        self._data = {"loc": {}, "locality": {}}
        if path and os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    self._data.update(json.load(f))
            except (OSError, ValueError):
                pass              # unreadable cache == empty cache

    def resolve(self, maps_url, address):
        key = f"{(maps_url or '').strip()}||{(address or '').strip()}"
        if key in self._data["loc"]:
            return self._data["loc"][key]
        self.lookups += 1
        found = self._resolver(maps_url, address)
        if found:
            self._data["loc"][key] = found
        return found

    def locality(self, lat, lon):
        key = f"{lat:.5f},{lon:.5f}"
        if key in self._data["locality"]:
            return self._data["locality"][key]
        self.lookups += 1
        name = self._locality(lat, lon)
        if name and name != "other":
            self._data["locality"][key] = name
        return name

    def save(self):
        if not self.path:
            return
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=1)
