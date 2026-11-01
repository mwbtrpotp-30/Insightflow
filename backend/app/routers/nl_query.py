"""
Natural Language Query Interface — text-to-SQL agent powered by Gemini.

Flow:
  1. User sends a natural language question
  2. Gemini generates a SQLite SQL query from the DB schema + question
  3. The query runs against the database
  4. Gemini writes a 1-sentence plain-English answer from the results
  5. Returns { question, sql, columns, rows, answer }

API endpoint: POST /api/query
"""

import json
import logging
import os
import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas import NLQueryIn, NLQueryOut

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["nl-query"])


# ── DB Schema (given to LLM as context) ──────────────────────────────────────

DB_SCHEMA = """
SQLite database for a product analytics platform called InsightFlow.

Tables:

1. events
   - id INTEGER PRIMARY KEY
   - event_name TEXT  (values: 'signup', 'onboarding_complete', 'page_view', 'session_start', 'feature_used')
   - user_id TEXT
   - timestamp DATETIME
   - acquisition_channel TEXT  (values: 'organic', 'google_ads', 'referral', 'direct')
   - country TEXT
   - plan_tier TEXT  (values: 'free', 'pro', 'enterprise')
   - properties TEXT (JSON blob, usually empty)

2. investigations
   - id INTEGER PRIMARY KEY
   - created_at DATETIME
   - triggered_metric TEXT  (e.g. 'retention_rate')
   - current_value REAL
   - baseline_value REAL
   - magnitude_pct REAL  (percentage change, negative = drop)
   - status TEXT  (values: 'running', 'completed', 'failed')
   - tests_run INTEGER
   - tests_skipped INTEGER
   - conclusion TEXT
   - recommendation TEXT
   - steps_json TEXT (JSON blob of investigation steps)

Common query patterns:
- Total users: SELECT COUNT(DISTINCT user_id) FROM events WHERE event_name = 'signup'
- Retention: ratio of users with a session_start after their signup date
- Signups by channel: GROUP BY acquisition_channel WHERE event_name = 'signup'
- Daily active users: COUNT DISTINCT user_id with session_start per day
- Recent investigations: SELECT from investigations ORDER BY created_at DESC
"""


# ── Gemini helpers ────────────────────────────────────────────────────────────

def _call_gemini(prompt: str) -> str:
    """Calls Gemini REST API and returns the response text."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set")

    import requests
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-3.5-flash-lite:generateContent?key={api_key}"
    )
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    resp = requests.post(url, json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()


def _generate_sql(question: str) -> str:
    """Ask Gemini to turn the question into a SQL query."""
    prompt = f"""You are an expert SQL developer for a product analytics platform.

Database schema:
{DB_SCHEMA}

User question: "{question}"

Write a SQLite SQL query that answers this question exactly.

Rules:
- Return ONLY the SQL query, no explanation, no markdown fences
- Use only tables and columns from the schema above
- Limit results to at most 50 rows unless the question asks for aggregates
- Use DATE() for date comparisons with DATETIME columns
- For retention: a user is retained if they had a session_start event after their signup date
- Keep it simple and correct

SQL query:"""

    raw = _call_gemini(prompt)

    # Strip markdown fences if present
    raw = re.sub(r"^```(?:sql)?\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s*```$", "", raw)
    return raw.strip()


def _generate_answer(question: str, sql: str, columns: list, rows: list) -> str:
    """Ask Gemini to write a plain-English answer from the results."""
    if not rows:
        return "No data found for this query."

    # Format a compact result preview (first 10 rows)
    preview_rows = rows[:10]
    table_str = " | ".join(columns) + "\n"
    table_str += "-" * 40 + "\n"
    for row in preview_rows:
        table_str += " | ".join(str(v) for v in row) + "\n"
    if len(rows) > 10:
        table_str += f"... ({len(rows)} total rows)\n"

    prompt = f"""You are a product analytics assistant.

The user asked: "{question}"

SQL used:
{sql}

Results:
{table_str}

Write a single clear sentence answering the user's question based on these results.
Be specific — include the actual numbers. Do not say "the query shows" or "based on the results".
Just state the answer directly."""

    return _call_gemini(prompt)


# ── API route ─────────────────────────────────────────────────────────────────

@router.post("/query", response_model=NLQueryOut)
def nl_query(body: NLQueryIn, db: Session = Depends(get_db)):
    """
    Natural language query interface.
    Converts a question to SQL via Gemini, executes it, and returns results
    with a plain-English answer.
    """
    question = body.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="question cannot be empty")

    # Check API key
    if not os.environ.get("GEMINI_API_KEY"):
        # Fallback: run a canned query to show the system works
        logger.warning("[NLQuery] GEMINI_API_KEY not set — returning mock answer")
        fallback_sql = "SELECT event_name, COUNT(*) as count FROM events GROUP BY event_name ORDER BY count DESC"
        try:
            result = db.execute(text(fallback_sql))
            cols = list(result.keys())
            rows_raw = result.fetchall()
            rows = [list(r) for r in rows_raw]
        except Exception as e:
            rows = []
            cols = []
        return NLQueryOut(
            question=question,
            sql=fallback_sql,
            columns=cols,
            rows=rows,
            answer=f"(Demo mode — GEMINI_API_KEY not set.) Event counts from database: {', '.join(f'{r[0]}={r[1]}' for r in rows[:5])}.",
        )

    # Step 1: Generate SQL
    try:
        sql = _generate_sql(question)
        logger.info(f"[NLQuery] Generated SQL: {sql[:200]}")
    except Exception as e:
        logger.error(f"[NLQuery] SQL generation failed: {e}")
        raise HTTPException(status_code=502, detail=f"SQL generation failed: {e}")

    # Step 2: Execute SQL
    try:
        result = db.execute(text(sql))
        columns = list(result.keys())
        rows_raw = result.fetchall()
        rows = [list(r) for r in rows_raw]
    except Exception as e:
        logger.error(f"[NLQuery] SQL execution failed: {e} | SQL: {sql}")
        # Return the error to the user with the SQL so they can debug
        return NLQueryOut(
            question=question,
            sql=sql,
            columns=[],
            rows=[],
            answer="",
            error=f"SQL execution error: {str(e)}",
        )

    # Step 3: Generate plain-English answer
    try:
        answer = _generate_answer(question, sql, columns, rows)
    except Exception as e:
        logger.warning(f"[NLQuery] Answer generation failed: {e}")
        answer = f"Query returned {len(rows)} row(s)."

    logger.info(f"[NLQuery] Question: '{question}' → {len(rows)} rows")

    return NLQueryOut(
        question=question,
        sql=sql,
        columns=columns,
        rows=rows,
        answer=answer,
    )
