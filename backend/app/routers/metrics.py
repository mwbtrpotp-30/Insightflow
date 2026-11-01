"""
Metrics API — returns pre-computed daily metrics for the dashboard.
"""
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session
from ..database import get_db
from ..schemas import MetricSeries, MetricPoint

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("/retention", response_model=MetricSeries)
def retention_over_time(
    days: int = Query(default=30, ge=7, le=90),
    db: Session = Depends(get_db),
):
    """Daily retention rate: % of users who had a session_start today out of all users who ever signed up."""
    end = datetime.utcnow()
    start = end - timedelta(days=days)

    q = text("""
        WITH date_series AS (
            SELECT date(timestamp) AS d
            FROM events
            WHERE timestamp BETWEEN :start AND :end
            GROUP BY date(timestamp)
        ),
        signups_total AS (
            SELECT COUNT(DISTINCT user_id) AS total
            FROM events
            WHERE event_name = 'signup' AND timestamp <= :end
        ),
        daily_active AS (
            SELECT date(timestamp) AS d, COUNT(DISTINCT user_id) AS dau
            FROM events
            WHERE event_name IN ('session_start', 'feature_used', 'page_view')
              AND timestamp BETWEEN :start AND :end
            GROUP BY date(timestamp)
        )
        SELECT ds.d, CAST(COALESCE(da.dau, 0) AS FLOAT) / NULLIF(st.total, 0) AS retention_rate
        FROM date_series ds
        CROSS JOIN signups_total st
        LEFT JOIN daily_active da ON ds.d = da.d
        ORDER BY ds.d
    """)

    rows = db.execute(q, {"start": start, "end": end}).fetchall()
    points = [
        MetricPoint(date=str(r.d), value=round(float(r.retention_rate or 0) * 100, 2))
        for r in rows
    ]
    return MetricSeries(metric_name="retention_rate_pct", points=points)


@router.get("/dau", response_model=MetricSeries)
def dau_over_time(
    days: int = Query(default=30, ge=7, le=90),
    db: Session = Depends(get_db),
):
    """Daily Active Users."""
    end = datetime.utcnow()
    start = end - timedelta(days=days)

    q = text("""
        SELECT date(timestamp) AS d, COUNT(DISTINCT user_id) AS dau
        FROM events
        WHERE event_name IN ('session_start', 'feature_used', 'page_view')
          AND timestamp BETWEEN :start AND :end
        GROUP BY date(timestamp)
        ORDER BY d
    """)

    rows = db.execute(q, {"start": start, "end": end}).fetchall()
    points = [MetricPoint(date=str(r.d), value=float(r.dau)) for r in rows]
    return MetricSeries(metric_name="dau", points=points)


@router.get("/retention_by_channel", response_model=list[MetricSeries])
def retention_by_channel(
    days: int = Query(default=14, ge=7, le=60),
    db: Session = Depends(get_db),
):
    """Retention rate per acquisition channel over time."""
    end = datetime.utcnow()
    start = end - timedelta(days=days)

    q = text("""
        WITH channels AS (
            SELECT DISTINCT acquisition_channel FROM events
            WHERE acquisition_channel IS NOT NULL
        ),
        signups_by_channel AS (
            SELECT acquisition_channel, COUNT(DISTINCT user_id) AS total
            FROM events WHERE event_name = 'signup' AND timestamp <= :end
            GROUP BY acquisition_channel
        ),
        daily_active_by_channel AS (
            SELECT date(e.timestamp) AS d, e.acquisition_channel,
                   COUNT(DISTINCT e.user_id) AS dau
            FROM events e
            WHERE e.event_name IN ('session_start', 'feature_used')
              AND e.timestamp BETWEEN :start AND :end
              AND e.acquisition_channel IS NOT NULL
            GROUP BY date(e.timestamp), e.acquisition_channel
        )
        SELECT da.d, da.acquisition_channel,
               CAST(da.dau AS FLOAT) / NULLIF(sc.total, 0) AS retention_rate
        FROM daily_active_by_channel da
        JOIN signups_by_channel sc ON da.acquisition_channel = sc.acquisition_channel
        ORDER BY da.acquisition_channel, da.d
    """)

    rows = db.execute(q, {"start": start, "end": end}).fetchall()

    # Group by channel
    from collections import defaultdict
    channel_points: dict = defaultdict(list)
    for r in rows:
        channel_points[r.acquisition_channel].append(
            MetricPoint(date=str(r.d), value=round(float(r.retention_rate or 0) * 100, 2))
        )

    return [
        MetricSeries(metric_name=f"retention_{ch}", points=pts)
        for ch, pts in channel_points.items()
    ]


@router.get("/funnel")
def funnel_snapshot(db: Session = Depends(get_db)):
    """Aggregate funnel for the last 7 days."""
    end = datetime.utcnow()
    start = end - timedelta(days=7)

    q = text("""
        SELECT event_name, COUNT(DISTINCT user_id) AS users
        FROM events
        WHERE event_name IN ('signup', 'onboarding_complete', 'feature_used', 'session_start')
          AND timestamp BETWEEN :start AND :end
        GROUP BY event_name
    """)
    rows = db.execute(q, {"start": start, "end": end}).fetchall()
    return {r.event_name: r.users for r in rows}
