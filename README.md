# 🏠 PG Accommodation Recommendation System

## 📌 Introduction
Finding suitable PG accommodation is difficult due to scattered listings and lack of personalization.  
This project provides an intelligent recommendation system that suggests PGs based on user preferences.

---

## 🎯 Features
- ✔ Preference-based filtering (budget, gender, amenities)
- ✔ Weighted similarity scoring (Euclidean distance)
- ✔ Distance-based recommendation (proximity consideration)
- ✔ Fuzzy location matching (handles spelling variations)
- ✔ Explainable recommendations (Why this PG?)
- ✔ Badge system (Budget Pick, Premium, Best Value)
- ✔ Fallback system (no empty results)
- ✔ Export recommendations to CSV
- ✔ "What if…" counterfactual suggestions (see what preference change would actually improve your results)
- ✔ Real commute-time ranking to a destination you name (college, office)

---

## 🆕 Recent Additions

**What-if suggestions (explainability).** After every search, the system re-runs
the real recommendation pipeline with small preference changes — raise the
budget, drop a sharing restriction, search city-wide, drop one amenity — and
only shows the ones that would actually change the outcome (more PGs unlocked,
or a better PG becoming the top pick). Each suggestion has a one-click
"Try this →" that applies the change and re-searches instantly.
See [`src/whatif.py`](src/whatif.py).

**Real commute-time ranking.** Enter a destination (e.g. "MSRIT", "Manyata
Tech Park") and PGs are re-ranked by actual road driving time to it, not
straight-line distance — blended with the existing preference-match score
so a slightly-closer PG doesn't outrank a much better overall match.
Geocoding and routing use free OpenStreetMap services (Nominatim + OSRM),
with an automatic distance-based fallback if either is unreachable.
See [`src/commute.py`](src/commute.py).

**Real data alongside the demo data.** A Demo / Real toggle switches the whole
app between the 1000 generated PGs and PGs collected from real residents through
a Google Form ([`scripts/create_pg_form.gs`](scripts/create_pg_form.gs) builds the
form). The app pulls the latest responses straight from the sheet, so there is
no CSV to download and re-send each time a friend submits. One-time setup:

1. In the response sheet: **File → Share → Publish to web** → choose the
   *Form Responses* tab and **CSV** → Publish, and copy the link.
2. Save that link as the first line of `data/form_responses_url.txt`
   (git-ignored; or set the `FORM_RESPONSES_URL` env var).
3. Restart the ML service. It syncs on start-up.

After that, press **↻ Refresh** next to the Demo/Real toggle to pull new
responses without restarting (Google can take a few minutes to update a
published sheet). If the sheet can't be reached, the app keeps the last saved
real data. To import by hand instead: `python scripts/import_form_responses.py`
(uses the link above, or a manual export saved as `data/form_responses.csv`).

Each PG becomes one row per sharing type, with coordinates read from its Google
Maps link (cached, so a refresh only looks up new PGs). Real PGs get IDs from 10001 up, so ratings/reviews never clash with the
generated set. Tests: `python -m unittest discover -s tests -t .`

---

## 🗂 Dataset
- 1000 structured records
- Focused on **Bangalore North**
- Includes locations like Hebbal, Yelahanka, Kalyan Nagar, etc.
- Features:
  - Rent, amenities, availability
  - Latitude & Longitude
  - Distance from center
- Generated using realistic constraints and validated with housing datasets

---

## ⚙️ System Architecture
1. Data Loading & Validation
2. Preprocessing & Feature Engineering
3. Hard Filtering
4. Weighted Scoring
5. Ranking & Rating
6. Explanation Generation
7. Output Display

---

## 🧠 Algorithm
- Weighted Euclidean Distance:
  
  distance = √ Σ wᵢ (pgᵢ - userᵢ)²

- Distance-based scoring:
  
  Closer PG → lower penalty → higher rank

- Final Score:
  
  Final Score = Distance Score - Location Bonus

---

## ▶️ How to Run

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python main.py