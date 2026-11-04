"""
Hypothesis Generator — produces the initial candidate hypothesis set.

In production: calls Gemini LLM with the anomaly context.
In mock mode (no GEMINI_API_KEY env var): returns a fixed structured taxonomy of hypotheses
that covers the real causal space for product metric anomalies.

Each hypothesis has:
  - id: short slug
  - label: human-readable name
  - description: what causal mechanism it represents
  - confidence: prior probability (updated by evidence store later)
  - discriminating_tests: which tests can confirm/reject it
"""

import json
import logging
import os
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class Hypothesis:
    id: str
    label: str
    description: str
    confidence: float = 0.20   # will be updated by evidence
    active: bool = True        # set False when eliminated
    discriminating_tests: list[str] = field(default_factory=list)


# ── Valid test IDs the selector knows about ──────────────────────────────────
# Keep in sync with test_catalog.py

VALID_TEST_IDS = {
    "kitagawa_oaxaca",
    "segment_share_drift",
    "funnel_drop_test",
    "feature_adoption_test",
    "cohort_age_test",
    "event_volume_test",
}

# ── Taxonomy of hypotheses for product retention anomalies ──────────────────
# Used as the fallback when LLM is unavailable.

HYPOTHESIS_TAXONOMY = [
    Hypothesis(
        id="composition_shift",
        label="Composition Shift",
        description="The user mix changed — a lower-quality acquisition segment now makes up a larger share, dragging the aggregate metric down without any behavioral change.",
        confidence=0.25,
        discriminating_tests=["kitagawa_oaxaca", "segment_share_drift"],
    ),
    Hypothesis(
        id="behavioral_change",
        label="Within-Group Behavioral Change",
        description="Users in one or more segments are genuinely behaving differently (reaching fewer key features, churning earlier), independent of who they are.",
        confidence=0.25,
        discriminating_tests=["kitagawa_oaxaca", "funnel_drop_test", "feature_adoption_test"],
    ),
    Hypothesis(
        id="feature_rollout",
        label="Feature Rollout Correlation",
        description="A recent feature release or A/B test is correlated with the anomaly — either a regression or a negative interaction with a user segment.",
        confidence=0.20,
        discriminating_tests=["feature_adoption_test"],
    ),
    Hypothesis(
        id="cohort_age_effect",
        label="Cohort Age Effect",
        description="Newer user cohorts naturally have lower retention; if acquisition spiked recently, the metric drops as a mathematical artifact of younger cohort weight.",
        confidence=0.15,
        discriminating_tests=["cohort_age_test", "segment_share_drift"],
    ),
    Hypothesis(
        id="data_artifact",
        label="Data Pipeline Artifact",
        description="The anomaly is not real user behavior — it's a tracking gap, SDK drop, or data pipeline issue.",
        confidence=0.15,
        discriminating_tests=["event_volume_test"],
    ),
]


# ── Public entry point ───────────────────────────────────────────────────────

def generate_hypotheses(metric_name: str, magnitude_pct: float, hint: str = "") -> list[Hypothesis]:
    """
    Returns the initial hypothesis set for a given anomaly.

    hint: optional context string injected into the Gemini prompt so the LLM
          generates scenario-specific priors (e.g. "Google Ads acquisition surge").

    Tries Gemini first (requires GEMINI_API_KEY env var).
    Falls back to the hardcoded taxonomy if the LLM is unavailable or returns
    an unexpected response.
    """
    try:
        hypotheses = _llm_generate_hypotheses(metric_name, magnitude_pct, hint=hint)
        if hypotheses:
            logger.info(
                f"[HypothesisGenerator] LLM returned {len(hypotheses)} hypotheses "
                f"for '{metric_name}' ({magnitude_pct:+.1f}%)"
            )
            return hypotheses
    except Exception as e:
        logger.warning(
            f"[HypothesisGenerator] LLM call failed — falling back to taxonomy. Error: {e}"
        )

    logger.info("[HypothesisGenerator] Using hardcoded taxonomy (fallback).")
    return _fallback_generate_hypotheses(metric_name, magnitude_pct, hint=hint)


# ── LLM path ─────────────────────────────────────────────────────────────────

def _llm_generate_hypotheses(
    metric_name: str, magnitude_pct: float, hint: str = ""
) -> list[Hypothesis] | None:
    """
    Calls Gemini REST API to generate hypotheses.  Returns None if GEMINI_API_KEY
    is not set (treated as "not configured" rather than an error).
    Raises on any other failure so the caller can fall back.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None

    import requests as _requests  # noqa: PLC0415

    direction = "dropped" if magnitude_pct < 0 else "increased"
    valid_ids_str = json.dumps(sorted(VALID_TEST_IDS))

    # Build optional hint block — injected so Gemini generates scenario-aware priors
    hint_block = ""
    if hint:
        hint_block = f"\n\nAdditional context about this anomaly:\n{hint}\n\nUse this context to weight your hypothesis confidences accordingly."

    prompt = f"""You are a product analytics expert investigating a metric anomaly.

Metric: '{metric_name}'
Change: {direction} by {abs(magnitude_pct):.1f}%{hint_block}

Generate 4–6 causal hypotheses for this anomaly.

Return ONLY a valid JSON array — no markdown fences, no commentary.
Each element must have exactly these fields:
  "id"                   – MUST be one of exactly these five values: "composition_shift", "behavioral_change", "feature_rollout", "cohort_age_effect", "data_artifact". Map your hypothesis to the closest conceptual match; do NOT invent new IDs.
  "label"                – human-readable name, 2–5 words describing the scenario-specific manifestation
  "description"          – 1–2 sentence causal explanation tailored to this specific anomaly
  "confidence"           – float 0.0–1.0; all values must sum to exactly 1.0; weight according to the anomaly context
  "discriminating_tests" – list of test IDs drawn ONLY from: {valid_ids_str}

Example element:
{{
  "id": "composition_shift",
  "label": "Composition Shift",
  "description": "The user mix changed — a lower-quality acquisition segment now makes up a larger share, dragging the aggregate metric down.",
  "confidence": 0.25,
  "discriminating_tests": ["kitagawa_oaxaca", "segment_share_drift"]
}}

Return only the JSON array, nothing else."""

    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-3.5-flash-lite:generateContent?key={api_key}"
    )
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    for attempt in range(3):
        resp = _requests.post(url, json=payload, timeout=30)
        if resp.status_code == 503:
            import time
            logger.warning(f"[HypothesisGenerator] Gemini 503 (attempt {attempt+1}/3), retrying...")
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
        # parts[1] is the content between the first pair of fences
        inner = parts[1]
        if inner.startswith("json"):
            inner = inner[4:]
        raw = inner.strip()

    data = json.loads(raw)

    if not isinstance(data, list) or len(data) < 2:
        raise ValueError(
            f"LLM returned {type(data).__name__} with {len(data) if isinstance(data, list) else '?'} items; expected list with ≥2"
        )

    # Canonical IDs that match the test catalog's hypothesis_updates
    CANONICAL_IDS = {"composition_shift", "behavioral_change", "feature_rollout", "cohort_age_effect", "data_artifact"}
    _ID_KEYWORD_MAP = {
        "composition": "composition_shift", "segment": "composition_shift", "mix": "composition_shift",
        "behavioral": "behavioral_change", "behaviour": "behavioral_change", "churn": "behavioral_change",
        "engagement": "behavioral_change", "session": "behavioral_change", "funnel": "behavioral_change",
        "feature": "feature_rollout", "rollout": "feature_rollout", "release": "feature_rollout",
        "bug": "feature_rollout", "regression": "feature_rollout",
        "cohort": "cohort_age_effect", "age": "cohort_age_effect", "acquisition": "cohort_age_effect",
        "data": "data_artifact", "artifact": "data_artifact", "pipeline": "data_artifact",
        "tracking": "data_artifact", "instrumentation": "data_artifact",
    }

    def _canonicalize_id(raw_id: str) -> str:
        if raw_id in CANONICAL_IDS:
            return raw_id
        lower = raw_id.lower()
        for keyword, canonical in _ID_KEYWORD_MAP.items():
            if keyword in lower:
                logger.warning(f"[HypothesisGenerator] Remapping LLM id '{raw_id}' → '{canonical}'")
                return canonical
        logger.warning(f"[HypothesisGenerator] Unknown LLM id '{raw_id}'; defaulting to 'behavioral_change'")
        return "behavioral_change"

    hypotheses: list[Hypothesis] = []
    seen_ids: set[str] = set()
    for item in data:
        # Sanitise: keep only test IDs that actually exist in the catalog
        raw_tests = item.get("discriminating_tests") or []
        valid_tests = [t for t in raw_tests if t in VALID_TEST_IDS]
        if not valid_tests:
            logger.warning(
                f"[HypothesisGenerator] LLM hypothesis '{item.get('id')}' had no valid test IDs; defaulting to kitagawa_oaxaca"
            )
            valid_tests = ["kitagawa_oaxaca"]

        canonical_id = _canonicalize_id(str(item["id"]))
        if canonical_id in seen_ids:
            # Merge duplicate into existing by boosting its confidence; skip adding a new entry
            for h in hypotheses:
                if h.id == canonical_id:
                    h.confidence += float(item.get("confidence", 0.0))
            continue
        seen_ids.add(canonical_id)

        hypotheses.append(
            Hypothesis(
                id=canonical_id,
                label=str(item["label"]),
                description=str(item["description"]),
                confidence=float(item["confidence"]),
                active=True,
                discriminating_tests=valid_tests,
            )
        )

    # Re-normalise regardless of what the LLM returned
    _normalize(hypotheses)
    return hypotheses


# ── Fallback (original hardcoded) path ───────────────────────────────────────

def _fallback_generate_hypotheses(
    metric_name: str, magnitude_pct: float, hint: str = ""
) -> list[Hypothesis]:
    """
    Original magnitude-adjusted prior logic, now also hint-aware.
    Always returns a valid list.
    """
    hypotheses = [
        Hypothesis(
            id=h.id,
            label=h.label,
            description=h.description,
            confidence=h.confidence,
            active=h.active,
            discriminating_tests=list(h.discriminating_tests),
        )
        for h in HYPOTHESIS_TAXONOMY
    ]

    # Adjust priors slightly based on magnitude
    # Large drops (>15%) are more likely behavioral; small drops more likely composition/artifact
    if abs(magnitude_pct) > 15:
        _boost(hypotheses, "behavioral_change", 0.08)
        _reduce(hypotheses, "data_artifact", 0.05)
    else:
        _boost(hypotheses, "composition_shift", 0.05)
        _boost(hypotheses, "cohort_age_effect", 0.03)

    # Hint-based prior adjustment (fallback path when LLM unavailable)
    if hint:
        hint_lower = hint.lower()
        if "google ads" in hint_lower or "paid" in hint_lower or "acquisition surge" in hint_lower:
            _boost(hypotheses, "composition_shift", 0.12)
            _reduce(hypotheses, "data_artifact", 0.04)
        elif "ui" in hint_lower or "regression" in hint_lower or "feature" in hint_lower or "bug" in hint_lower:
            _boost(hypotheses, "behavioral_change", 0.12)
            _reduce(hypotheses, "cohort_age_effect", 0.04)
        elif "cohort" in hint_lower or "viral" in hint_lower or "signup spike" in hint_lower:
            _boost(hypotheses, "cohort_age_effect", 0.14)
            _reduce(hypotheses, "data_artifact", 0.04)
        elif "sdk" in hint_lower or "pipeline" in hint_lower or "tracking" in hint_lower:
            _boost(hypotheses, "data_artifact", 0.18)
            _reduce(hypotheses, "behavioral_change", 0.06)

    _normalize(hypotheses)
    return hypotheses


# ── Helpers ──────────────────────────────────────────────────────────────────

def _boost(hypotheses: list[Hypothesis], hid: str, delta: float):
    for h in hypotheses:
        if h.id == hid:
            h.confidence = min(0.95, h.confidence + delta)


def _reduce(hypotheses: list[Hypothesis], hid: str, delta: float):
    for h in hypotheses:
        if h.id == hid:
            h.confidence = max(0.02, h.confidence - delta)


def _normalize(hypotheses: list[Hypothesis]):
    total = sum(h.confidence for h in hypotheses)
    if total > 0:
        for h in hypotheses:
            h.confidence /= total
