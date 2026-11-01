"""
Synthesis Agent — produces a plain-language conclusion from investigation evidence.

In production: calls Gemini LLM with the full evidence trail.
In mock mode (no GEMINI_API_KEY env var): generates a structured conclusion from
the confirmed hypothesis and the evidence collected at each step.
"""

import json
import logging
import os

from .hypothesis_generator import Hypothesis

logger = logging.getLogger(__name__)


def synthesize(
    triggered_metric: str,
    magnitude_pct: float,
    hypotheses: list[Hypothesis],
    steps_evidence: list[dict],
) -> tuple[str, str]:
    """
    Returns (conclusion, recommendation) strings.

    Tries Gemini first (requires GEMINI_API_KEY env var).
    Falls back to template-based synthesis if the LLM is unavailable or returns
    an unexpected response.

    Args:
        triggered_metric: name of the metric that anomalied
        magnitude_pct: % change from baseline
        hypotheses: final hypothesis list with confidences
        steps_evidence: list of step dicts from the investigation loop
    """
    try:
        result = _llm_synthesize(triggered_metric, magnitude_pct, hypotheses, steps_evidence)
        if result is not None:
            logger.info(f"[SynthesisAgent] LLM produced conclusion for '{triggered_metric}'")
            return result
    except Exception as e:
        logger.warning(
            f"[SynthesisAgent] LLM call failed — falling back to templates. Error: {e}"
        )

    logger.info("[SynthesisAgent] Using template-based synthesis (fallback).")
    return _fallback_synthesize(triggered_metric, magnitude_pct, hypotheses, steps_evidence)


# ── LLM path ─────────────────────────────────────────────────────────────────

def _llm_synthesize(
    triggered_metric: str,
    magnitude_pct: float,
    hypotheses: list[Hypothesis],
    steps_evidence: list[dict],
) -> tuple[str, str] | None:
    """
    Calls Gemini to produce a plain-English conclusion and recommendation.
    Returns None if GEMINI_API_KEY is not set.
    Raises on any other failure so the caller can fall back.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None

    import requests as _requests  # noqa: PLC0415

    active = [h for h in hypotheses if h.active]
    if not active:
        return None  # let fallback handle the "all eliminated" edge case

    leading = max(active, key=lambda h: h.confidence)

    # Slim down evidence to keep the prompt concise
    evidence_summary = [
        {
            "test": step.get("test_name"),
            "result": step.get("result_summary"),
            "p_value": step.get("p_value"),
            "effect_size": step.get("effect_size"),
        }
        for step in steps_evidence
    ]

    hyp_summary = [
        {
            "id": h.id,
            "label": h.label,
            "confidence": round(h.confidence, 3),
            "active": h.active,
        }
        for h in hypotheses
    ]

    direction = "dropped" if magnitude_pct < 0 else "increased"

    prompt = f"""You are a senior product analyst writing an investigation summary.

Metric '{triggered_metric}' {direction} {abs(magnitude_pct):.1f}%.

Leading hypothesis: {leading.label} ({leading.confidence * 100:.0f}% confidence)
Description: {leading.description}

All hypotheses after investigation:
{json.dumps(hyp_summary, indent=2)}

Tests run and evidence:
{json.dumps(evidence_summary, indent=2)}

Write a plain-English conclusion and an actionable recommendation for the product or engineering team.

Return ONLY a valid JSON object — no markdown fences, no commentary:
{{
  "conclusion": "2–4 sentences summarising what happened and why. Reference the metric name, the leading cause, and specific evidence where relevant. Be concrete.",
  "recommendation": "2–3 sentences of specific, actionable next steps for the team."
}}

Return only the JSON object, nothing else."""

    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-3.5-flash-lite:generateContent?key={api_key}"
    )
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    for attempt in range(3):
        resp = _requests.post(url, json=payload, timeout=30)
        if resp.status_code == 503:
            import time
            logger.warning(f"[SynthesisAgent] Gemini 503 (attempt {attempt+1}/3), retrying...")
            time.sleep(2 ** attempt)
            continue
        resp.raise_for_status()
        break
    else:
        raise RuntimeError("Gemini returned 503 after 3 attempts")
    raw = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()

    # Strip markdown code fences if the model included them
    if raw.startswith("```"):
        parts = raw.split("```")
        inner = parts[1]
        if inner.startswith("json"):
            inner = inner[4:]
        raw = inner.strip()

    data = json.loads(raw)

    conclusion = data.get("conclusion", "").strip()
    recommendation = data.get("recommendation", "").strip()

    if not conclusion or not recommendation:
        raise ValueError(
            f"LLM returned empty fields — conclusion={bool(conclusion)}, recommendation={bool(recommendation)}"
        )

    return conclusion, recommendation


# ── Fallback (original template) path ────────────────────────────────────────

def _fallback_synthesize(
    triggered_metric: str,
    magnitude_pct: float,
    hypotheses: list[Hypothesis],
    steps_evidence: list[dict],
) -> tuple[str, str]:
    """Original template-based synthesis.  Always returns a valid tuple."""
    active = [h for h in hypotheses if h.active]
    if not active:
        return (
            "Investigation inconclusive — all hypotheses were eliminated.",
            "Review data pipeline integrity and retry after the next data refresh.",
        )

    leading = max(active, key=lambda h: h.confidence)
    runner_up = (
        sorted(active, key=lambda h: h.confidence, reverse=True)[1]
        if len(active) > 1
        else None
    )

    direction = "dropped" if magnitude_pct < 0 else "increased"
    abs_pct = abs(magnitude_pct)
    tests_run = len(steps_evidence)

    if leading.id == "composition_shift":
        conclusion = (
            f"'{triggered_metric}' {direction} {abs_pct:.1f}% primarily due to a "
            f"**composition shift** in your user acquisition mix. "
            f"A lower-quality segment now makes up a larger share of new users, "
            f"dragging the aggregate metric down — but users within each segment "
            f"are behaving the same as before. "
            f"Confidence: {leading.confidence * 100:.0f}% after {tests_run} test(s)."
        )
        recommendation = (
            "Investigate your acquisition channels. The influx from one channel is "
            "bringing in users who convert/retain at a lower rate. Consider adding "
            "channel-level filters to your marketing dashboard and reviewing your "
            "Google Ads or Facebook Ads targeting criteria."
        )

    elif leading.id == "behavioral_change":
        worst_step = None
        for step in steps_evidence:
            if step.get("test_id") == "funnel_drop_test":
                worst_step = step.get("evidence", {}).get("worst_step")
                break

        conclusion = (
            f"'{triggered_metric}' {direction} {abs_pct:.1f}% due to a genuine "
            f"**within-group behavioral change** — users are completing fewer key actions, "
            f"independent of who they are. "
            f"{f'The sharpest drop is at the {repr(worst_step)} funnel step. ' if worst_step else ''}"
            f"Confidence: {leading.confidence * 100:.0f}% after {tests_run} test(s)."
        )
        recommendation = (
            f"Investigate recent product changes affecting the "
            f"{worst_step or 'core activation'} step. Check your changelog for "
            f"UI changes, new friction points, or backend regressions in the past 7 days."
        )

    elif leading.id == "feature_rollout":
        conclusion = (
            f"'{triggered_metric}' {direction} {abs_pct:.1f}% correlated with a "
            f"**feature rollout or A/B test**. Feature usage per user dropped, "
            f"suggesting a regression in a recently released feature. "
            f"Confidence: {leading.confidence * 100:.0f}% after {tests_run} test(s)."
        )
        recommendation = (
            "Review recent deployments and active A/B tests. Roll back or patch "
            "the most recent feature release and monitor the metric over the next 24 hours."
        )

    elif leading.id == "cohort_age_effect":
        conclusion = (
            f"'{triggered_metric}' {direction} {abs_pct:.1f}% likely due to a "
            f"**cohort age effect** — a recent signup spike introduced younger users "
            f"who naturally have lower retention at this stage of their lifecycle. "
            f"Confidence: {leading.confidence * 100:.0f}% after {tests_run} test(s)."
        )
        recommendation = (
            "This is a mathematical artifact of fast growth. Segment your retention "
            "dashboard by cohort week to confirm, and consider reporting cohort-normalized "
            "retention rather than aggregate retention."
        )

    elif leading.id == "data_artifact":
        conclusion = (
            f"'{triggered_metric}' {direction} {abs_pct:.1f}% — but this is likely a "
            f"**data pipeline issue**, not real user behavior. Total event volume dropped "
            f"significantly, suggesting an SDK tracking gap or ingestion failure. "
            f"Confidence: {leading.confidence * 100:.0f}% after {tests_run} test(s)."
        )
        recommendation = (
            "Do not act on this metric change until the data issue is resolved. "
            "Check your SDK integration, verify the ingestion pipeline is healthy, "
            "and compare event counts against your CDN or server-side logs."
        )

    else:
        conclusion = (
            f"'{triggered_metric}' {direction} {abs_pct:.1f}%. "
            f"Leading explanation: {leading.label} ({leading.confidence * 100:.0f}% confidence) "
            f"after {tests_run} tests. "
            f"{f'Alternative: {runner_up.label} ({runner_up.confidence * 100:.0f}%).' if runner_up else ''}"
        )
        recommendation = (
            f"Investigate further along the '{leading.id}' hypothesis. "
            "The investigation was inconclusive — consider expanding the time window or segment granularity."
        )

    return conclusion, recommendation
