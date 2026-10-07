"""
src/commute.py
────────────────
Commute-aware ranking: lets a user say where they actually need to get to
every day (college, office) and factors REAL road travel time — not
straight-line distance — into how PGs are ranked and shown.

Two external, keyless services do the work:
  - Nominatim (OpenStreetMap) geocodes the free-text destination into
    coordinates, restricted to the Bangalore North area so "MSRIT" doesn't
    resolve to an MSRIT in another city.
  - OSRM's public routing server returns real driving durations from the
    destination to every candidate PG in a SINGLE request (its /table
    endpoint — a distance/duration matrix), not one request per PG.

Both are public demo servers with no API key and no uptime guarantee, which
is exactly wrong for something a user is about to demo live. So every call
here is wrapped: a failure (timeout, non-200, malformed body) degrades to a
straight-line-distance estimate using an average effective city-driving
speed, never raises, and the result always says which method was used so
the UI can be honest about it ("~18 min (estimated)" vs "18 min").
"""

import math
from typing import Optional

import pandas as pd
import requests

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OSRM_TABLE_URL = "http://router.project-osrm.org/table/v1/driving/{coords}"

# Keeps geocoding results inside Bangalore North so a short query like
# "Hebbal" or "MSRIT" can't resolve to a same-named place elsewhere.
BANGALORE_NORTH_VIEWBOX = "77.45,13.15,77.75,12.95"  # left,top,right,bottom

# OpenStreetMap's usage policy requires a descriptive, non-generic User-Agent.
HTTP_HEADERS = {"User-Agent": "PG-Recommendation-System/1.0 (university project)"}

REQUEST_TIMEOUT_SECONDS = 6

# Used only when OSRM is unreachable — a conservative average speed for
# mixed Bangalore city-road driving (arterial + residential, with signals),
# deliberately on the slow side so the estimate doesn't undersell commute time.
FALLBACK_AVG_SPEED_KMH = 22.0

ZONE_BOUNDARIES_MIN = [15, 30, 45]  # -> "Under 15 min", "15-30 min", "30-45 min", "45+ min"

# How much real commute time counts toward final ranking, relative to the
# existing preference-match score. Deliberately not dominant — a user who
# set tight preferences (budget, amenities, location) shouldn't have a
# slightly-closer-but-otherwise-poor PG jump to #1 just because it's 5
# minutes nearer. 0.35 means a PG that's the best possible commute match
# but weakest preference match can still be out-ranked by one that's an
# excellent preference match with an average commute.
COMMUTE_WEIGHT = 0.35

# When ranking by commute, pull a wider pool of already-good matches from
# recommend() before blending in commute time, so a PG that was e.g. #12 on
# preference match but has by far the shortest commute still has a chance
# to surface — re-ranking only the preference top-5 would never let that
# happen in the first place.
COMMUTE_POOL_SIZE = 30


def geocode_destination(query: str) -> Optional[dict]:
    """
    Resolve a free-text destination ("MSRIT", "Manyata Tech Park") to
    coordinates within Bangalore North.

    Returns {"lat": float, "lon": float, "display_name": str} or None if the
    place couldn't be found or the geocoding service is unreachable.
    """
    query = (query or "").strip()
    if not query:
        return None

    try:
        resp = requests.get(
            NOMINATIM_URL,
            params={
                "q": query,
                "format": "json",
                "limit": 1,
                "viewbox": BANGALORE_NORTH_VIEWBOX,
                "bounded": 1,
            },
            headers=HTTP_HEADERS,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        results = resp.json()
    except (requests.RequestException, ValueError):
        return None

    if not results:
        return None

    top = results[0]
    try:
        return {
            "lat": float(top["lat"]),
            "lon": float(top["lon"]),
            "display_name": top.get("display_name", query),
        }
    except (KeyError, TypeError, ValueError):
        return None


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    """Great-circle distance in km — used only as the fallback estimator."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _estimate_fallback(dest_lat, dest_lon, pgs: list) -> dict:
    """Straight-line-distance estimate, used when OSRM can't be reached."""
    out = {}
    for pg_id, lat, lon in pgs:
        dist_km = _haversine_km(dest_lat, dest_lon, lat, lon)
        duration_min = (dist_km / FALLBACK_AVG_SPEED_KMH) * 60.0
        out[pg_id] = {
            "distance_km": round(dist_km, 1),
            "duration_min": round(duration_min),
            "method": "estimate",
        }
    return out


def get_commute_times(dest_lat: float, dest_lon: float, pgs: list) -> dict:
    """
    Real driving time + distance from (dest_lat, dest_lon) to each PG.

    Args:
        dest_lat, dest_lon: destination coordinates (e.g. the user's college).
        pgs: list of (pg_id, latitude, longitude) tuples for the candidate PGs.

    Returns:
        {pg_id: {"distance_km": float, "duration_min": int, "method": "osrm" | "estimate"}}
        for every pg_id passed in — this never drops entries, it falls back
        to an estimate for any PG that OSRM couldn't be reached for.
    """
    if not pgs:
        return {}

    # OSRM takes one coordinate list; destination is index 0, PGs follow.
    coords = [f"{dest_lon},{dest_lat}"] + [f"{lon},{lat}" for _, lat, lon in pgs]
    coord_str = ";".join(coords)
    destination_indices = ";".join(str(i) for i in range(1, len(pgs) + 1))

    try:
        resp = requests.get(
            OSRM_TABLE_URL.format(coords=coord_str),
            params={
                "sources": 0,
                "destinations": destination_indices,
                "annotations": "duration,distance",
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        body = resp.json()
        if body.get("code") != "Ok":
            raise ValueError(f"OSRM returned code={body.get('code')}")

        durations = body["durations"][0]   # seconds, one per PG (source is index 0)
        distances = body["distances"][0]   # meters

        out = {}
        for (pg_id, _, _), duration_s, distance_m in zip(pgs, durations, distances):
            if duration_s is None or distance_m is None:
                # OSRM couldn't route to this one specific point (e.g. off
                # the road network) — estimate just that one.
                out.update(_estimate_fallback(dest_lat, dest_lon, [
                    p for p in pgs if p[0] == pg_id
                ]))
                continue
            out[pg_id] = {
                "distance_km": round(distance_m / 1000.0, 1),
                "duration_min": round(duration_s / 60.0),
                "method": "osrm",
            }
        return out

    except (requests.RequestException, ValueError, KeyError, IndexError, TypeError):
        return _estimate_fallback(dest_lat, dest_lon, pgs)


def commute_zone(duration_min) -> str:
    """Bucket a commute duration into a human display zone."""
    if duration_min is None:
        return "Unknown"
    if duration_min < ZONE_BOUNDARIES_MIN[0]:
        return f"Under {ZONE_BOUNDARIES_MIN[0]} min"
    if duration_min < ZONE_BOUNDARIES_MIN[1]:
        return f"{ZONE_BOUNDARIES_MIN[0]}-{ZONE_BOUNDARIES_MIN[1]} min"
    if duration_min < ZONE_BOUNDARIES_MIN[2]:
        return f"{ZONE_BOUNDARIES_MIN[1]}-{ZONE_BOUNDARIES_MIN[2]} min"
    return f"{ZONE_BOUNDARIES_MIN[2]}+ min"


def apply_commute_ranking(pool: pd.DataFrame, dest_lat: float, dest_lon: float, top_n: int) -> pd.DataFrame:
    """
    Re-rank an already-scored pool of candidate PGs (the output of
    src.recommender.recommend, called with a wider top_n than normal) by
    blending in real commute time to (dest_lat, dest_lon), then cut to the
    top `top_n`.

    The existing preference-match score (normalized_score / match_rating)
    is left untouched — it still reflects how well a PG matches
    budget/amenities/location, independent of commute. Only the ORDER
    changes, weighted toward a shorter real commute by COMMUTE_WEIGHT.
    """
    if pool.empty:
        return pool

    pgs = list(zip(pool["PG_ID"], pool["Latitude"], pool["Longitude"]))
    commute_map = get_commute_times(dest_lat, dest_lon, pgs)

    pool = pool.copy()
    pool["commute_duration_min"] = pool["PG_ID"].map(lambda pid: commute_map.get(pid, {}).get("duration_min"))
    pool["commute_distance_km"] = pool["PG_ID"].map(lambda pid: commute_map.get(pid, {}).get("distance_km"))
    pool["commute_method"] = pool["PG_ID"].map(lambda pid: commute_map.get(pid, {}).get("method"))
    pool["commute_zone"] = pool["commute_duration_min"].map(commute_zone)

    min_d = pool["commute_duration_min"].min()
    max_d = pool["commute_duration_min"].max()
    if pd.isna(min_d) or max_d == min_d:
        pool["commute_score"] = 1.0
    else:
        pool["commute_score"] = 1.0 - (pool["commute_duration_min"] - min_d) / (max_d - min_d)

    pool["blended_score"] = (
        (1 - COMMUTE_WEIGHT) * pool["normalized_score"] + COMMUTE_WEIGHT * pool["commute_score"]
    )

    pool = pool.sort_values("blended_score", ascending=False).head(top_n).copy()
    pool["Rank"] = range(1, len(pool) + 1)
    return pool
