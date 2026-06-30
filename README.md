# Provenance Guard

A backend classification system that detects AI-generated content, scores confidence, surfaces transparency labels, and handles creator appeals. Built for any creative-sharing platform that needs to give audiences honest context about whether content was written by a human.

---

## Architecture Overview

A submitted piece of text travels through the following path:

1. `POST /submit` receives the JSON body and validates it (non-empty, minimum 20 chars).
2. The raw text is passed **simultaneously** to two independent detection signals.
3. **Signal 1** (Groq LLM) returns a float 0.0–1.0 representing how human-like the text reads semantically.
4. **Signal 2** (stylometric heuristics, pure Python) returns a float 0.0–1.0 representing how human-like the text is structurally — based on sentence length variance, vocabulary diversity, and punctuation density.
5. A **confidence scorer** combines the two scores: `confidence = 0.60 * s1 + 0.40 * s2`.
6. The confidence score is mapped to one of three **transparency label** variants.
7. The full decision — both signal scores, combined confidence, label, and status — is written to the **SQLite audit log**.
8. The structured JSON response is returned to the caller.

For appeals: `POST /appeal/<submission_id>` retrieves the original record, records the creator's reasoning, updates the submission status to `under_review`, and writes an appeal entry to the audit log. No automated re-classification occurs — the appeal enters a human review queue visible at `GET /appeals`.

```
POST /submit
     |
     v
[ Input Validation ]
     |  raw text
  ---|---
  |       |
  v       v
[Signal 1:      ]   [Signal 2:             ]
[LLM Classify   ]   [Stylometric Heuristics]
[Groq 0.0-1.0   ]   [Pure Python 0.0-1.0   ]
  |       |
  s1      s2
  ---|---
     |
     v
[ Confidence Scorer ]
[ 0.60*s1 + 0.40*s2 ]
     |
     v
[ Label Generator ]
[ AI / Unclear / Human ]
     |
     v
[ Audit Logger ] --> SQLite
     |
     v
[ JSON Response ]
```

See `planning.md` for the full narrative and appeal flow diagram.

---

## Detection Signals

### Signal 1 — LLM Classification (Groq, llama-3.3-70b-versatile), weight 60%

**What it measures:** Holistic semantic and stylistic coherence. The model evaluates whether the text reads as human-authored based on naturalness of expression, idiosyncratic word choices, emotional register, tonal inconsistency, and narrative voice.

**Why I chose it:** No surface-level heuristic can capture what "sounds like a person wrote it." The LLM has been trained on the full spectrum of human and AI writing and can assess semantic register in a way that rule-based signals cannot. It's the primary signal because it captures the most information.

**Why it differs between human and AI text:** Human writing carries personal quirks, unexpected metaphors, emotional shifts, and authentic imprecision. AI writing tends toward polished, consistent, slightly generic prose — coherent but lacking idiosyncrasy.

**What it misses:** Competent, clean human writing — a well-edited essay, a professional email — can read as AI to the LLM. Writers who deliberately adopt a neutral voice will score lower than their authorship warrants. The model's own internal biases about "what sounds human" may not generalize across demographics or writing cultures.

---

### Signal 2 — Stylometric Heuristics (pure Python), weight 40%

**What it measures:** Three statistical properties of surface text, combined into one score:

- **Sentence length variance (50% of Signal 2):** AI text clusters around uniform sentence lengths. Human text is noisier — a long complex sentence followed by a short punch. Measured as coefficient of variation (std/mean) of per-sentence word counts.
- **Type-token ratio / TTR (30%):** Vocabulary diversity. Human casual writing shows colloquial repetition; human formal writing shows rich diversity. AI writing occupies a consistent mid-range. Calibrated for texts over 50 words to avoid short-text inflation.
- **Punctuation density (20%):** Counts expressive punctuation — `!`, `?`, `--`, `—`, `…`, `()` — as a ratio of total characters. AI defaults to periods and commas; human writers are more expressive and irregular.

**Why I chose it:** It's genuinely independent from Signal 1. The LLM evaluates semantics; the heuristics evaluate measurable surface structure. Two signals that capture different properties make the combined score more informative than either alone.

**What it misses:** Short texts (under 3 sentences) produce unreliable variance estimates and fall back to a neutral 0.5. Deliberately minimalist writing — haiku, short poems, sparse prose — will score low on variance and punctuation regardless of human origin. A verbose AI response with intentional variety can score deceptively high.

---

## Confidence Scoring

Scores run from `0.0` (certain AI) to `1.0` (certain human). The combination formula weights the LLM signal higher because it captures semantic nuance that heuristics cannot:

```
confidence = 0.60 * signal_1 + 0.40 * signal_2
```

**Thresholds:**

| Score Range | Result | Label Variant |
|---|---|---|
| 0.00 – 0.35 | `ai` | Likely AI-Generated |
| 0.36 – 0.79 | `uncertain` | Authorship Unclear |
| 0.80 – 1.00 | `human` | Likely Human-Written |

**Why these thresholds:** The AI threshold is deliberately conservative at ≤ 0.35. On a writing platform, a false positive — labeling a human's work as AI-generated — is worse than a false negative. A score of 0.40 lands in "Uncertain," not "AI." This means more content receives the "Authorship Unclear" label, which is the honest outcome when the system genuinely cannot tell.

**Why not a binary 0.5 split:** The "Uncertain" band (0.36–0.79) covers 43 points of the scoring range intentionally. Forcing ambiguous scores to one extreme would manufacture false confidence. A score of 0.51 and a score of 0.95 mean different things to a reader — the system says so.

**Validation — two example submissions with meaningfully different scores:**

Example 1 — Clearly AI (score 0.231, result: `ai`):
```
Input:    "Artificial intelligence represents a transformative paradigm shift in
           modern society. It is important to note that while the benefits of AI
           are numerous, it is equally essential to consider the ethical implications.
           Furthermore, stakeholders across various sectors must collaborate to ensure
           responsible deployment."
Signal 1: 0.200  (LLM: generic register, uniform phrasing, no personal voice)
Signal 2: 0.276  (low sentence variance, mid TTR, zero expressive punctuation)
Combined: 0.231  --> Likely AI-Generated
```

Example 2 — Human, borderline (score 0.667, result: `uncertain`):
```
Input:    "I burned the grilled cheese again. Third time this week. My roommate
           didn't say anything but I saw him hide the good pan."
Signal 1: 0.900  (LLM: strong personal voice, informal register, specific detail)
Signal 2: 0.317  (short text -- variance and TTR fall back to neutral; low punct)
Combined: 0.667  --> Authorship Unclear
```

The second example illustrates the system working as intended: Signal 1 strongly reads the anecdote as human, but Signal 2 can't confirm it (the text is too short for reliable variance measurement). Rather than rubber-stamping Signal 1's confidence, the weighted combination produces a score in the "Uncertain" range. The creator can appeal if the label is wrong.

---

## Transparency Labels

The system returns one of three labels based on the combined confidence score. All three variants are shown below exactly as returned by the API and displayed to readers.

| Variant | Score Range |
|---|---|
| High-confidence AI | 0.00 – 0.35 |
| Uncertain | 0.36 – 0.79 |
| High-confidence human | 0.80 – 1.00 |

**High-confidence AI (score 0.00 – 0.35):**
> "⚠️ Likely AI-Generated: Our analysis found strong signals that this content was produced with AI assistance. The author has not verified human authorship. This label reflects automated analysis and may not be fully accurate."

**Uncertain (score 0.36 – 0.79):**
> "🔍 Authorship Unclear: Our system could not confidently determine whether this content was written by a human or generated by AI. Treat this content with that uncertainty in mind. The creator may submit an appeal if this label is incorrect."

**High-confidence human (score 0.80 – 1.00):**
> "✅ Likely Human-Written: Our analysis found strong signals that this content was written by a human author. This label reflects automated analysis and is not a guarantee."

---

## Rate Limiting

| Endpoint | Limit | Reasoning |
|---|---|---|
| `POST /submit` | 10 requests / minute per IP | A legitimate creator submits one piece at a time. 10/min allows a developer to batch-test during integration while making automated flooding expensive. Above 10/min is scripted behavior, not human behavior. |
| `POST /appeal/<id>` | 3 requests / minute per IP | Appeals are deliberate human actions — you write a reason, you submit once. 3/min prevents a script from spamming the same submission_id with junk appeals to flood the review queue. |
| `GET /log` | 30 requests / minute per IP | Read-only and lower risk, but uncapped it becomes a data scraping surface. 30/min supports rapid development use while preventing bulk extraction. |

Rate limiting is implemented with Flask-Limiter 3.x using per-IP in-memory storage. A 429 response includes a human-readable error message.

---

## Audit Log

Every attribution decision and appeal is recorded in SQLite. The log captures:

| Field | Description |
|---|---|
| `submission_id` | UUID for the submission |
| `creator_id` | Optional creator identifier from request body |
| `timestamp` | ISO 8601 UTC timestamp |
| `content_preview` | First 100 characters of submitted content |
| `signal1_score` | LLM classification score (0.0–1.0) |
| `signal2_score` | Stylometric score (0.0–1.0) |
| `confidence` | Weighted combined score |
| `result` | `ai`, `uncertain`, or `human` |
| `label` | Full verbatim transparency label text |
| `status` | `reviewed` or `under_review` |

Appeals additionally record: `appeal_id`, `creator_id`, `reason`, and `appeal_timestamp`.

Access via `GET /log` (returns most recent 50 entries) or `GET /appeals` (returns all under-review submissions with appeal reasons).

**Sample log entry:**
```json
{
  "submission_id": "e51e5177-ee68-4575-806a-a7e77b32ef80",
  "creator_id": "m5-ai-test",
  "timestamp": "2026-06-30T06:07:10.122782+00:00",
  "content_preview": "Artificial intelligence represents a transformative paradigm shift in modern society...",
  "signal1_score": 0.2,
  "signal2_score": 0.2764,
  "confidence": 0.2306,
  "result": "ai",
  "label": "Likely AI-Generated: Our analysis found strong signals...",
  "status": "under_review"
}
```

---

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/submit` | Submit content for attribution analysis |
| `POST` | `/appeal/<submission_id>` | Contest a classification |
| `GET` | `/appeals` | View all submissions under review |
| `GET` | `/log` | View full audit log |

### `POST /submit`

Request:
```json
{
  "content": "Your text here...",
  "creator_id": "optional-creator-identifier"
}
```

Response:
```json
{
  "submission_id": "abc123",
  "result": "human",
  "confidence": 0.84,
  "signal1_score": 0.88,
  "signal2_score": 0.77,
  "label": "✅ Likely Human-Written: Our analysis found strong signals that this content was written by a human author. This label reflects automated analysis and is not a guarantee.",
  "status": "reviewed"
}
```

### `POST /appeal/<submission_id>`

Request:
```json
{
  "creator_id": "creator-handle",
  "reason": "I wrote this myself. The style is intentionally simple."
}
```

Response:
```json
{
  "submission_id": "abc123",
  "status": "under_review",
  "message": "Your appeal has been recorded and will be reviewed."
}
```

---

## Known Limitations

**1. Short text is structurally unanalyzable by Signal 2.**
Texts under 3 sentences fall back to a variance score of 0.5 (neutral), and texts under 50 words fall back to a TTR score of 0.5. This means Signal 2 contributes almost no information for short poems, captions, or brief personal notes — the very content types most likely to be written by a human creator on a creative platform. In these cases, the combined score leans almost entirely on Signal 1, reducing the multi-signal benefit. The system partially mitigates this by landing short ambiguous texts in "Uncertain" rather than incorrectly labeling them.

**2. Formal human writing is the system's hardest case.**
A well-edited academic paragraph, a polished op-ed, or a professional bio will score low on both signals — Signal 1 because the LLM reads clean prose as AI-like, Signal 2 because formal writing has controlled sentence structure and conventional punctuation. This is not a calibration failure; it reflects a genuine property of the detection problem. The system handles it by being conservative: the "Likely AI" band requires a score ≤ 0.35, so a score of 0.40 on a formal human essay returns "Authorship Unclear" rather than a false accusation.

**3. The LLM signal is not deterministic.**
Signal 1 calls the Groq API with `temperature=0.1`, which is low but not zero. Running the same text twice may return slightly different scores. This is acceptable for a system that acknowledges uncertainty, but it means a submission that scores 0.34 (just inside the "AI" band) on one call might score 0.37 on another. A production deployment would either average multiple calls or widen the uncertainty band further.

---

## Spec Reflection

**One way the spec helped:** Writing out the three verbatim label texts before any implementation — required in Milestone 2 — turned out to be the most useful planning step. It forced a decision about tone and framing that would otherwise have been deferred. The "Uncertain" label in particular required real thought: it needed to explain the ambiguity honestly without making the user distrust the system entirely. Having the exact text locked before building the scoring logic meant the label function was trivial to implement — it was just a lookup, not a design problem during coding.

**One way implementation diverged from the spec:** The spec described Signal 2 as capturing "sentence length variance, type-token ratio, and punctuation density" with a single combined output. During implementation, it became clear that TTR behaves very differently depending on text length — short texts always have high TTR regardless of origin, making the raw score misleading. The implementation added a length-based fallback (texts under 50 words return a neutral 0.5 for TTR) that wasn't in the original spec. This is a case where the spec described the intent correctly but the implementation had to add a calibration step the spec didn't anticipate.

---

## AI Usage

**Instance 1 — Signal 2 sub-metric weighting.**
I directed the AI tool to generate the stylometric heuristic function given my spec's description of three sub-metrics (variance, TTR, punctuation density). The generated code combined them with equal weights (33/33/33). I overrode this after reasoning through the relative reliability of each metric: variance is the most independent and informative signal, TTR is unreliable on short texts, and punctuation is useful but narrow. I changed the weights to 50/30/20 to reflect that hierarchy. I also added the length-based TTR fallback described in the Spec Reflection section above, which the generated code did not include.

**Instance 2 — Flask app skeleton and scoring logic.**
I provided the AI tool with the architecture diagram and planning.md's uncertainty representation section and asked it to generate the Flask POST /submit route and the confidence scoring helpers. The generated code put the scoring logic (combine_scores, score_to_result, score_to_label) directly inside app.py. I refactored this into a separate scoring.py module so each concern — routing, signal computation, scoring, logging — lived in its own file. This wasn't a correctness issue but a maintainability one: as the app grew across milestones, having scoring isolated meant I could test it independently and update it without touching the Flask routes.

---

## Setup

```bash
git clone <your-repo-url>
cd ai201-project4-provenance-guard
python -m venv .venv

# Mac/Linux:
source .venv/bin/activate
# Windows (Git Bash):
source .venv/Scripts/activate
# Windows (Command Prompt):
.venv\Scripts\activate

pip install -r requirements.txt
```

Create a `.env` file in the repo root (never commit this):
```
GROQ_API_KEY=your_key_here
```

Run:
```bash
python app.py
```

The server starts on `http://localhost:5000`.
