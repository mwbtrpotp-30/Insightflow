"""
SQLAlchemy ORM models for InsightFlow.
"""
import json
from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, Text, Boolean, Index
from sqlalchemy.orm import relationship
from .database import Base


class Event(Base):
    """Raw user behavioral events — the core data layer."""
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, index=True)
    event_name = Column(String(100), nullable=False, index=True)
    user_id = Column(String(100), nullable=False, index=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    # Acquisition channel: organic, google_ads, facebook_ads, referral
    acquisition_channel = Column(String(50), index=True)
    # User country
    country = Column(String(50), index=True)
    # Plan tier: free, pro, enterprise
    plan_tier = Column(String(20), index=True)
    # Additional properties as JSON string
    properties = Column(Text, default="{}")

    @property
    def props(self):
        return json.loads(self.properties or "{}")

    __table_args__ = (
        Index("ix_events_timestamp_name", "timestamp", "event_name"),
        Index("ix_events_user_channel", "user_id", "acquisition_channel"),
    )


class DailyMetric(Base):
    """Pre-computed daily metrics for quick charting."""
    __tablename__ = "daily_metrics"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(DateTime, nullable=False, index=True)
    metric_name = Column(String(100), nullable=False, index=True)
    # Optional dimension (e.g. acquisition_channel=google_ads)
    dimension_key = Column(String(50), nullable=True)
    dimension_value = Column(String(100), nullable=True)
    value = Column(Float, nullable=False)

    __table_args__ = (
        Index("ix_daily_metrics_date_name", "date", "metric_name"),
    )


class Investigation(Base):
    """One investigation run triggered by an anomaly."""
    __tablename__ = "investigations"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    triggered_metric = Column(String(100), nullable=False)
    current_value = Column(Float)
    baseline_value = Column(Float)
    magnitude_pct = Column(Float)  # % change from baseline
    status = Column(String(20), default="running")  # running | completed | failed
    # Serialized list of InvestigationStep dicts
    steps_json = Column(Text, default="[]")
    # Final conclusion from synthesis agent
    conclusion = Column(Text, nullable=True)
    # Recommended action
    recommendation = Column(Text, nullable=True)
    # How many tests were run (vs hypothetical max)
    tests_run = Column(Integer, default=0)
    tests_skipped = Column(Integer, default=0)

    @property
    def steps(self):
        return json.loads(self.steps_json or "[]")

    @steps.setter
    def steps(self, value):
        self.steps_json = json.dumps(value)
