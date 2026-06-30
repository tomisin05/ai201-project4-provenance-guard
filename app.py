"""
Provenance Guard — Flask API
Milestone 5: Full production layer — all endpoints live
"""

import uuid
from flask import Flask, request, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from dotenv import load_dotenv

from signal1_llm import classify_with_llm
from signal2_stylometric import compute_stylometric_score
from scoring import combine_scores, score_to_result, score_to_label
import audit_log as db

load_dotenv()

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Rate limiting
# Limits chosen per planning.md rationale:
#   /submit     — 10/min: one creator submits one piece at a time
#   /appeal     — 3/min:  deliberate human action, prevent spam
#   /log        — 30/min: read-only but capped against scraping
# ---------------------------------------------------------------------------
limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=[],
    storage_uri="memory://",
)

db.init_db()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/submit", methods=["POST"])
@limiter.limit("10 per minute")
def submit():
    """
    POST /submit
    Body: { "content": "...", "creator_id": "optional" }
    Returns: submission_id, result, confidence, signal scores, label, status
    """
    body = request.get_json(silent=True)
    if not body or not body.get("content"):
        return jsonify({"error": "Request body must include a non-empty 'content' field."}), 400

    content: str = body["content"].strip()
    creator_id: str = body.get("creator_id", "")

    if len(content) < 20:
        return jsonify({"error": "Content is too short for meaningful analysis (minimum 20 characters)."}), 400

    submission_id = str(uuid.uuid4())

    # Signal 1 — LLM classification (live)
    signal1_score = classify_with_llm(content)

    # Signal 2 — stylometric heuristics (live)
    signal2_score = compute_stylometric_score(content)

    confidence = combine_scores(signal1_score, signal2_score)
    result = score_to_result(confidence)
    label = score_to_label(confidence)

    db.log_submission(
        submission_id=submission_id,
        creator_id=creator_id,
        content=content,
        signal1_score=signal1_score,
        signal2_score=signal2_score,
        confidence=confidence,
        result=result,
        label=label,
    )

    return jsonify({
        "submission_id": submission_id,
        "result": result,
        "confidence": confidence,
        "signal1_score": signal1_score,
        "signal2_score": signal2_score,
        "label": label,
        "status": "reviewed",
    }), 200


@app.route("/log", methods=["GET"])
@limiter.limit("30 per minute")
def log():
    """
    GET /log
    Returns the most recent audit log entries.
    Query param: ?limit=N (default 50, max 100)
    """
    try:
        limit = min(int(request.args.get("limit", 50)), 100)
    except ValueError:
        limit = 50

    entries = db.get_log(limit=limit)
    return jsonify({"entries": entries, "count": len(entries)}), 200


# ---------------------------------------------------------------------------
# Placeholder routes — implemented in Milestone 5
# ---------------------------------------------------------------------------

@app.route("/appeal/<submission_id>", methods=["POST"])
@limiter.limit("3 per minute")
def appeal(submission_id):
    """
    POST /appeal/<submission_id>
    Body: { "creator_id": "...", "reason": "..." }
    Updates submission status to 'under_review' and logs the appeal.
    """
    body = request.get_json(silent=True)
    if not body:
        return jsonify({"error": "Request body is required."}), 400

    creator_id: str = body.get("creator_id", "").strip()
    reason: str = body.get("reason", "").strip()

    if not reason:
        return jsonify({"error": "'reason' field is required — explain why you believe the classification is incorrect."}), 400

    if len(reason) > 1000:
        return jsonify({"error": "'reason' must be 1000 characters or fewer."}), 400

    # Verify the submission exists and log the appeal
    found = db.log_appeal(
        submission_id=submission_id,
        creator_id=creator_id,
        reason=reason,
    )

    if not found:
        return jsonify({"error": f"Submission '{submission_id}' not found."}), 404

    return jsonify({
        "submission_id": submission_id,
        "status": "under_review",
        "message": "Your appeal has been recorded and will be reviewed.",
    }), 200


@app.route("/appeals", methods=["GET"])
def appeals():
    """
    GET /appeals
    Returns all submissions currently under review, with appeal reasons.
    """
    entries = db.get_appeals()
    return jsonify({"appeals": entries, "count": len(entries)}), 200


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------

@app.errorhandler(429)
def rate_limit_exceeded(e):
    return jsonify({"error": "Rate limit exceeded. Please slow down.", "details": str(e)}), 429


@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Endpoint not found."}), 404


@app.errorhandler(500)
def internal_error(e):
    return jsonify({"error": "Internal server error.", "details": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)
