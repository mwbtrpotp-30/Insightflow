"""
Investigations API — trigger and query adaptive investigations.
"""
import json
import statistics
import threading
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from ..database import get_db, SessionLocal
from ..models import Investigation
from ..schemas import InvestigationTrigger, InvestigationOut, InvestigationStepOut, HypothesisOut
from ..services.investigation_engine import run_investigation

router = APIRouter(prefix="/investigations", tags=["investigations"])


def _run_in_background(investigation_id: int, scenario_hint: str = ""):
    """Runs the investigation in a background thread with its own DB session."""
    db = SessionLocal()
    try:
        investigation = db.query(Investigation).filter(Investigation.id == investigation_id).first()
        if investigation:
            context = {"window_days": 7, "scenario_hint": scenario_hint}
            run_investigation(db, investigation, context=context)
    finally:
        db.close()


@router.post("/trigger", status_code=202)
def trigger_investigation(
    trigger: InvestigationTrigger,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Trigger a new adaptive investigation for a metric anomaly.
    Returns immediately with the investigation ID; runs in background.

    If current_value / baseline_value are omitted, they are measured from the
    event data (same 7-day windows as the auto-detector), so the investigation
    reflects whatever scenario is actually loaded.
    """
    current_value = trigger.current_value
    baseline_value = trigger.baseline_value
    scenario_hint = trigger.scenario_hint

    if current_value is None or baseline_value is None:
        from .anomaly_detector import _fetch_metric_windows
        baseline, current = _fetch_metric_windows(db, trigger.metric_name)
        if not baseline or not current:
            raise HTTPException(
                status_code=400,
                detail=f"Not enough data to measure '{trigger.metric_name}'. Load a scenario first.",
            )
        baseline_value = round(statistics.mean(baseline), 4)
        current_value = round(statistics.mean(current), 4)
        if not scenario_hint:
            scenario_hint = (
                f"Manually triggered. Baseline mean: {baseline_value:.3f}, "
                f"Current mean: {current_value:.3f}."
            )

    magnitude_pct = (
        (current_value - baseline_value) / baseline_value * 100
        if baseline_value != 0 else 0.0
    )

    investigation = Investigation(
        triggered_metric=trigger.metric_name,
        current_value=current_value,
        baseline_value=baseline_value,
        magnitude_pct=round(magnitude_pct, 2),
        status="running",
    )
    db.add(investigation)
    db.commit()
    db.refresh(investigation)

    # Run investigation asynchronously — pass scenario hint through context
    investigation_id = investigation.id
    background_tasks.add_task(_run_in_background, investigation_id, scenario_hint)

    return {
        "investigation_id": investigation_id,
        "status": "running",
        "metric": trigger.metric_name,
        "magnitude_pct": round(magnitude_pct, 2),
        "message": "Investigation started. Poll GET /investigations/{id} for results.",
    }


@router.get("/", response_model=list[dict])
def list_investigations(
    limit: int = 20,
    db: Session = Depends(get_db),
):
    """List recent investigations."""
    rows = (
        db.query(Investigation)
        .order_by(Investigation.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": r.id,
            "created_at": r.created_at.isoformat(),
            "triggered_metric": r.triggered_metric,
            "magnitude_pct": r.magnitude_pct,
            "status": r.status,
            "tests_run": r.tests_run,
            "conclusion_preview": (r.conclusion or "")[:100] + "..." if r.conclusion and len(r.conclusion) > 100 else r.conclusion,
        }
        for r in rows
    ]


@router.delete("/{investigation_id}", status_code=204)
def delete_investigation(investigation_id: int, db: Session = Depends(get_db)):
    """Delete an investigation record."""
    inv = db.query(Investigation).filter(Investigation.id == investigation_id).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Investigation not found")
    db.delete(inv)
    db.commit()
    return None


@router.get("/{investigation_id}")
def get_investigation(investigation_id: int, db: Session = Depends(get_db)):
    """Get full investigation result including all steps."""
    inv = db.query(Investigation).filter(Investigation.id == investigation_id).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Investigation not found")

    steps = json.loads(inv.steps_json or "[]")

    return {
        "id": inv.id,
        "created_at": inv.created_at.isoformat(),
        "triggered_metric": inv.triggered_metric,
        "current_value": inv.current_value,
        "baseline_value": inv.baseline_value,
        "magnitude_pct": inv.magnitude_pct,
        "status": inv.status,
        "tests_run": inv.tests_run,
        "tests_skipped": inv.tests_skipped,
        "steps": steps,
        "conclusion": inv.conclusion,
        "recommendation": inv.recommendation,
    }
