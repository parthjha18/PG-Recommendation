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