"""
src/sentiment_analyzer.py
─────────────────────────
Converts a free-text PG review into a numeric sentiment score [0.0, 1.0].

Uses a curated lexicon of PG-relevant positive and negative words plus
simple intensity modifiers (very, not, etc.).  No external ML libraries
are needed — pure Python.

Scoring formula
───────────────
  raw  = Σ word_score  (positive words +1, negative words -1, scaled by modifiers)
  score = clip( (raw + max_possible) / (2 × max_possible), 0, 1 )

  This gives:
    all positive → ~1.0
    all negative → ~0.0
    mixed / neutral → ~0.5

Public API
──────────
  analyze(text: str) -> float          0.0–1.0 sentiment score
  sentiment_label(score: float) -> str "Poor" / "Average" / "Good" / "Excellent"
  star_equivalent(score: float) -> float  maps 0–1 → 1.0–5.0 star range
"""

import re
from typing import List, Tuple

# ── Lexicon ────────────────────────────────────────────────────────────────
# Each entry is (word/phrase, base_score)
# Positive → +1.0, Strong positive → +1.5, Mild positive → +0.5
# Negative → -1.0, Strong negative → -1.5, Mild negative → -0.5

_POSITIVE_WORDS: List[Tuple[str, float]] = [
    # Overall sentiment
    ("excellent",       1.5), ("outstanding",  1.5), ("fantastic",   1.5),
    ("amazing",         1.5), ("superb",       1.5), ("wonderful",   1.5),
    ("great",           1.0), ("good",         1.0), ("nice",        1.0),
    ("love",            1.0), ("loved",        1.0), ("perfect",     1.5),
    ("awesome",         1.5), ("brilliant",    1.5), ("best",        1.5),
    ("impressive",      1.0), ("satisfied",    1.0), ("happy",       1.0),
    ("pleased",         1.0), ("recommend",    1.0), ("recommended", 1.0),
    ("highly recommend",1.5), ("worth",        0.5), ("worth it",    1.0),

    # Food
    ("good food",       1.5), ("tasty",        1.0), ("delicious",   1.5),
    ("yummy",           1.0), ("decent food",  0.5), ("fresh food",  1.0),
    ("healthy food",    1.0), ("quality food", 1.0), ("home food",   1.0),

    # Cleanliness
    ("clean",           1.0), ("hygienic",     1.0), ("neat",        1.0),
    ("spotless",        1.5), ("well maintained", 1.5),

    # Location / accessibility
    ("convenient",      1.0), ("accessible",   1.0), ("good location", 1.5),
    ("nearby",          0.5), ("close to",     0.5), ("well connected", 1.0),

    # Facilities / amenities
    ("good wifi",       1.0), ("fast wifi",    1.5), ("stable wifi", 1.0),
    ("good ac",         1.0), ("good water",   1.0), ("hot water",   0.5),
    ("good parking",    0.5), ("power backup", 0.5), ("good gym",    0.5),
    ("good security",   1.0), ("24/7 security",1.0), ("cctv",        0.5),
    ("safe",            1.0), ("secure",       1.0),

    # Staff / management
    ("friendly staff",  1.5), ("helpful staff", 1.5), ("cooperative", 1.0),
    ("responsive",      1.0), ("attentive",    1.0), ("professional", 1.0),
    ("caring",          0.5), ("nice owner",   1.0), ("helpful",     1.0),
    ("good management", 1.5),

    # Value
    ("affordable",      1.0), ("reasonable",   1.0), ("value for money", 1.5),
    ("budget friendly", 1.0), ("cheap",        0.5), ("economical",  1.0),

    # General positive adjectives
    ("comfortable",     1.0), ("spacious",     1.0), ("well furnished", 1.0),
    ("good ambience",   1.0), ("quiet",        0.5), ("peaceful",    1.0),
    ("decent",          0.5),

    # Functioning / experience verbs (important for negation: "doesn't work", "didn't like")
    ("like",            0.8), ("enjoy",        1.0), ("enjoyed",     1.0),
    ("work",            0.7), ("works",        0.7), ("working",     0.7),
    ("smooth",          0.5), ("fast",         0.5), ("quick",       0.5),
]

_NEGATIVE_WORDS: List[Tuple[str, float]] = [
    # Overall sentiment
    ("terrible",        -1.5), ("horrible",    -1.5), ("awful",      -1.5),
    ("worst",           -1.5), ("bad",         -1.0), ("poor",       -1.0),
    ("disappointed",    -1.0), ("disappointing",-1.0), ("waste",     -1.0),
    ("waste of money",  -1.5), ("not worth",   -1.5), ("avoid",      -1.5),
    ("stay away",       -1.5), ("don't go",    -1.5), ("regret",     -1.0),
    ("pathetic",        -1.5), ("disgusting",  -1.5), ("hate",       -1.5),
    ("hated",           -1.5), ("worst ever",  -1.5),

    # Food
    ("bad food",        -1.5), ("stale food",  -1.5), ("unhealthy food", -1.0),
    ("no food",         -1.0), ("poor food",   -1.5), ("tasteless",  -1.0),
    ("food issues",     -1.0),

    # Cleanliness
    ("dirty",           -1.5), ("unhygienic",  -1.5), ("unclean",    -1.5),
    ("messy",           -1.0), ("smelly",      -1.5), ("cockroaches", -1.5),
    ("rats",            -1.5), ("pests",       -1.5), ("filthy",     -1.5),
    ("not clean",       -1.5),

    # Location / accessibility
    ("far from",        -0.5), ("too far",     -1.0), ("bad location", -1.5),
    ("remote",          -0.5),

    # Facilities / amenities
    ("no wifi",         -1.5), ("slow wifi",   -1.0), ("bad wifi",   -1.5),
    ("wifi issues",     -1.0), ("no ac",       -1.0), ("bad ac",     -1.0),
    ("no hot water",    -1.0), ("no water",    -1.5), ("water issues", -1.0),
    ("no power",        -1.0), ("power cuts",  -1.0), ("no backup",  -0.5),
    ("unsafe",          -1.5), ("no security", -1.5), ("no cctv",    -1.0),

    # Staff / management
    ("rude staff",      -1.5), ("unhelpful",   -1.0), ("arrogant",   -1.5),
    ("unresponsive",    -1.0), ("careless",    -1.0), ("bad management", -1.5),
    ("cheating",        -1.5), ("scam",        -1.5), ("fraud",      -1.5),
    ("rude owner",      -1.5), ("bad owner",   -1.5),

    # Value
    ("overpriced",      -1.5), ("expensive",   -1.0), ("not worth",  -1.5),

    # General negative adjectives
    ("small room",      -0.5), ("cramped",     -1.0), ("noisy",      -1.0),
    ("loud",            -0.5), ("run down",    -1.0), ("old",        -0.5),
    ("outdated",        -0.5), ("broken",      -1.0), ("issues",     -0.5),
    ("problems",        -0.5), ("complaints",  -0.5),
]

# ── Intensity modifiers ─────────────────────────────────────────────────────
# These multiply the score of the NEXT matched word
_AMPLIFIERS = {"very", "really", "extremely", "super", "absolutely", "highly",
               "totally", "completely", "definitely", "so", "quite"}
_DIMINISHERS = {"somewhat", "little", "bit", "slightly", "kind of", "sort of",
                "barely", "almost", "fairly"}
_NEGATORS    = {"not", "no", "never", "neither", "hardly", "barely", "doesn't",
                "didn't", "don't", "isn't", "wasn't", "aren't", "weren't",
                "won't", "can't", "cannot"}

_AMPLIFIER_MUL  = 1.4
_DIMINISHER_MUL = 0.6
_NEGATOR_MUL    = -1.0   # flips sign

# ── Helpers ─────────────────────────────────────────────────────────────────

def _preprocess(text: str) -> str:
    """Lower-case and lightly clean the text."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s'/]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _build_combined_lexicon():
    """Merge positive + negative lists into a single sorted list (longest first)."""
    combined = _POSITIVE_WORDS + _NEGATIVE_WORDS
    # Sort by phrase length descending so multi-word phrases match before single words
    return sorted(combined, key=lambda x: len(x[0].split()), reverse=True)


_LEXICON = _build_combined_lexicon()


def _find_matches(text: str):
    """
    Scan text for lexicon matches and return a list of (position, score) tuples.
    Multi-word phrases are matched first.
    """
    results = []
    used_positions = set()

    for phrase, score in _LEXICON:
        words = phrase.split()
        n = len(words)
        text_words = text.split()
        for i in range(len(text_words) - n + 1):
            if i in used_positions:
                continue
            if text_words[i:i+n] == words:
                results.append((i, score, n))
                for j in range(i, i + n):
                    used_positions.add(j)
    return results


def analyze(text: str) -> float:
    """
    Convert a free-text review into a sentiment score.

    Args:
        text: Raw review string (any language fragment, but primarily English).

    Returns:
        float in [0.0, 1.0] — higher is more positive.
        Returns 0.5 (neutral) for empty or uninformative text.
    """
    if not text or not text.strip():
        return 0.5

    cleaned = _preprocess(text)
    words   = cleaned.split()

    if not words:
        return 0.5

    raw_score   = 0.0
    word_count  = len(words)
    word_index  = 0
    modifier    = 1.0

    # Walk word by word, detect modifiers, then apply to next scored word
    remaining_modifier = 1.0

    # Build position → match map for fast lookup
    matches = _find_matches(cleaned)   # list of (start_idx, score, phrase_len)
    match_map = {}
    for (pos, score, n) in matches:
        match_map[pos] = (score, n)

    i = 0
    mod_decay = 0   # counts non-sentiment words seen since last modifier was set
    MAX_DECAY = 3   # modifier expires after this many consecutive non-sentiment words

    while i < word_count:
        word = words[i]

        # Check for negator
        if word in _NEGATORS:
            remaining_modifier *= _NEGATOR_MUL
            mod_decay = 0
            i += 1
            continue
        # Check for amplifier
        if word in _AMPLIFIERS:
            remaining_modifier *= _AMPLIFIER_MUL
            mod_decay = 0
            i += 1
            continue
        # Check for diminisher
        if word in _DIMINISHERS:
            remaining_modifier *= _DIMINISHER_MUL
            mod_decay = 0
            i += 1
            continue

        if i in match_map:
            score, n = match_map[i]
            raw_score += score * remaining_modifier
            remaining_modifier = 1.0   # reset after applying
            mod_decay = 0
            i += n
        else:
            # Non-sentiment filler word — let modifier persist but count toward decay
            if remaining_modifier != 1.0:
                mod_decay += 1
                if mod_decay >= MAX_DECAY:
                    remaining_modifier = 1.0   # modifier expired
                    mod_decay = 0
            i += 1

    # Normalise: typical review has 3-15 words → max possible raw ≈ 15 × 1.5 × 1.4 ≈ 31
    # We use a gentler normalisation: clip to [-8, +8] then map to [0, 1]
    CLIP = 8.0
    raw_score = max(-CLIP, min(CLIP, raw_score))
    score = (raw_score + CLIP) / (2.0 * CLIP)

    return round(score, 4)


def sentiment_label(score: float) -> str:
    """
    Map a [0,1] sentiment score to a human-readable label.

    0.00–0.30 → "Poor"
    0.30–0.50 → "Average"
    0.50–0.70 → "Good"
    0.70–1.00 → "Excellent"
    """
    if score >= 0.70:
        return "Excellent"
    if score >= 0.50:
        return "Good"
    if score >= 0.30:
        return "Average"
    return "Poor"


def star_equivalent(score: float) -> float:
    """
    Map sentiment score [0, 1] to a star-equivalent [1.0, 5.0].
    This is used to blend text sentiment into the rating pipeline.
    """
    return round(1.0 + score * 4.0, 2)
