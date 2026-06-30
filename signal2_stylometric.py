"""
Signal 2 — Stylometric Heuristics (pure Python, no external libraries)
Weight: 40% of final confidence score
Output: float 0.0 (AI-like uniformity) to 1.0 (human-like variability)

Three sub-metrics:
  1. Sentence length variance  — AI text has uniform sentence lengths; human text varies
  2. Type-token ratio (TTR)    — vocabulary diversity; very high TTR in short AI text,
                                 but human text shows natural repetition in longer passages
  3. Punctuation density       — humans use dashes, ellipses, exclamations, questions more
                                 than AI which defaults to periods and commas

Sub-metric weights: variance 50%, TTR 30%, punctuation 20%

Test independently:
    python signal2_stylometric.py
"""

import re
import math


# ---------------------------------------------------------------------------
# Sub-metric 1: Sentence length variance
# ---------------------------------------------------------------------------

def _sentence_lengths(text: str) -> list[int]:
    """Split text into sentences and return word counts per sentence."""
    # Split on . ! ? followed by whitespace or end-of-string
    sentences = re.split(r'[.!?]+[\s]+|[.!?]+$', text.strip())
    sentences = [s.strip() for s in sentences if s.strip()]
    return [len(s.split()) for s in sentences]


def _variance_score(text: str) -> float:
    """
    Returns 0.0–1.0. Higher = more variance = more human-like.
    Uses coefficient of variation (std/mean) so it's scale-independent.
    Capped at CV=1.5 (returns 1.0 above that).
    Returns 0.5 for texts too short to measure reliably (< 3 sentences).
    """
    lengths = _sentence_lengths(text)
    if len(lengths) < 3:
        return 0.5  # not enough data — neutral fallback

    mean = sum(lengths) / len(lengths)
    if mean == 0:
        return 0.5

    variance = sum((l - mean) ** 2 for l in lengths) / len(lengths)
    std = math.sqrt(variance)
    cv = std / mean  # coefficient of variation

    # AI text typically CV < 0.3; human text typically CV > 0.5
    # Map 0.0–1.5 range to 0.0–1.0
    score = min(cv / 1.5, 1.0)
    return round(score, 4)


# ---------------------------------------------------------------------------
# Sub-metric 2: Type-token ratio (vocabulary diversity)
# ---------------------------------------------------------------------------

def _ttr_score(text: str) -> float:
    """
    Returns 0.0–1.0. Calibrated so that mid-range TTR scores near 0.5.

    Raw TTR is high for short texts regardless of origin, so we use a
    corrected measure: if text < 100 words, apply a length penalty.

    AI text tends toward moderate-high TTR with very consistent vocabulary.
    Human text in longer passages shows natural repetition (lower TTR)
    but in casual short text shows very high TTR with colloquialisms.

    We score TTR neutrally at 0.5 for short texts (< 50 words).
    For longer texts: TTR < 0.4 → likely AI (repetitive filler),
                      TTR 0.4–0.7 → uncertain,
                      TTR > 0.7 → likely human (rich vocabulary or casual voice)
    """
    words = re.findall(r'\b[a-zA-Z]+\b', text.lower())
    if len(words) < 50:
        return 0.5  # too short to calibrate

    ttr = len(set(words)) / len(words)

    # Map to 0–1: TTR of 0.3 → 0.0, TTR of 0.8 → 1.0
    score = (ttr - 0.3) / (0.8 - 0.3)
    return round(max(0.0, min(1.0, score)), 4)


# ---------------------------------------------------------------------------
# Sub-metric 3: Punctuation density (non-standard punctuation)
# ---------------------------------------------------------------------------

def _punctuation_score(text: str) -> float:
    """
    Returns 0.0–1.0. Higher = more expressive punctuation = more human-like.

    Counts 'expressive' punctuation: -- — … ! ? () [] \" ' (curly or straight)
    AI text uses mostly . and , with occasional ? and very rare !
    Human text uses em-dashes, ellipses, exclamations, informal brackets.

    Score is (expressive_punct_count / total_chars) normalised.
    """
    if not text:
        return 0.5

    expressive = re.findall(r'[!?]|--|—|…|\.\.\.|[()\[\]]', text)
    density = len(expressive) / max(len(text), 1)

    # Typical AI: 0–0.005  Typical human casual: 0.01–0.05
    # Map 0–0.04 → 0–1
    score = min(density / 0.04, 1.0)
    return round(score, 4)


# ---------------------------------------------------------------------------
# Combined Signal 2 score
# ---------------------------------------------------------------------------

VARIANCE_WEIGHT    = 0.50
TTR_WEIGHT         = 0.30
PUNCTUATION_WEIGHT = 0.20


def compute_stylometric_score(text: str) -> float:
    """
    Combine three sub-metrics into a single 0.0–1.0 score.
    0.0 = AI-like (uniform, plain)
    1.0 = human-like (variable, expressive)

    Args:
        text: Raw content string.

    Returns:
        float in [0.0, 1.0]
    """
    v = _variance_score(text)
    t = _ttr_score(text)
    p = _punctuation_score(text)

    score = VARIANCE_WEIGHT * v + TTR_WEIGHT * t + PUNCTUATION_WEIGHT * p
    return round(score, 4)


# ---------------------------------------------------------------------------
# Standalone test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    test_cases = [
        ("clearly_ai", (
            "Artificial intelligence represents a transformative paradigm shift in modern society. "
            "It is important to note that while the benefits of AI are numerous, it is equally "
            "essential to consider the ethical implications. Furthermore, stakeholders across "
            "various sectors must collaborate to ensure responsible deployment."
        )),
        ("clearly_human", (
            "ok so i finally tried that new ramen place downtown and honestly? "
            "underwhelming. the broth was fine but they put WAY too much sodium in it and "
            "i was thirsty for like three hours after. my friend got the spicy version and "
            "said it was better. probably won't go back unless someone drags me there"
        )),
        ("borderline_formal_human", (
            "The relationship between monetary policy and asset price inflation has been "
            "extensively studied in the literature. Central banks face a fundamental tension "
            "between their mandate for price stability and the unintended consequences of "
            "prolonged low interest rates on equity and real estate valuations."
        )),
        ("borderline_edited_ai", (
            "I've been thinking a lot about remote work lately. There are genuine tradeoffs — "
            "flexibility and no commute on one side, isolation and blurred work-life boundaries "
            "on the other. Studies show productivity varies widely by individual and role type."
        )),
    ]

    print("Signal 2 — Stylometric Heuristics Test")
    print("=" * 50)
    for name, text in test_cases:
        v = _variance_score(text)
        t = _ttr_score(text)
        p = _punctuation_score(text)
        final = compute_stylometric_score(text)
        print(f"\n[{name}]")
        print(f"  variance_score  : {v:.3f}")
        print(f"  ttr_score       : {t:.3f}")
        print(f"  punct_score     : {p:.3f}")
        print(f"  SIGNAL 2 TOTAL  : {final:.3f}")
