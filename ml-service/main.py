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

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional

from src.data_loader import load_raw_data
from src.preprocessor import preprocess, build_user_normalized
from src.recommender import recommend
from src.explainer import add_explanations
from src.whatif import generate_whatifs
from src.commute import geocode_destination, apply_commute_ranking, COMMUTE_POOL_SIZE
from src.sentiment_analyzer import analyze as analyze_sentiment, sentiment_label
from config import DEFAULT_TOP_N

app = FastAPI(title="PG Recommendation ML Service")

# ── Load & preprocess dataset once at startup ──
df = None


@app.on_event("startup")
async def startup():
    global df
    raw = load_raw_data()
    df, _ = preprocess(raw)
    print(f"✅ ML Service: loaded {len(df)} preprocessed PG records")


# ── Request schemas ──

class RecommendRequest(BaseModel):
    user_preferences: dict
    db_stats: Optional[dict] = None


class AnalyzeSentimentRequest(BaseModel):
    review_text: str


# ── Routes ──

@app.post("/recommend")
async def recommend_endpoint(req: RecommendRequest):
    """Run the full recommendation pipeline with external db_stats."""
    user = req.user_preferences

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
            "destination": None, "commute_error": commute_error,
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
