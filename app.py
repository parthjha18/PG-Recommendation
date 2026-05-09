from flask import Flask, render_template, request, jsonify
from src.data_loader import load_raw_data
from src.preprocessor import preprocess, normalize_user_rent, normalize_user_meals
from src.recommender import recommend
from src.ratings_store import (
    add_rating, get_stats,
    add_review, get_review_stats, get_all_review_stats,
)

app = Flask(__name__)

# Load and preprocess once at startup
df = load_raw_data()
df, _ = preprocess(df)

# ─── Custom Jinja2 filter: Indian number formatting ───────────
def format_inr(value):
    """Format a number as Indian-style: 15,000 / 1,50,000"""
    try:
        value = int(value)
        s = str(value)
        if len(s) <= 3:
            return s
        # Last 3 digits, then groups of 2
        last3 = s[-3:]
        rest = s[:-3]
        groups = []
        while len(rest) > 2:
            groups.append(rest[-2:])
            rest = rest[:-2]
        if rest:
            groups.append(rest)
        groups.reverse()
        return ",".join(groups) + "," + last3
    except (ValueError, TypeError):
        return str(value)

app.jinja_env.filters["format_inr"] = format_inr


# ─── Main route ───────────────────────────────────────────────
@app.route("/", methods=["GET", "POST"])
def index():
    results = None
    user_display = None
    error_message = None
    # pre-load all review stats so the template can show review counts without extra queries
    all_review_stats = get_all_review_stats()

    if request.method == "POST":
        # Inputs
        budget   = float(request.form.get("budget", 15000))
        location = request.form.get("location", "").strip().lower()
        meals    = int(request.form.get("meals", 2))
        gender   = int(request.form.get("gender", 2))
        sharing  = request.form.get("sharing", "Any")
        wifi     = 1 if request.form.get("wifi") else 0
        ac       = 1 if request.form.get("ac") else 0
        laundry  = 1 if request.form.get("laundry") else 0
        food     = 1 if request.form.get("food") else 0

        user_raw = {
            "budget":   budget,
            "location": location,
            "sharing":  sharing,
            "wifi":     wifi,
            "ac":       ac,
            "laundry":  laundry,
            "food":     food,
            "meals":    meals,
            "gender":   gender,
        }

        user_normalized = {
            "Meals_Per_Day": normalize_user_meals(meals),
        }
        if wifi: user_normalized["WiFi"] = 1
        if ac: user_normalized["AC"] = 1
        if laundry: user_normalized["Laundry"] = 1
        if food: user_normalized["Weekend_Food"] = 1

        results_df = recommend(df, user_normalized, location, budget, gender, sharing=sharing)
        
        if isinstance(results_df, str):
            error_message = results_df
            results = None
        else:
            results = results_df.to_dict(orient="records")
            # Attach text review data to each result card
            for pg in results:
                pg_id = int(pg.get("PG_ID", 0))
                rs = get_review_stats(pg_id)
                pg["text_reviews"]      = rs["reviews"]
                pg["text_review_count"] = rs["review_count"]
                pg["avg_sentiment"]     = rs["avg_sentiment"]

                # ── Combined display rating ──────────────────────────────
                # Blends numeric star ratings (70%) with text-review
                # sentiment star-equivalent (30%) so that negative text
                # reviews visibly pull down the shown score.
                #
                # sentiment star-equivalent: avg_sentiment ∈ [0,1] → [1,5]
                # text_weight grows with review_count (0 reviews → 0 weight)
                star_avg  = float(pg.get("average_rating", 3.5))
                sent_avg  = float(rs["avg_sentiment"])        # 0.0–1.0
                sent_star = 1.0 + sent_avg * 4.0             # 1.0–5.0
                r_cnt     = int(rs["review_count"])
                # weight for text component: 0 reviews → 0%, grows toward 30%
                text_w = 0.30 * (r_cnt / (r_cnt + 3))        # 3 reviews → 15%, 10 → 23%
                star_w = 1.0 - text_w
                pg["combined_display_rating"] = round(star_w * star_avg + text_w * sent_star, 1)
                pg["has_text_influence"]      = r_cnt > 0
            
        user_display = user_raw

    return render_template(
        "index.html",
        results=results,
        user=user_display,
        error_message=error_message,
        all_review_stats=all_review_stats,
    )


# ─── Rate-PG API ─────────────────────────────────────────
@app.route("/rate-pg", methods=["POST"])
def rate_pg():
    """
    POST /rate-pg
    Body (JSON): { "pg_id": 42, "rating": 4 }

    Appends the rating to data/ratings.csv and returns updated stats.
    """
    data = request.get_json(force=True, silent=True) or {}
    pg_id  = data.get("pg_id")
    rating = data.get("rating")

    if pg_id is None or rating is None:
        return jsonify({"error": "pg_id and rating are required"}), 400

    try:
        stats = add_rating(pg_id, rating)
        return jsonify({"success": True, "pg_id": pg_id, **stats}), 200
    except ValueError as e:
        return jsonify({"error": str(e)}), 422


# ─── Submit Text Review API ───────────────────────────────
@app.route("/submit-review", methods=["POST"])
def submit_review():
    """
    POST /submit-review
    Body (JSON): { "pg_id": 42, "review_text": "This PG is great, food is excellent!" }

    Analyzes sentiment and persists review to data/reviews.csv.
    Returns sentiment score, label, star equivalent, and updated averages.
    """
    data = request.get_json(force=True, silent=True) or {}
    pg_id       = data.get("pg_id")
    review_text = data.get("review_text", "").strip()

    if pg_id is None:
        return jsonify({"error": "pg_id is required"}), 400
    if not review_text:
        return jsonify({"error": "review_text cannot be empty"}), 400

    try:
        result = add_review(pg_id, review_text)
        return jsonify({"success": True, "pg_id": pg_id, **result}), 200
    except ValueError as e:
        return jsonify({"error": str(e)}), 422


# ─── Get Reviews API ─────────────────────────────────────
@app.route("/get-reviews/<int:pg_id>", methods=["GET"])
def get_reviews(pg_id):
    """
    GET /get-reviews/<pg_id>
    Returns all text reviews and sentiment stats for a PG.
    """
    stats = get_review_stats(pg_id)
    return jsonify({"success": True, "pg_id": pg_id, **stats}), 200


if __name__ == "__main__":
    app.run(debug=True, port=5001)
