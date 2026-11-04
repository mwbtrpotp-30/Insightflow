"""
Anomaly Auto-Detector — background monitor that watches metrics and
automatically fires investigations when a statistical anomaly is detected.

Method: Kolmogorov-Smirnov (KS) two-sample test on rolling retention windows.
  - Baseline window: days -14 to -8 (7-day window, older)
  - Current window: days -7 to -1 (7-day window, recent)
  - If KS p-value < ANOMALY_THRESHOLD: fire investigation automatically

The monitor can be started as a background thread or triggered manually
via the API endpoint /api/monitor/check.

API endpoints (mounted in main.py):
  POST /api/monitor/check   — run one detection pass right now
  GET  /api/monitor/status  — last check time, last anomaly found
"""

import logging
import os
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..database import SessionLocal, get_db
from ..models import Investigation

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/monitor", tags=["monitor"])

# ── Config ────────────────────────────────────────────────────────────────────
ANOMALY_P_THRESHOLD = 0.05   # KS p-value below this → anomaly
MIN_SAMPLES = 5              # need at least this many data points per window

# ── In-memory status ──────────────────────────────────────────────────────────
_monitor_status = {
    "last_check": None,
    "last_anomaly_metric": None,
    "last_anomaly_p": None,
    "last_investigation_id": None,
    "checks_run": 0,
    "anomalies_found": 0,
}

METRICS_TO_WATCH = ["retention_rate", "activation_rate", "feature_adoption_rate"]


# ── Core detection logic ──────────────────────────────────────────────────────

def _get_daily_retention(db: Session, start_date: datetime, end_date: datetime) -> list[float]:
    """
    Computes day-by-day retention values between start_date and end_date.
    Returns list of floats (one per day that has data).
    """
    sql = text("""
        WITH signups AS (
            SELECT DATE(timestamp) as day, user_id
            FROM events
            WHERE event_name = 'signup'
              AND timestamp >= :start AND timestamp < :end
        ),
        returners AS (
            SELECT DATE(s.day) as day, COUNT(DISTINCT e.user_id) as returned
            FROM signups s
            LEFT JOIN events e
                ON e.user_id = s.user_id
               AND e.event_name = 'session_start'
               AND DATE(e.timestamp) > DATE(s.day)
               AND DATE(e.timestamp) <= DATE(s.day, '+7 days')
            GROUP BY DATE(s.day)
        ),
        totals AS (
            SELECT day, COUNT(DISTINCT user_id) as total
            FROM signups
            GROUP BY day
        )
        SELECT t.day,
               CAST(COALESCE(r.returned, 0) AS FLOAT) / NULLIF(t.total, 0) as rate
        FROM totals t
        LEFT JOIN returners r ON r.day = t.day
        WHERE t.total >= 1
        ORDER BY t.day
    """)
    rows = db.execute(sql, {"start": start_date, "end": end_date}).fetchall()
    return [float(r[1]) for r in rows if r[1] is not None]


def _get_daily_activation(db: Session, start_date: datetime, end_date: datetime) -> list[float]:
    """Day-by-day activation rate (signup → feature_use within 1 day)."""
    sql = text("""
        WITH signups AS (
            SELECT DATE(timestamp) as day, user_id
            FROM events
            WHERE event_name = 'signup'
              AND timestamp >= :start AND timestamp < :end
        ),
        activators AS (
            SELECT DATE(s.day) as day, COUNT(DISTINCT e.user_id) as activated
            FROM signups s
            LEFT JOIN events e
                ON e.user_id = s.user_id
               AND e.event_name = 'feature_used'
               AND DATE(e.timestamp) = DATE(s.day)
            GROUP BY DATE(s.day)
        ),
        totals AS (
            SELECT day, COUNT(DISTINCT user_id) as total
            FROM signups
            GROUP BY day
        )
        SELECT t.day,
               CAST(COALESCE(a.activated, 0) AS FLOAT) / NULLIF(t.total, 0) as rate
        FROM totals t
        LEFT JOIN activators a ON a.day = t.day
        WHERE t.total >= 1
        ORDER BY t.day
    """)
    rows = db.execute(sql, {"start": start_date, "end": end_date}).fetchall()
    return [float(r[1]) for r in rows if r[1] is not None]


def _get_daily_feature_adoption(db: Session, start_date: datetime, end_date: datetime) -> list[float]:
    """Day-by-day feature adoption (events with feature_use per active user per day)."""
    sql = text("""
        WITH active AS (
            SELECT DATE(timestamp) as day, COUNT(DISTINCT user_id) as dau
            FROM events
            WHERE event_name = 'session_start'
              AND timestamp >= :start AND timestamp < :end
            GROUP BY DATE(timestamp)
        ),
        adopters AS (
            SELECT DATE(timestamp) as day, COUNT(DISTINCT user_id) as cnt
            FROM events
            WHERE event_name = 'feature_used'
              AND timestamp >= :start AND timestamp < :end
            GROUP BY DATE(timestamp)
        )
        SELECT a.day,
               CAST(COALESCE(d.cnt, 0) AS FLOAT) / NULLIF(a.dau, 0) as rate
        FROM active a
        LEFT JOIN adopters d ON d.day = a.day
        WHERE a.dau >= 1
        ORDER BY a.day
    """)
    rows = db.execute(sql, {"start": start_date, "end": end_date}).fetchall()
    return [float(r[1]) for r in rows if r[1] is not None]


def _fetch_metric_windows(db: Session, metric: str):
    """Returns (baseline_values, current_values) for the given metric."""
    now = datetime.utcnow()
    baseline_start = now - timedelta(days=14)
    baseline_end = now - timedelta(days=7)
    current_start = now - timedelta(days=7)
    current_end = now

    if metric == "retention_rate":
        baseline = _get_daily_retention(db, baseline_start, baseline_end)
        current = _get_daily_retention(db, current_start, current_end)
    elif metric == "activation_rate":
        baseline = _get_daily_activation(db, baseline_start, baseline_end)
        current = _get_daily_activation(db, current_start, current_end)
    elif metric == "feature_adoption_rate":
        baseline = _get_daily_feature_adoption(db, baseline_start, baseline_end)
        current = _get_daily_feature_adoption(db, current_start, current_end)
    else:
        return [], []

    return baseline, current


def _ks_test(baseline: list[float], current: list[float]) -> tuple[float, float]:
    """
    Two-sample Kolmogorov-Smirnov test.
    Returns (ks_statistic, p_value).
    Falls back to a simple mean-difference heuristic if scipy is unavailable.
    """
    try:
        from scipy.stats import ks_2samp
        stat, p = ks_2samp(baseline, current)
        return float(stat), float(p)
    except ImportError:
        # Fallback: if mean difference is large relative to baseline std, treat as anomaly
        import statistics
        b_mean = statistics.mean(baseline) if baseline else 0
        c_mean = statistics.mean(current) if current else 0
        b_std = statistics.stdev(baseline) if len(baseline) > 1 else 0.01
        z = abs(b_mean - c_mean) / b_std if b_std > 0 else 0
        # Rough p-value approximation: p ≈ exp(-z)
        import math
        p = math.exp(-z)
        return z, p


def run_detection_pass(db: Session) -> dict:
    """
    Runs one detection pass across all watched metrics.
    Fires investigations for any detected anomalies.
    Returns summary dict.
    """
    from .investigations import _run_in_background

    _monitor_status["last_check"] = datetime.utcnow().isoformat()
    _monitor_status["checks_run"] += 1

    results = []
    anomalies_fired = []

    for metric in METRICS_TO_WATCH:
        baseline, current = _fetch_metric_windows(db, metric)

        if len(baseline) < MIN_SAMPLES or len(current) < MIN_SAMPLES:
            results.append({
                "metric": metric,
                "status": "skipped",
                "reason": f"insufficient data (baseline={len(baseline)}, current={len(current)})",
            })
            continue

        ks_stat, p_value = _ks_test(baseline, current)

        import statistics
        baseline_mean = statistics.mean(baseline)
        current_mean = statistics.mean(current)
        magnitude_pct = ((current_mean - baseline_mean) / baseline_mean * 100) if baseline_mean != 0 else 0

        is_anomaly = p_value < ANOMALY_P_THRESHOLD and abs(magnitude_pct) > 5

        result_entry = {
            "metric": metric,
            "status": "anomaly" if is_anomaly else "normal",
            "ks_statistic": round(ks_stat, 4),
            "p_value": round(p_value, 4),
            "baseline_mean": round(baseline_mean, 4),
            "current_mean": round(current_mean, 4),
            "magnitude_pct": round(magnitude_pct, 2),
        }

        if is_anomaly:
            hint = f"Auto-detected by KS-test monitor. Baseline mean: {baseline_mean:.3f}, Current mean: {current_mean:.3f}, KS p-value: {p_value:.4f}, Change: {magnitude_pct:+.1f}%."
            inv = Investigation(
                triggered_metric=metric,
                current_value=round(current_mean, 4),
                baseline_value=round(baseline_mean, 4),
                magnitude_pct=round(magnitude_pct, 2),
                status="running",
            )
            db.add(inv)
            # Flush to get the id without committing yet — we batch-commit after the loop
            db.flush()

            result_entry["investigation_id"] = inv.id
            anomalies_fired.append({"metric": metric, "investigation_id": inv.id, "hint": hint})

            _monitor_status["last_anomaly_metric"] = metric
            _monitor_status["last_anomaly_p"] = round(p_value, 4)
            _monitor_status["last_investigation_id"] = inv.id
            _monitor_status["anomalies_found"] += 1

            logger.info(
                f"[AnomalyDetector] ANOMALY: {metric} changed {magnitude_pct:+.1f}% "
                f"(KS p={p_value:.4f}) → will fire investigation #{inv.id}"
            )
        else:
            logger.info(f"[AnomalyDetector] {metric}: normal (KS p={p_value:.4f}, Δ={magnitude_pct:+.1f}%)")

        results.append(result_entry)

    # Commit all new Investigation records in ONE transaction before starting any threads.
    # This prevents a race where a background thread is already writing while the route
    # is still committing more records.
    if anomalies_fired:
        db.commit()

    import threading
    for entry in anomalies_fired:
        t = threading.Thread(
            target=_run_in_background,
            args=(entry["investigation_id"], entry.get("hint", "")),
            daemon=True,
        )
        t.start()

    return {
        "checked_at": _monitor_status["last_check"],
        "metrics_checked": len(results),
        "anomalies_fired": len(anomalies_fired),
        "investigations": anomalies_fired,
        "details": results,
    }


# ── API routes ────────────────────────────────────────────────────────────────

@router.get("/metric-values")
def get_metric_values(metric: str, db: Session = Depends(get_db)):
    """
    Returns the real current and baseline averages for a given metric,
    using the same 7-day windows as the anomaly detector.
    """
    import statistics
    try:
        baseline, current = _fetch_metric_windows(db, metric)
        if not baseline or not current:
            return {"metric": metric, "current_value": None, "baseline_value": None, "error": "insufficient data"}
        return {
            "metric": metric,
            "current_value": round(statistics.mean(current), 4),
            "baseline_value": round(statistics.mean(baseline), 4),
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.post("/check")
def run_check(db: Session = Depends(get_db)):
    """
    Manually trigger one anomaly detection pass across all watched metrics.
    Fires investigations automatically for any detected anomalies.
    """
    try:
        return run_detection_pass(db)
    except Exception as e:
        logger.exception(f"[AnomalyDetector] /check failed: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": str(e), "anomalies_fired": 0, "metrics_checked": 0},
        )


@router.get("/status")
def get_status():
    """Return the last detection pass summary."""
    return {
        **_monitor_status,
        "metrics_watched": METRICS_TO_WATCH,
        "ks_p_threshold": ANOMALY_P_THRESHOLD,
    }
