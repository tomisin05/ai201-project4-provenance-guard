"""
Audit Log — SQLite-backed structured logger
Every attribution decision and appeal is recorded here.

Schema (submissions table):
    submission_id   TEXT PRIMARY KEY
    creator_id      TEXT
    timestamp       TEXT (ISO 8601)
    content_preview TEXT (first 100 chars)
    signal1_score   REAL
    signal2_score   REAL  -- NULL until M4 wires it in
    confidence      REAL
    result          TEXT  ('ai' | 'human' | 'uncertain')
    label           TEXT
    status          TEXT  ('reviewed' | 'under_review')

Schema (appeals table):
    appeal_id       TEXT PRIMARY KEY
    submission_id   TEXT (FK → submissions)
    creator_id      TEXT
    timestamp       TEXT
    reason          TEXT
"""

import os
import sqlite3
import uuid
from datetime import datetime, timezone

DB_PATH = os.path.join(os.path.dirname(__file__), "audit_log.db")


def _get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create tables if they don't exist. Call once at app startup."""
    with _get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS submissions (
                submission_id   TEXT PRIMARY KEY,
                creator_id      TEXT,
                timestamp       TEXT NOT NULL,
                content_preview TEXT,
                signal1_score   REAL,
                signal2_score   REAL,
                confidence      REAL,
                result          TEXT,
                label           TEXT,
                status          TEXT DEFAULT 'reviewed'
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS appeals (
                appeal_id       TEXT PRIMARY KEY,
                submission_id   TEXT NOT NULL,
                creator_id      TEXT,
                timestamp       TEXT NOT NULL,
                reason          TEXT,
                FOREIGN KEY (submission_id) REFERENCES submissions(submission_id)
            )
        """)
        conn.commit()


def log_submission(
    submission_id: str,
    creator_id: str,
    content: str,
    signal1_score: float,
    signal2_score: float | None,
    confidence: float,
    result: str,
    label: str,
) -> None:
    """Insert a new submission record into the audit log."""
    with _get_connection() as conn:
        conn.execute(
            """
            INSERT INTO submissions
                (submission_id, creator_id, timestamp, content_preview,
                 signal1_score, signal2_score, confidence, result, label, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'reviewed')
            """,
            (
                submission_id,
                creator_id or "",
                _now(),
                content[:100],
                signal1_score,
                signal2_score,
                confidence,
                result,
                label,
            ),
        )
        conn.commit()


def log_appeal(submission_id: str, creator_id: str, reason: str) -> bool:
    """
    Record an appeal and update the submission status to 'under_review'.

    Returns True if the submission was found, False if not.
    """
    with _get_connection() as conn:
        row = conn.execute(
            "SELECT submission_id FROM submissions WHERE submission_id = ?",
            (submission_id,),
        ).fetchone()

        if not row:
            return False

        appeal_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO appeals (appeal_id, submission_id, creator_id, timestamp, reason)
            VALUES (?, ?, ?, ?, ?)
            """,
            (appeal_id, submission_id, creator_id or "", _now(), reason),
        )
        conn.execute(
            "UPDATE submissions SET status = 'under_review' WHERE submission_id = ?",
            (submission_id,),
        )
        conn.commit()
        return True


def get_log(limit: int = 50) -> list[dict]:
    """Return the most recent submission log entries as a list of dicts."""
    with _get_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM submissions
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]


def get_appeals() -> list[dict]:
    """Return all submissions currently under review, joined with their appeal reasons."""
    with _get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                s.submission_id,
                s.creator_id,
                s.timestamp         AS submission_timestamp,
                s.content_preview,
                s.signal1_score,
                s.signal2_score,
                s.confidence,
                s.result,
                s.label,
                a.timestamp         AS appeal_timestamp,
                a.reason,
                a.creator_id        AS appellant_id
            FROM submissions s
            JOIN appeals a ON s.submission_id = a.submission_id
            WHERE s.status = 'under_review'
            ORDER BY a.timestamp DESC
            """
        ).fetchall()
        return [dict(row) for row in rows]


def get_submission(submission_id: str) -> dict | None:
    """Fetch a single submission record by ID."""
    with _get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM submissions WHERE submission_id = ?",
            (submission_id,),
        ).fetchone()
        return dict(row) if row else None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
