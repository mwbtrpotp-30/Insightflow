"""
Adaptive Investigation Engine — the main loop.

Flow:
  1. Generate initial hypotheses (LLM or mock)
  2. Loop until conclusive or budget exhausted:
     a. Greedy selector picks highest-scoring untested test
     b. Investigator runs the test against the DB
     c. Evidence store updates hypothesis confidences
     d. Check if any hypothesis is now conclusive (>70%)
     e. Eliminate hypotheses below threshold
  3. Synthesis agent produces conclusion + recommendation
  4. Persist investigation record to DB

This is the "Adaptive Sequential Investigation" that differentiates InsightFlow
from prior work (LLMDebug, Context-RCA, RCLAgent) which use fixed pipelines.
"""

import json
import logging
from datetime import datetime
from sqlalchemy.orm import Session

from .hypothesis_generator import generate_hypotheses, Hypothesis
from .selector import select_next_test, get_test_rationale
from .evidence_store import (
    update_confidences,
    get_leading_hypothesis,
    format_hypotheses_snapshot,
    CONFIRMATION_THRESHOLD,
)
from .synthesis import synthesize
from ...models import Investigation

logger = logging.getLogger(__name__)

MAX_TESTS = 6          # budget: never run more than this many tests
MIN_TESTS = 4          # always run at least this many even if confident early


def run_investigation(
    db: Session,
    investigation: Investigation,
    context: dict = None,
) -> Investigation:
    """
    Runs the adaptive investigation loop for a given Investigation record.
    Updates the record in-place and commits to DB.

    Args:
        db: SQLAlchemy session
        investigation: Investigation ORM object (already committed with status='running')
        context: optional context dict (window_days, etc.)
    """
    if context is None:
        context = {"window_days": 7}

    metric_name = investigation.triggered_metric
    magnitude_pct = investigation.magnitude_pct or 0.0

    logger.info(f"[InvestigationEngine] Starting investigation #{investigation.id} "
                f"for metric '{metric_name}' ({magnitude_pct:+.1f}%)")

    # Step 1: Generate initial hypotheses (pass scenario hint for LLM prompt steering)
    hint = context.get("scenario_hint", "")
    hypotheses: list[Hypothesis] = generate_hypotheses(metric_name, magnitude_pct, hint=hint)
    tests_run: set[str] = set()
    steps_record: list[dict] = []
    budget = MAX_TESTS
    step_number = 0

    try:
        # Step 2: Adaptive loop
        while budget > 0:
            # Select next test
            next_test = select_next_test(hypotheses, tests_run, budget)
            if next_test is None:
                logger.info(f"  No more tests available. Ending loop.")
                break

            step_number += 1
            rationale = get_test_rationale(next_test, hypotheses)

            logger.info(f"  Step {step_number}: Running '{next_test.name}' — {rationale}")

            # Run the test
            result = next_test.run(db, context)
            tests_run.add(next_test.id)
            budget -= next_test.cost

            # Update hypothesis confidences
            hypotheses, eliminated = update_confidences(hypotheses, result)

            if eliminated:
                logger.info(f"  Eliminated hypotheses: {eliminated}")

            # Snapshot hypothesis state after this step
            hyp_snapshot = format_hypotheses_snapshot(hypotheses)

            # Build per-step intermediate assessment from hypothesis state (no extra LLM call)
            active_hyps = [h for h in hypotheses if h.active]
            if active_hyps:
                leading_h = max(active_hyps, key=lambda h: h.confidence)
                others = [h for h in active_hyps if h.id != leading_h.id]
                runner_up = max(others, key=lambda h: h.confidence) if others else None
                confidence_pct = round(leading_h.confidence * 100)
                strength = "strongly suggests" if confidence_pct >= 70 else "points toward" if confidence_pct >= 50 else "weakly favors"
                runner_note = f" '{runner_up.label}' is the next candidate at {round(runner_up.confidence * 100)}%." if runner_up else ""
                eliminated_note = f" Eliminated: {', '.join(eliminated)}." if eliminated else ""
                intermediate_conclusion = (
                    f"After {step_number} test(s), evidence {strength} '{leading_h.label}' "
                    f"({confidence_pct}% confidence). {leading_h.description}{runner_note}{eliminated_note}"
                )
            else:
                intermediate_conclusion = "All hypotheses eliminated — investigation may need additional data."

            # Record this step
            step_record = {
                "step_number": step_number,
                "test_id": result.test_id,
                "test_name": next_test.name,
                "test_rationale": rationale,
                "hypotheses_targeted": next_test.hypotheses_targeted,
                "result_summary": result.summary,
                "p_value": result.p_value,
                "effect_size": result.effect_size,
                "evidence": result.evidence,
                "hypotheses_after": hyp_snapshot,
                "eliminated": eliminated,
                "intermediate_conclusion": intermediate_conclusion,
            }
            steps_record.append(step_record)

            # Check for early conclusion (but only after MIN_TESTS)
            if step_number >= MIN_TESTS:
                leading, is_conclusive = get_leading_hypothesis(hypotheses)
                if is_conclusive:
                    logger.info(
                        f"  Conclusive: '{leading.label}' at {leading.confidence*100:.0f}% confidence. "
                        f"Stopping after {step_number} tests (budget had {budget} remaining)."
                    )
                    break

        # Step 3: Synthesis
        conclusion, recommendation = synthesize(
            triggered_metric=metric_name,
            magnitude_pct=magnitude_pct,
            hypotheses=hypotheses,
            steps_evidence=steps_record,
        )

        # Step 4: Persist
        investigation.steps_json = json.dumps(steps_record)
        investigation.conclusion = conclusion
        investigation.recommendation = recommendation
        investigation.tests_run = len(tests_run)
        investigation.tests_skipped = max(0, len(tests_run) - step_number)
        investigation.status = "completed"

        db.add(investigation)
        db.commit()
        db.refresh(investigation)

        logger.info(
            f"[InvestigationEngine] Investigation #{investigation.id} complete. "
            f"Ran {step_number} tests (max budget was {MAX_TESTS}). "
            f"Conclusion: {conclusion[:80]}..."
        )

    except Exception as e:
        logger.exception(f"[InvestigationEngine] Investigation #{investigation.id} failed: {e}")
        investigation.status = "failed"
        investigation.conclusion = f"Investigation failed: {str(e)}"
        db.add(investigation)
        db.commit()

    return investigation
