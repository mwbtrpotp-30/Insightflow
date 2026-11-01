"""
Pydantic request/response schemas.
"""
from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel


# ── Event Ingestion ────────────────────────────────────────────────────────────

class EventIn(BaseModel):
    event_name: str
    user_id: str
    timestamp: Optional[datetime] = None
    acquisition_channel: Optional[str] = None
    country: Optional[str] = None
    plan_tier: Optional[str] = "free"
    properties: Optional[dict] = {}


class EventOut(BaseModel):
    id: int
    event_name: str
    user_id: str
    timestamp: datetime
    acquisition_channel: Optional[str]
    country: Optional[str]
    plan_tier: Optional[str]

    model_config = {"from_attributes": True}


class EventBatchIn(BaseModel):
    events: list[EventIn]


# ── Metrics ────────────────────────────────────────────────────────────────────

class MetricPoint(BaseModel):
    date: str
    value: float
    dimension_key: Optional[str] = None
    dimension_value: Optional[str] = None


class MetricSeries(BaseModel):
    metric_name: str
    points: list[MetricPoint]


# ── Investigation ──────────────────────────────────────────────────────────────

class InvestigationTrigger(BaseModel):
    metric_name: str
    current_value: Optional[float] = None    # omitted → measured from the event data
    baseline_value: Optional[float] = None   # omitted → measured from the event data
    time_window_days: int = 7
    scenario_hint: str = ""   # optional context string passed to Gemini hypothesis generator


class HypothesisOut(BaseModel):
    id: str
    label: str
    description: str
    confidence: float   # 0.0 – 1.0


class InvestigationStepOut(BaseModel):
    step_number: int
    test_name: str
    test_rationale: str          # why the selector chose this test
    hypotheses_targeted: list[str]  # which hypothesis IDs this discriminates
    result_summary: str
    p_value: Optional[float] = None
    effect_size: Optional[float] = None
    evidence: dict[str, Any]
    hypotheses_after: list[HypothesisOut]  # updated confidences


class InvestigationOut(BaseModel):
    id: int
    created_at: datetime
    triggered_metric: str
    current_value: float
    baseline_value: float
    magnitude_pct: float
    status: str
    steps: list[InvestigationStepOut]
    conclusion: Optional[str]
    recommendation: Optional[str]
    tests_run: int
    tests_skipped: int

    model_config = {"from_attributes": True}


# ── NL Query ──────────────────────────────────────────────────────────────────

class NLQueryIn(BaseModel):
    question: str


class NLQueryOut(BaseModel):
    question: str
    sql: str
    columns: list[str]
    rows: list[list[Any]]
    answer: str
    error: Optional[str] = None
