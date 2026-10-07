"""
src/whatif.py
───────────────
"What if…" counterfactual engine for explainability.

Given the preferences a user just searched with, this tries a handful of
small, realistic changes — raise the budget a bit, relax the room-sharing
type, drop one amenity requirement, search city-wide instead of one
neighbourhood — and reports which of those changes would *actually* change
the outcome.

Nothing here is templated or guessed from a rule of thumb: every suggestion
is produced by re-running the real recommendation pipeline
(src.recommender.recommend) with one preference changed, then diffing the
result against the baseline search the user actually ran. If a change
wouldn't matter, no suggestion is generated for it.

Two kinds of levers:
  - "Unlocking" levers (budget, sharing) are enforced in hard_filter(), so
    relaxing them can let in PGs that were invisible before. Impact is
    measured as the growth in the hard-filtered candidate pool.
  - "Re-ranking" levers (location, amenities) only affect scoring, not the
    hard filter — relaxing them can surface a different, better-scoring PG
    as the top pick even though it was already a candidate. Impact is
    measured as a jump in the top pick's match_rating.
"""

import pandas as pd

from src.preprocessor import build_user_normalized
from src.recommender import recommend, hard_filter

# Budget increments (₹) tried, smallest first — we report the smallest one
# that actually changes the candidate pool, not the biggest jump available.
BUDGET_STEPS = [1000, 2500, 4000, 6000, 8000]

AMENITY_LABELS = {
    "wifi": "WiFi",
    "ac": "AC",
    "laundry": "Laundry",
    "food": "Weekend food",
}

MAX_SUGGESTIONS = 3


# ─────────────────────────────────────────────────────────────
# SHARED HELPERS
# ─────────────────────────────────────────────────────────────

def _run(df: pd.DataFrame, user_raw: dict, db_stats, review_stats, top_n: int = 5):
    """
    Run the real pipeline for a (possibly modified) preference dict.
    Returns the ranked results DataFrame, or None if nothing cleared it
    (no example to show, so the lever isn't worth suggesting).
    """
    user_normalized = build_user_normalized(user_raw)
    result = recommend(
        df,
        user_normalized,
        user_raw.get("location", "").strip().lower(),
        float(user_raw.get("budget", 15000)),
        int(user_raw.get("gender", 2)),
        sharing=user_raw.get("sharing", "Any"),
        top_n=top_n,
        db_stats=db_stats,
        review_stats=review_stats,
    )
    if isinstance(result, str) or result.empty:
        return None
    return result


def _example(row: pd.Series) -> dict:
    """Plain-Python summary of one result row, safe to drop straight into JSON."""
    return {
        "PG_ID": int(row["PG_ID"]),
        "Location": str(row["Location"]).title(),
        "Rent": int(row["Original_Rent"]),
        "Sharing": str(row["Sharing"]),
        "WiFi": bool(row.get("WiFi")),
        "AC": bool(row.get("AC")),
        "Laundry": bool(row.get("Laundry")),
        "Weekend_Food": bool(row.get("Weekend_Food")),
        "match_rating": float(row.get("match_rating", 0)),
    }


def _fmt_inr(value) -> str:
    return f"₹{int(round(value)):,}"


# ─────────────────────────────────────────────────────────────
# LEVERS
# ─────────────────────────────────────────────────────────────

def _best_newly_unlocked(df, modified, baseline_ids, db_stats, review_stats):
    """
    Of the PGs that only become reachable under `modified` preferences (not
    already visible to the baseline search), find the single best one.

    Scores ONLY that newly-unlocked pool against the user's preferences,
    rather than ranking it against the full dataset and hoping one surfaces
    in a top-N cut — otherwise a genuinely great newly-unlocked PG could be
    buried under old, already-visible PGs that score even higher, making the
    "e.g." example an also-ran instead of the best thing actually gained.

    Returns (best_row_or_None, total_candidate_count_under_modified_filter).
    """
    modified_ids = set(hard_filter(
        df,
        float(modified.get("budget", 15000)),
        int(modified.get("gender", 2)),
        modified.get("sharing", "Any"),
    )["PG_ID"])
    new_only_ids = modified_ids - baseline_ids
    if not new_only_ids:
        return None, len(modified_ids)

    unlocked_pool = df[df["PG_ID"].isin(new_only_ids)]
    result = _run(unlocked_pool, modified, db_stats, review_stats, top_n=1)
    if result is None:
        return None, len(modified_ids)
    return result.iloc[0], len(modified_ids)


def _budget_lever(df, user_raw, baseline_ids, db_stats, review_stats):
    """Would a slightly higher budget unlock more PGs?"""
    budget = float(user_raw.get("budget", 15000))
    gender = int(user_raw.get("gender", 2))
    sharing = user_raw.get("sharing", "Any")
    baseline_count = len(baseline_ids)

    for step in BUDGET_STEPS:
        new_budget = budget + step
        modified = {**user_raw, "budget": new_budget}
        top, new_count = _best_newly_unlocked(df, modified, baseline_ids, db_stats, review_stats)
        if new_count <= baseline_count or top is None:
            continue

        gained = new_count - baseline_count
        return {
            "lever": "budget",
            "headline": f"Raise your budget to {_fmt_inr(new_budget)}",
            "detail": (
                f"Unlocks {gained} more PG{'s' if gained != 1 else ''} that your current "
                f"budget rules out — e.g. PG {int(top['PG_ID'])} in {str(top['Location']).title()} "
                f"at {_fmt_inr(top['Original_Rent'])}, rated {top.get('match_rating', 0)}/5."
            ),
            "change": {"budget": new_budget},
            "unlocked_count": gained,
            "example": _example(top),
        }
    return None


def _sharing_lever(df, user_raw, baseline_ids, db_stats, review_stats):
    """Would dropping a specific sharing requirement unlock more PGs?"""
    sharing = user_raw.get("sharing", "Any")
    if sharing == "Any":
        return None

    baseline_count = len(baseline_ids)

    modified = {**user_raw, "sharing": "Any"}
    top, new_count = _best_newly_unlocked(df, modified, baseline_ids, db_stats, review_stats)
    if new_count <= baseline_count or top is None:
        return None

    gained = new_count - baseline_count
    return {
        "lever": "sharing",
        "headline": "Open up to any room-sharing type",
        "detail": (
            f"Dropping the '{sharing}' requirement unlocks {gained} more "
            f"PG{'s' if gained != 1 else ''} — e.g. PG {int(top['PG_ID'])} "
            f"in {str(top['Location']).title()} at {_fmt_inr(top['Original_Rent'])}, "
            f"rated {top.get('match_rating', 0)}/5."
        ),
        "change": {"sharing": "Any"},
        "unlocked_count": gained,
        "example": _example(top),
    }


def _location_lever(df, user_raw, baseline_rating, db_stats, review_stats):
    """
    Would searching city-wide (instead of one neighbourhood) surface a
    better-scoring PG? Location is a scoring bonus, not a hard filter, so
    this never changes the candidate count — only who comes out on top.
    """
    location = user_raw.get("location", "").strip()
    if not location:
        return None

    modified = {**user_raw, "location": ""}
    result = _run(df, modified, db_stats, review_stats)
    if result is None:
        return None

    top = result.iloc[0]
    top_rating = float(top.get("match_rating", 0))
    if top_rating <= baseline_rating:
        return None

    return {
        "lever": "location",
        "headline": f"Search city-wide instead of just {location.title()}",
        "detail": (
            f"PG {int(top['PG_ID'])} in {str(top['Location']).title()} "
            f"({_fmt_inr(top['Original_Rent'])}, rated {top_rating}/5) scores higher "
            f"than anything found in {location.title()} alone."
        ),
        "change": {"location": ""},
        "unlocked_count": 0,
        "example": _example(top),
    }


def _amenity_lever(df, user_raw, baseline_id, db_stats, review_stats):
    """
    For each amenity the user required, would dropping it change the
    top pick? Only the single best such swap is returned.
    """
    best = None
    for key, label in AMENITY_LABELS.items():
        if not user_raw.get(key):
            continue

        modified = {**user_raw, key: 0}
        result = _run(df, modified, db_stats, review_stats)
        if result is None:
            continue

        top = result.iloc[0]
        if int(top["PG_ID"]) == baseline_id:
            continue

        candidate = {
            "lever": "amenity",
            "headline": f"Drop the '{label}' requirement",
            "detail": (
                f"PG {int(top['PG_ID'])} in {str(top['Location']).title()} at "
                f"{_fmt_inr(top['Original_Rent'])} (rated {top.get('match_rating', 0)}/5) "
                f"would become your top pick."
            ),
            "change": {key: 0},
            "unlocked_count": 0,
            "example": _example(top),
        }
        if best is None or candidate["example"]["match_rating"] > best["example"]["match_rating"]:
            best = candidate
    return best


# ─────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────

def generate_whatifs(
    df: pd.DataFrame,
    user_raw: dict,
    baseline_result,
    db_stats: dict = None,
    review_stats: dict = None,
    max_suggestions: int = MAX_SUGGESTIONS,
) -> list:
    """
    Build up to `max_suggestions` counterfactual "what if" cards for this
    search, highest-impact first.

    Args:
        df:              Full preprocessed PG dataset (module-level df).
        user_raw:        Raw preference dict exactly as received from the
                          frontend (budget, location, gender, sharing, meals,
                          wifi, ac, laundry, food).
        baseline_result: Whatever recommend() returned for this exact search
                          — a DataFrame, or an error string if nothing matched.
        db_stats, review_stats: Same aggregates passed to the real
                          recommend() call, so what-if runs see identical
                          trust/sentiment signals (no drift from the live search).

    Returns:
        List of suggestion dicts, each JSON-serializable as-is.
    """
    gender = int(user_raw.get("gender", 2))
    budget = float(user_raw.get("budget", 15000))
    sharing = user_raw.get("sharing", "Any")
    baseline_ids = set(hard_filter(df, budget, gender, sharing)["PG_ID"])

    baseline_top = None
    if isinstance(baseline_result, pd.DataFrame) and not baseline_result.empty:
        baseline_top = baseline_result.iloc[0]

    baseline_rating = float(baseline_top.get("match_rating", 0)) if baseline_top is not None else 0.0
    baseline_id = int(baseline_top["PG_ID"]) if baseline_top is not None else None

    candidates = [
        _budget_lever(df, user_raw, baseline_ids, db_stats, review_stats),
        _sharing_lever(df, user_raw, baseline_ids, db_stats, review_stats),
        _location_lever(df, user_raw, baseline_rating, db_stats, review_stats),
        _amenity_lever(df, user_raw, baseline_id, db_stats, review_stats),
    ]
    candidates = [c for c in candidates if c]

    # "Unlocking" levers (more PGs become visible) are more useful than
    # levers that only re-rank an already-visible PG, so surface those first.
    candidates.sort(key=lambda c: c["unlocked_count"], reverse=True)

    return candidates[:max_suggestions]
