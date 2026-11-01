"""
Evidence Store — tracks hypothesis confidence throughout an investigation.

After each test result comes in, updates hypothesis confidences using:
  new_confidence = clamp(old_confidence + delta, 0.02, 0.98)
  then renormalize across active hypotheses

A hypothesis is "eliminated" when its confidence drops below ELIMINATION_THRESHOLD.
A hypothesis is "confirmed" when its confidence exceeds CONFIRMATION_THRESHOLD
  AND all others have been suppressed enough.
"""

from copy import deepcopy
from .hypothesis_generator import Hypothesis
from .test_catalog import TestResult

ELIMINATION_THRESHOLD = 0.05   # < 5% confidence → eliminate
CONFIRMATION_THRESHOLD = 0.70  # > 70% confidence → strong candidate for conclusion


def update_confidences(
    hypotheses: list[Hypothesis],
    result: TestResult,
) -> tuple[list[Hypothesis], list[str]]:
    """
    Applies a test result's hypothesis_updates to the hypothesis list.

    Returns:
      (updated_hypotheses, eliminated_ids)
    """
    updated = deepcopy(hypotheses)
    eliminated = []

    # Apply deltas
    update_map = result.hypothesis_updates
    for h in updated:
        if not h.active:
            continue
        delta = update_map.get(h.id, 0.0)
        h.confidence = max(0.01, min(0.99, h.confidence + delta))

    # Renormalize over active hypotheses
    active = [h for h in updated if h.active]
    total = sum(h.confidence for h in active)
    if total > 0:
        for h in active:
            h.confidence /= total

    # Eliminate low-confidence hypotheses
    for h in updated:
        if h.active and h.confidence < ELIMINATION_THRESHOLD:
            h.active = False
            eliminated.append(h.id)

    return updated, eliminated


def get_leading_hypothesis(hypotheses: list[Hypothesis]) -> tuple[Hypothesis | None, bool]:
    """
    Returns the leading hypothesis and whether it's confident enough to conclude.

    Returns:
      (leading_hypothesis, is_conclusive)
    """
    active = [h for h in hypotheses if h.active]
    if not active:
        return None, False

    leading = max(active, key=lambda h: h.confidence)
    is_conclusive = leading.confidence >= CONFIRMATION_THRESHOLD

    return leading, is_conclusive


def format_hypotheses_snapshot(hypotheses: list[Hypothesis]) -> list[dict]:
    """Serializable snapshot of hypothesis state."""
    return [
        {
            "id": h.id,
            "label": h.label,
            "description": h.description,
            "confidence": round(h.confidence, 4),
            "active": h.active,
        }
        for h in sorted(hypotheses, key=lambda h: h.confidence, reverse=True)
    ]
