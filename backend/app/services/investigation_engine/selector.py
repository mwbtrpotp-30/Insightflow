"""
Greedy Information-Gain Selector — the core novelty of InsightFlow.

Given:
  - A set of active hypotheses with current confidence scores
  - A set of tests already run (to avoid repeats)
  - The full test catalog

Selects the next test that maximally discriminates among remaining hypotheses.

Scoring function:
  score(test t) = Σ_{h ∈ active_hypotheses ∩ t.hypotheses_targeted} confidence(h)
                  / cost(t)

Intuition: a test that targets many high-confidence hypotheses scores highest.
Dividing by cost ensures we prefer cheap discriminating tests over expensive ones.

This is the "greedy" approximation to the full MDP (which would maximize
expected information gain over the entire remaining investigation trajectory).
"""

import math
from typing import Optional
from .hypothesis_generator import Hypothesis
from .test_catalog import CATALOG, StatTest


def select_next_test(
    hypotheses: list[Hypothesis],
    tests_already_run: set[str],
    budget_remaining: int,
) -> Optional[StatTest]:
    """
    Returns the highest-scoring untested test, or None if no tests remain
    or budget is exhausted.

    Args:
        hypotheses: current hypothesis list (only active ones contribute to score)
        tests_already_run: set of test IDs already executed this investigation
        budget_remaining: max number of additional tests allowed
    """
    if budget_remaining <= 0:
        return None

    active_hypotheses = [h for h in hypotheses if h.active]
    if not active_hypotheses:
        return None

    # Build a confidence lookup for fast scoring
    confidence = {h.id: h.confidence for h in active_hypotheses}

    best_test: Optional[StatTest] = None
    best_score: float = -1.0
    scored_tests = []

    for test_id, test in CATALOG.items():
        if test_id in tests_already_run:
            continue
        if test.cost > budget_remaining:
            continue

        # Score = sum of confidence of active hypotheses this test targets, / cost
        targeted_confidence = sum(
            confidence.get(hid, 0.0)
            for hid in test.hypotheses_targeted
        )
        score = targeted_confidence / test.cost

        scored_tests.append((test_id, score, targeted_confidence))

        if score > best_score:
            best_score = score
            best_test = test

    return best_test


def get_test_rationale(
    test: StatTest,
    hypotheses: list[Hypothesis],
) -> str:
    """
    Generates a human-readable explanation of why the selector chose this test.
    """
    active = {h.id: h for h in hypotheses if h.active}
    targeted = [active[hid] for hid in test.hypotheses_targeted if hid in active]

    if not targeted:
        return f"Running {test.name} to check remaining open questions."

    top = sorted(targeted, key=lambda h: h.confidence, reverse=True)
    top_labels = [f"'{h.label}' ({h.confidence*100:.0f}%)'" for h in top[:2]]

    return (
        f"Selected because it targets {' and '.join(top_labels)} — "
        f"the highest-confidence unresolved hypotheses. "
        f"Cost: {test.cost} query unit(s)."
    )
