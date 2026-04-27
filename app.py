from flask import Flask, render_template, request, jsonify
from src.data_loader import load_raw_data
from src.preprocessor import preprocess, normalize_user_rent, normalize_user_meals
from src.recommender import recommend
from src.ratings_store import add_rating, get_stats

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

    if request.method == "POST":
        # Inputs
        budget   = float(request.form.get("budget", 15000))
        location = request.form.get("location", "").strip().lower()
        meals    = int(request.form.get("meals", 2))
        gender   = int(request.form.get("gender", 2))
        wifi     = 1 if request.form.get("wifi") else 0
        ac       = 1 if request.form.get("ac") else 0
        laundry  = 1 if request.form.get("laundry") else 0
        food     = 1 if request.form.get("food") else 0

        user_raw = {
            "budget":   budget,
            "location": location,
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

        results_df = recommend(df, user_normalized, location, budget, gender)
        
        if isinstance(results_df, str):
            error_message = results_df
            results = None
        else:
            results = results_df.to_dict(orient="records")
            
        user_display = user_raw

    return render_template("index.html", results=results, user=user_display, error_message=error_message)


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


if __name__ == "__main__":
    app.run(debug=True)
