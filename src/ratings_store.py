"""
src/ratings_store.py
─────────────────────
Handles persistent user ratings stored in data/ratings.csv.

Provides:
  - add_rating(pg_id, rating)       → append to CSV
  - get_stats(pg_id)                → {average_rating, rating_count}
  - get_all_stats()                 → dict keyed by pg_id
  - compute_confidence(...)         → consistency × (avg / 5)
  - compute_trust(...)              → log(1 + count) × (avg / 5)
"""

import os
import math
import threading
import pandas as pd

# ── File path ─────────────────────────────────────────────────
_BASE  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_PATH = os.path.join(_BASE, "data", "ratings.csv")

# Thread-safe write lock
_lock = threading.Lock()

# ── Defaults when a PG has zero user ratings ──────────────────
_DEFAULT_AVG   = 3.5   # neutral starting average
_DEFAULT_COUNT = 0


# ─────────────────────────────────────────────────────────────
# INIT: ensure file exists
# ─────────────────────────────────────────────────────────────

def _ensure_csv() -> None:
    """Create ratings.csv with headers if it doesn't exist."""
    if not os.path.exists(CSV_PATH):
        os.makedirs(os.path.dirname(CSV_PATH), exist_ok=True)
        pd.DataFrame(columns=["pg_id", "rating"]).to_csv(CSV_PATH, index=False)


# ─────────────────────────────────────────────────────────────
# WRITE
# ─────────────────────────────────────────────────────────────

def add_rating(pg_id: int, rating: int) -> dict:
    """
    Append a new rating to ratings.csv.

    Args:
        pg_id:  Integer PG identifier (matches PG_ID column in dataset)
        rating: Integer 1–5

    Returns:
        Updated stats dict for this PG: {average_rating, rating_count}

    Raises:
        ValueError: If rating is not in 1–5 range.
    """
    if not (1 <= int(rating) <= 5):
        raise ValueError(f"Rating must be 1–5, got {rating}")

    _ensure_csv()

    row = pd.DataFrame([{"pg_id": int(pg_id), "rating": int(rating)}])

    with _lock:
        row.to_csv(CSV_PATH, mode="a", header=False, index=False)

    return get_stats(pg_id)


# ─────────────────────────────────────────────────────────────
# READ / AGGREGATE
# ─────────────────────────────────────────────────────────────

def _load() -> pd.DataFrame:
    """Load the ratings CSV, returning an empty DataFrame if missing."""
    _ensure_csv()
    df = pd.read_csv(CSV_PATH)
    if df.empty:
        return df
    df["pg_id"]  = df["pg_id"].astype(int)
    df["rating"] = df["rating"].astype(int)
    return df


def get_stats(pg_id: int) -> dict:
    """
    Compute average_rating and rating_count for a single PG.

    Returns default values if no ratings exist yet.
    """
    df = _load()
    subset = df[df["pg_id"] == int(pg_id)]

    if subset.empty:
        return {
            "average_rating": _DEFAULT_AVG,
            "rating_count":   _DEFAULT_COUNT,
        }

    return {
        "average_rating": round(float(subset["rating"].mean()), 2),
        "rating_count":   int(len(subset)),
    }


def get_all_stats() -> dict:
    """
    Return a dict of stats for ALL PGs that have at least one rating.

    Returns:
        { pg_id (int): {"average_rating": float, "rating_count": int} }
    """
    df = _load()
    if df.empty:
        return {}

    grouped = df.groupby("pg_id")["rating"].agg(["mean", "count"]).reset_index()
    grouped.columns = ["pg_id", "average_rating", "rating_count"]

    result = {}
    for _, row in grouped.iterrows():
        result[int(row["pg_id"])] = {
            "average_rating": round(float(row["average_rating"]), 2),
            "rating_count":   int(row["rating_count"]),
        }
    return result


# ─────────────────────────────────────────────────────────────
# TRUST / CONFIDENCE FORMULAS
# ─────────────────────────────────────────────────────────────

def compute_confidence(rating_count: int, average_rating: float) -> float:
    """
    confidence = consistency × (avg / 5)
    consistency = rating_count / (rating_count + 10)

    Approaches 1.0 as more ratings accumulate.
    """
    consistency = rating_count / (rating_count + 10)
    return round(consistency * (average_rating / 5.0), 4)


def compute_trust(rating_count: int, average_rating: float) -> float:
    """
    trust = log(1 + rating_count) × (avg / 5)

    Grows logarithmically with more ratings.
    Normalised so 100 ratings ≈ max ~0.921.
    """
    return round(math.log1p(rating_count) * (average_rating / 5.0), 4)
