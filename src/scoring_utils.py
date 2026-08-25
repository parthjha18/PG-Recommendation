"""
src/scoring_utils.py
────────────────────
Pure-math scoring helpers with no database dependency.
Used by recommender.py to compute confidence and trust scores
from aggregated stats that Express/Prisma passes in.
"""

import math

_DEFAULT_AVG   = 3.5
_DEFAULT_COUNT = 0


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
