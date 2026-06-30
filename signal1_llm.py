"""
Signal 1 — LLM Classification via Groq (llama-3.3-70b-versatile)
Weight: 60% of final confidence score
Output: float 0.0 (AI) to 1.0 (human)

Tests this module independently:
    python signal1_llm.py
"""

import os
import re
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

_client = None


def _get_client() -> Groq:
    global _client
    if _client is None:
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            raise EnvironmentError("GROQ_API_KEY is not set in environment or .env file.")
        _client = Groq(api_key=api_key)
    return _client


SYSTEM_PROMPT = """You are an expert in distinguishing human-written text from AI-generated text.

Your task: analyze the provided text and return a single confidence score from 0.0 to 1.0 representing how likely it is that a human wrote this content.

Scoring guide:
- 0.0 = certain AI-generated (uniform style, no personal voice, generic phrasing, polished to a fault)
- 0.5 = genuinely ambiguous (could plausibly be either)
- 1.0 = certain human-written (personal voice, idiosyncratic word choices, emotional register, natural inconsistencies)

Return ONLY a JSON object in this exact format — no explanation, no extra text:
{"human_probability": <float between 0.0 and 1.0>}"""


def classify_with_llm(text: str) -> float:
    """
    Call Groq to assess whether text is human or AI-generated.

    Args:
        text: The content to classify. Truncated to 3000 chars to stay within token limits.

    Returns:
        A float from 0.0 (AI) to 1.0 (human). Returns 0.5 on any error (safe fallback).
    """
    truncated = text[:3000]
    client = _get_client()

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Analyze this text:\n\n{truncated}"},
            ],
            temperature=0.1,
            max_tokens=64,
        )

        content = response.choices[0].message.content
        if content is None:
            return 0.5
        return _parse_score(content.strip())

    except Exception as exc:
        print(f"[signal1_llm] Groq call failed: {exc}")
        return 0.5


def _parse_score(raw: str) -> float:
    """
    Extract human_probability from the model's response.
    Tries JSON parse first, then regex fallback.
    """
    import json

    try:
        data = json.loads(raw)
        score = float(data["human_probability"])
        return max(0.0, min(1.0, score))
    except Exception:
        pass

    # Regex fallback: find any float in the response
    match = re.search(r"(\d+\.\d+|\d+)", raw)
    if match:
        score = float(match.group(1))
        # If the model returned a value like 85 instead of 0.85
        if score > 1.0:
            score = score / 100.0
        return max(0.0, min(1.0, score))

    print(f"[signal1_llm] Could not parse score from: {raw!r}")
    return 0.5


if __name__ == "__main__":
    test_cases = [
        (
            "human_anecdote",
            "I burned the grilled cheese again. Third time this week. "
            "My roommate didn't say anything but I saw him hide the good pan.",
        ),
        (
            "ai_sounding",
            "Artificial intelligence represents a transformative paradigm in modern technology. "
            "By leveraging advanced algorithms and machine learning techniques, organizations can "
            "unlock unprecedented levels of operational efficiency and strategic insight.",
        ),
        (
            "ambiguous",
            "The morning light filtered through the curtains. She made coffee and sat by the window, "
            "watching the street below as the city slowly woke up.",
        ),
    ]

    print("Signal 1 — LLM Classification Test\n" + "=" * 40)
    for name, text in test_cases:
        score = classify_with_llm(text)
        print(f"\n[{name}]\nText: {text[:80]}...\nScore: {score:.3f}")
