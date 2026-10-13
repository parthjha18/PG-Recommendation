"""
ml-service/main.py
──────────────────
FastAPI ML Microservice wrapping the existing src/ recommendation pipeline.

Endpoints:
  POST /recommend          — full recommendation pipeline
  POST /analyze-sentiment  — HuggingFace sentiment analysis
"""

import sys
import os
import time
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional

from src.data_loader import load_raw_data, load_real_data
from src.form_sync import get_source, is_live_source, sync_real_data
from src.preprocessor import preprocess, build_user_normalized
from src.recommender import recommend
from src.explainer import add_explanations
from src.whatif import generate_whatifs
from src.commute import geocode_destination, apply_commute_ranking, COMMUTE_POOL_SIZE
from src.sentiment_analyzer import analyze as analyze_sentiment, sentiment_label
from config import DEFAULT_TOP_N

app = FastAPI(title="PG Recommendation ML Service")

# ── Load & preprocess datasets once at startup ──
# "demo" = the 1000 generated PGs (Postgres). "real" = PGs collected through
# the Google Form (data/raw/real_pgs.csv); None until that file is imported.
datasets = {"demo": None, "real": None}


REFRESH_MIN_INTERVAL_SECONDS = 10      # don't let a double-click hammer Google / the geocoder
_refresh_lock = threading.Lock()
_last_refresh = {"at": 0.0}


def _load_real_into_memory():
    """(Re)load data/raw/real_pgs.csv into datasets['real']; None if absent/empty."""
    real_raw = load_real_data()
    if real_raw is not None and len(real_raw) > 0:
        datasets["real"], _ = preprocess(real_raw)
        print(f"✅ ML Service: loaded {len(datasets['real'])} preprocessed REAL PG rows")
    else:
        datasets["real"] = None
        print("ℹ️  ML Service: no real PG data imported yet (data/raw/real_pgs.csv)")


@app.on_event("startup")
async def startup():
    raw = load_raw_data()
    datasets["demo"], _ = preprocess(raw)
    print(f"✅ ML Service: loaded {len(datasets['demo'])} preprocessed demo PG records")

    # If a live responses link is configured, pull the latest before loading;
    # on any failure fall back to whatever real_pgs.csv was last written.
    source = get_source()
    if is_live_source(source):
        try:
            result = sync_real_data(source)
            print(f"✅ ML Service: synced {result['pgs']} real PG(s) from the live form responses")
        except Exception as exc:
            print(f"⚠️  ML Service: live sync failed ({exc}); using the last saved real data")

    try:
        _load_real_into_memory()
    except Exception as exc:  # a bad real-data file must not stop the demo from running
        print(f"⚠️  ML Service: could not load real PG data: {exc}")


def _pick_dataset(user: dict):
    """Which dataset this search runs on: 'demo' (default) or 'real'."""
    name = str(user.get("dataset") or "demo").lower()
    if name not in datasets:
        name = "demo"
    return name, datasets[name]


# ── Request schemas ──

class RecommendRequest(BaseModel):
    user_preferences: dict
    db_stats: Optional[dict] = None


class AnalyzeSentimentRequest(BaseModel):
    review_text: str


# ── Routes ──

def _datasets_info() -> dict:
    out = {}
    for name, data in datasets.items():
        if data is None:
            out[name] = {"loaded": False, "rows": 0, "pgs": 0}
        else:
            pgs = int(data["PG_Name"].nunique()) if "PG_Name" in data.columns else len(data)
            out[name] = {"loaded": True, "rows": len(data), "pgs": pgs}
    # Whether the Refresh button can do anything: only with a live link configured.
    out["real"]["sync_available"] = is_live_source(get_source())
    return out


@app.get("/datasets")
async def datasets_endpoint():
    """What's loaded, so the UI can show honest counts next to the toggle."""
    return _datasets_info()


@app.post("/datasets/refresh")
def refresh_real_data():
    """
    Pull the latest form responses, rebuild the real dataset and reload it
    in memory. (Plain `def`, so FastAPI runs it in a worker thread and the
    network calls don't block other searches.)
    """
    source = get_source()
    if not is_live_source(source):
        raise HTTPException(
            status_code=400,
            detail="No live responses link configured. Publish the response sheet as CSV and put "
                   "the link in data/form_responses_url.txt (see README).")
    if not _refresh_lock.acquire(blocking=False):
        raise HTTPException(status_code=429, detail="A refresh is already running.")
    try:
        wait = REFRESH_MIN_INTERVAL_SECONDS - (time.time() - _last_refresh["at"])
        if wait > 0:
            raise HTTPException(status_code=429, detail=f"Just refreshed - try again in {int(wait) + 1}s.")
        try:
            result = sync_real_data(source)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Couldn't refresh from the form responses: {exc}")
        _load_real_into_memory()
        _last_refresh["at"] = time.time()
        return {"sync": result, "datasets": _datasets_info()}
    finally:
        _refresh_lock.release()


@app.post("/recommend")
async def recommend_endpoint(req: RecommendRequest):
    """Run the full recommendation pipeline with external db_stats."""
    user = req.user_preferences

    dataset_name, df = _pick_dataset(user)
    if df is None:
        return {
            "error": "No real PG data has been imported yet. Import the form responses "
                     "(scripts/import_form_responses.py), restart the ML service, or switch to Demo data.",
            "results": [], "what_if": [], "destination": None, "commute_error": None,
            "dataset": dataset_name,
        }

    # Normalize user input
    user_normalized = build_user_normalized(user)

    # Parse db_stats
    db_stats_in = None
    review_stats_in = None
    if req.db_stats:
        db_stats_in = req.db_stats.get("ratings")
        review_stats_in = req.db_stats.get("reviews")

    # Commute-aware ranking is opt-in: only kicks in when the user names a
    # destination. Geocoding happens up front so we know whether to ask
    # recommend() for a wide pool (to re-rank by commute) or the normal
    # top-N (unchanged, existing behaviour).
    destination_raw = (user.get("destination") or "").strip()
    destination_geo = None
    commute_error = None
    pool_top_n = DEFAULT_TOP_N
    if destination_raw:
        destination_geo = geocode_destination(destination_raw)
        if destination_geo is None:
            commute_error = (
                f"Couldn't find \"{destination_raw}\" in Bangalore North — "
                "showing results without commute ranking."
            )
        else:
            pool_top_n = COMMUTE_POOL_SIZE

    result = recommend(
        df,
        user_normalized,
        user.get("location", "").strip().lower(),
        float(user.get("budget", 15000)),
        int(user.get("gender", 2)),
        top_n=pool_top_n,
        sharing=user.get("sharing", "Any"),
        db_stats=db_stats_in,
        review_stats=review_stats_in,
    )

    # "What if…" counterfactual suggestions — computed from the SAME baseline
    # result (before add_explanations/commute reshape it) so the comparisons
    # inside generate_whatifs are apples-to-apples with what the user just
    # searched. What-if stays scoped to preference trade-offs; it doesn't
    # know about commute, which is an independent ranking layer below.
    what_if = generate_whatifs(df, user, result, db_stats_in, review_stats_in)

    if isinstance(result, str):
        return {
            "error": result, "results": [], "what_if": what_if,
            "destination": None, "commute_error": commute_error, "dataset": dataset_name,
        }

    if destination_geo is not None:
        result = apply_commute_ranking(
            result, destination_geo["lat"], destination_geo["lon"], DEFAULT_TOP_N
        )

    # Attach explanations and badges
    result = add_explanations(result, user)

    records = result.to_dict(orient="records")
    # Convert numpy types to native Python for JSON serialization
    cleaned = _clean_records(records)

    destination_out = None
    if destination_geo is not None:
        destination_out = {
            "display_name": destination_geo["display_name"],
            "lat": destination_geo["lat"],
            "lon": destination_geo["lon"],
        }

    return {
        "results": cleaned, "error": None, "what_if": what_if,
        "destination": destination_out, "commute_error": commute_error,
        "dataset": dataset_name,
    }


@app.post("/analyze-sentiment")
async def analyze_sentiment_endpoint(req: AnalyzeSentimentRequest):
    """Analyze review text and return sentiment score."""
    score = analyze_sentiment(req.review_text)
    return {
        "sentiment_score": score,
        "sentiment_label": sentiment_label(score),
    }


# ── Helpers ──

def _clean_records(records: list) -> list:
    """Convert numpy types to native Python for JSON serialization."""
    import math
    cleaned = []
    for rec in records:
        clean = {}
        for k, v in rec.items():
            if isinstance(v, (float,)):
                if math.isnan(v) or math.isinf(v):
                    clean[k] = None
                else:
                    clean[k] = round(float(v), 4)
            elif isinstance(v, (int,)):
                clean[k] = int(v)
            elif isinstance(v, dict):
                clean[k] = v
            else:
                clean[k] = v
        cleaned.append(clean)
    return cleaned
