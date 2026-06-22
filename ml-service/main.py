from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Dict, Any, Optional

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.data_loader import load_raw_data
from src.preprocessor import preprocess, normalize_user_rent, normalize_user_meals
from src.recommender import recommend
from src.sentiment_analyzer import analyze, sentiment_label, star_equivalent

app = FastAPI(title="PG Recommendation ML Service")

# Load and preprocess data at startup
try:
    print("Loading data...")
    df_raw = load_raw_data()
    df, _ = preprocess(df_raw)
    print("Data loaded successfully.")
except Exception as e:
    print(f"Error loading data: {e}")
    df = None

class RecommendRequest(BaseModel):
    budget: float
    location: str
    meals: int
    gender: int
    sharing: str
    wifi: int
    ac: int
    laundry: int
    food: int
    db_stats: Optional[Dict[str, Any]] = None

class SentimentRequest(BaseModel):
    text: str

@app.post("/recommend")
def get_recommendations(req: RecommendRequest):
    if df is None:
        raise HTTPException(status_code=500, detail="Data not loaded")
    
    user_normalized = {
        "Meals_Per_Day": normalize_user_meals(req.meals),
    }
    if req.wifi: user_normalized["WiFi"] = 1
    if req.ac: user_normalized["AC"] = 1
    if req.laundry: user_normalized["Laundry"] = 1
    if req.food: user_normalized["Weekend_Food"] = 1

    try:
        results_df = recommend(
            df=df,
            user_input=user_normalized,
            user_location=req.location.strip().lower(),
            budget=req.budget,
            gender=req.gender,
            sharing=req.sharing,
            db_stats=req.db_stats
        )
        
        if isinstance(results_df, str):
            # No results or error message
            return {"status": "error", "message": results_df}
            
        results = results_df.to_dict(orient="records")
        return {"status": "success", "data": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/analyze-sentiment")
def analyze_sentiment(req: SentimentRequest):
    try:
        score = analyze(req.text)
        return {
            "status": "success",
            "sentiment_score": score,
            "sentiment_label": sentiment_label(score),
            "star_equivalent": star_equivalent(score)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
