# Provenance Guard — Planning Document

## Architecture

### Submission Flow Narrative

A piece of text enters via `POST /submit`. It passes through two independent detection signals: (1) an LLM-based classifier via Groq that evaluates semantic and stylistic coherence, and (2) a stylometric heuristic engine that computes measurable statistical properties of the text. The two signal scores are combined into a single confidence score, which is mapped to one of three transparency label variants. The decision — including both signal scores, the combined score, and the label — is written to the audit log, then returned to the caller.

An appeal enters via `POST /appeal/<submission_id>`. The system retrieves the original decision, records the creator's reasoning, updates the submission status to "under review," and writes an appeal entry to the audit log.

### Architecture Diagram

```
POST /submit
     │
     ▼
┌─────────────────────────────┐
│     Input Validation        │
└─────────────┬───────────────┘
              │ raw text
    ┌─────────┴──────────┐
    ▼                    ▼
┌──────────────┐  ┌──────────────────────┐
│ Signal 1:    │  │ Signal 2:            │
│ LLM Classify │  │ Stylometric Heuristic│
│ (Groq)       │  │ (pure Python)        │
│ → score 0–1  │  │ → score 0–1          │
└──────┬───────┘  └──────────┬───────────┘
       │   s1_score          │ s2_score
       └──────────┬──────────┘
                  ▼
        ┌──────────────────┐
        │ Confidence Scorer │
        │ weighted average  │
        │ → combined 0–1    │
        └────────┬─────────┘
                 │ confidence_score
                 ▼
        ┌──────────────────┐
        │  Label Generator  │
        │ high-AI / unsure  │
        │ / high-human      │
        └────────┬─────────┘
                 │ label_text
                 ▼
        ┌──────────────────┐
        │   Audit Logger   │◄── submission_id, signals, score, label
        └────────┬─────────┘
                 │
                 ▼
           JSON Response
           (id, result, confidence, label)


POST /appeal/<submission_id>
     │
     ▼
┌──────────────────────────┐
│  Load original decision  │
│  Capture creator reason  │
│  Status → "under review" │
└────────────┬─────────────┘
             │
             ▼
     ┌───────────────┐
     │  Audit Logger │◄── appeal_reason, original_decision
     └───────────────┘
             │
             ▼
       JSON Response
       (status: "under review")
```

---

## Detection Signals

### Signal 1 — LLM Classification (Groq, llama-3.3-70b-versatile)

**What it measures:** Holistic semantic and stylistic coherence. The model is prompted to assess whether the text reads as human-authored or AI-generated based on naturalness of expression, idiosyncratic word choices, emotional register, and narrative voice.

**Why it differs between human and AI text:** Human writing carries personal quirks, unexpected metaphors, tonal inconsistencies, and emotionally authentic phrasing. AI writing tends toward polished, coherent, slightly generic prose with consistent register.

**Output:** A score from 0.0 (confident AI) to 1.0 (confident human), parsed from the model's structured response.

**Blind spots:** LLMs can confuse competent, clear human writing for AI. Edited or heavily revised human text may score lower. The model's own biases about what "sounds human" may not generalize.

---

### Signal 2 — Stylometric Heuristics (pure Python)

**What it measures:** Statistical properties of surface text: sentence length variance, type-token ratio (vocabulary diversity), punctuation density, and average sentence length.

**Why it differs:** AI-generated text is statistically uniform — sentences cluster around similar lengths, vocabulary is diverse but not unusually so, punctuation is minimal and conventional. Human writing is noisier: high variance in sentence length, idiosyncratic punctuation, and either unusually high or low vocabulary density depending on author style.

**Output:** A score from 0.0 (AI-like uniformity) to 1.0 (human-like variability), computed from a weighted combination of the four sub-metrics.

**Blind spots:** Short texts (< 5 sentences) yield unreliable variance estimates. A poet who writes deliberately uniform short lines may score low. A verbose AI prompt can produce high variance output.

---

## Uncertainty Representation

| Confidence Score | Interpretation          | Label Variant          |
| ---------------- | ----------------------- | ---------------------- |
| ≥ 0.80           | High confidence — human | "Likely Human-Written" |
| ≤ 0.35           | High confidence — AI    | "Likely AI-Generated"  |
| 0.36 – 0.79      | Uncertain               | "Authorship Unclear"   |

**Combining signals:** The combined score is a weighted average: `confidence = 0.60 * s1 + 0.40 * s2`. Signal 1 (LLM) receives higher weight because it captures semantic nuance that heuristics cannot. Signal 2 acts as a tiebreaker and sanity check.

**What 0.6 means:** The system has a moderate lean toward human authorship but cannot confidently distinguish. The label will say "Authorship Unclear" and recommend the reader consider this context. It does NOT say "AI-generated."

**Asymmetric design (false positive protection):** To avoid labeling human work as AI (false positive), the AI threshold is set low (≤ 0.35). A score of 0.40 is uncertain, not AI. This means more content lands in the "Uncertain" bucket.

---

## Transparency Label Variants

These are the verbatim label texts returned by the API and shown to readers.

**High-confidence AI (score ≤ 0.35):**

> "Likely AI-Generated: Our analysis found strong signals that this content was produced with AI assistance. The author has not verified human authorship. This label reflects automated analysis and may not be fully accurate."

**Uncertain (score 0.36–0.79):**

> "Authorship Unclear: Our system could not confidently determine whether this content was written by a human or generated by AI. Treat this content with that uncertainty in mind. The creator may submit an appeal if this label is incorrect."

**High-confidence human (score ≥ 0.80):**

> "✅ Likely Human-Written: Our analysis found strong signals that this content was written by a human author. This label reflects automated analysis and is not a guarantee."

---

## Appeals Workflow

**Who can appeal:** Any creator who submitted content (identified by `submission_id`).

**What they provide:** `submission_id`, `creator_id` (string identifier), and `reason` (free-text explanation, max 1000 chars).

**What the system does:**

1. Retrieves the original audit log entry for the submission.
2. Updates the submission's `status` field to `"under_review"`.
3. Writes a new audit log entry of type `"appeal"` containing: `submission_id`, `creator_id`, `reason`, original `confidence_score`, original `label`, and `timestamp`.
4. Returns a confirmation response.

**What a human reviewer sees:** A `GET /appeals` endpoint returns all entries with `status = "under_review"`, ordered by timestamp, showing: original label, confidence score, both signal scores, and the creator's stated reason.

---

## Anticipated Edge Cases

1. **Short poetry with deliberate repetition and simple diction** (e.g., a prose poem): stylometric heuristics will flag low vocabulary diversity and low sentence variance, producing a falsely low Signal 2 score. The LLM signal should compensate if the emotional register reads as authentic, but combined score may land in "Uncertain" for genuinely human work.

2. **Heavily edited AI-assisted drafts** where a human substantially rewrote AI output: both signals may disagree — heuristics may show high variance (due to editing inconsistencies) while the LLM detects residual AI phrasing. The combined score will likely be in the "Uncertain" range, which is the correct and honest output for this case.

3. **Very long text:** Groq API token limits may require truncation. The LLM signal will only see the truncated portion, potentially missing stylistic shifts mid-document.

4. **Non-English or code-mixed text:** Both signals are calibrated for English prose. Non-English text will produce unreliable scores;

---

## AI Tool Plan

### M3 — Submission Endpoint + Signal 1 (LLM)

**Spec sections to provide:** Detection Signals (Signal 1), Architecture Diagram, Transparency Label Variants.

**What to ask for:** Flask app skeleton with `POST /submit` endpoint, Signal 1 function that calls Groq and returns a float 0–1, and stub for Signal 2.

**Verification:** Call the endpoint with 3 inputs — a clearly AI-sounding paragraph, a clearly personal human anecdote, and an ambiguous text. Confirm Signal 1 scores differ meaningfully before wiring the full pipeline.

---

### M4 — Signal 2 + Confidence Scoring

**Spec sections to provide:** Detection Signals (Signal 2), Uncertainty Representation, Architecture Diagram.

**What to ask for:** Stylometric heuristic function (sentence length variance, TTR, punctuation density), weighted combination logic, and threshold-to-label mapping.

**Verification:** Run the same 3 test inputs. Confirm: (a) Signal 2 scores differ from Signal 1 for at least one input, proving independence; (b) combined scores produce different labels for clearly AI vs. clearly human text; (c) a borderline text lands in "Uncertain."

---

### M5 — Production Layer (Labels, Appeals, Rate Limiting, Audit Log)

**Spec sections to provide:** Transparency Label Variants, Appeals Workflow, Architecture Diagram.

**What to ask for:** Label generator function, `POST /appeal/<id>` endpoint, `GET /appeals` endpoint, SQLite audit log schema and write/read functions, Flask-Limiter configuration.

**Verification:** (a) Trigger all three label variants by crafting inputs that land in each score range; (b) submit an appeal and confirm status changes to "under_review" in `GET /appeals`; (c) confirm audit log entries appear in `GET /log` with all required fields; (d) hit the rate limit and confirm 429 response.
