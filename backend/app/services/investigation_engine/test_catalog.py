"""
Test Catalog — defines every statistical test the investigation engine can run.

Each test entry specifies:
  - id: slug
  - name: human-readable
  - description: what it measures
  - hypotheses_targeted: which hypothesis IDs it can discriminate
  - cost: relative DB query cost (1 = cheap, 3 = expensive)
  - run(): executes the test against the DB and returns TestResult
"""

from dataclasses import dataclass, field
from typing import Any, Optional, Callable
import numpy as np
from scipy import stats


@dataclass
class TestResult:
    test_id: str
    summary: str
    p_value: Optional[float]
    effect_size: Optional[float]   # Cohen's d or relative difference
    evidence: dict[str, Any]       # raw numbers for the dashboard
    # Which hypotheses this result supports / refutes
    hypothesis_updates: dict[str, float]  # id -> confidence delta


@dataclass
class StatTest:
    id: str
    name: str
    description: str
    hypotheses_targeted: list[str]
    cost: int = 1
    _run_fn: Optional[Callable] = field(default=None, repr=False)

    def run(self, db, context: dict) -> TestResult:
        if self._run_fn:
            return self._run_fn(db, context)
        raise NotImplementedError(f"Test {self.id} has no run function assigned")


# ── Test implementations ────────────────────────────────────────────────────

def run_kitagawa_oaxaca(db, context: dict) -> TestResult:
    """
    Kitagawa-Oaxaca decomposition:
    Decomposes metric change into:
      (A) Composition effect: different segment mix
      (B) Rate effect: within-segment behavioral change

    This is the first test because it eliminates ~half the hypothesis space.

    The metric decomposed is age-matched retention (came back within 2 days),
    over users old enough to be fully observed, so younger cohorts can't
    masquerade as a within-segment behavior change.
    """
    from sqlalchemy import text
    from datetime import datetime, timedelta

    current_end = datetime.utcnow()
    current_start = current_end - timedelta(days=context.get("window_days", 7))
    baseline_start = current_start - timedelta(days=context.get("window_days", 7))
    baseline_end = current_start
    observable_until = current_end - timedelta(days=3)   # newer users not fully observed yet

    # Query: age-matched retention rate per acquisition_channel in each window
    q = text("""
        WITH signups AS (
            SELECT user_id, acquisition_channel, MIN(timestamp) AS signup_ts
            FROM events
            WHERE event_name = 'signup'
            GROUP BY user_id, acquisition_channel
        ),
        cohorts AS (
            SELECT s.acquisition_channel,
                   CASE WHEN s.signup_ts BETWEEN :current_start AND :observable_until THEN 'current'
                        WHEN s.signup_ts BETWEEN :baseline_start AND :baseline_end THEN 'baseline'
                   END AS cohort,
                   EXISTS (
                       SELECT 1 FROM events e
                       WHERE e.user_id = s.user_id
                         AND e.event_name = 'session_start'
                         AND julianday(e.timestamp) - julianday(s.signup_ts) BETWEEN 0.5 AND 2.0
                   ) AS returned
            FROM signups s
        )
        SELECT acquisition_channel AS channel,
               SUM(cohort = 'current') AS current_size,
               SUM(cohort = 'baseline') AS baseline_size,
               COALESCE(CAST(SUM(cohort = 'current' AND returned) AS FLOAT)
                        / NULLIF(SUM(cohort = 'current'), 0), 0) AS current_rate,
               COALESCE(CAST(SUM(cohort = 'baseline' AND returned) AS FLOAT)
                        / NULLIF(SUM(cohort = 'baseline'), 0), 0) AS baseline_rate
        FROM cohorts
        WHERE cohort IS NOT NULL
        GROUP BY acquisition_channel
    """)

    rows = db.execute(q, {
        "current_start": current_start,
        "observable_until": observable_until,
        "baseline_start": baseline_start,
        "baseline_end": baseline_end,
    }).fetchall()

    if not rows:
        return TestResult(
            test_id="kitagawa_oaxaca",
            summary="Insufficient data to run decomposition.",
            p_value=None, effect_size=None, evidence={},
            hypothesis_updates={}
        )

    # Compute Kitagawa-Oaxaca decomposition
    total_current = sum(r.current_size for r in rows)
    total_baseline = sum(r.baseline_size for r in rows)

    segments = []
    composition_effect = 0.0
    rate_effect = 0.0
    baseline_agg_rate = 0.0

    for r in rows:
        w_current = r.current_size / total_current if total_current > 0 else 0
        w_baseline = r.baseline_size / total_baseline if total_baseline > 0 else 0
        r_current = r.current_rate
        r_baseline = r.baseline_rate

        # Kitagawa decomposition:
        # Total change = composition effect + rate effect
        # Comp effect for segment i = (w_current_i - w_baseline_i) * r_baseline_i
        # Rate effect for segment i = w_current_i * (r_current_i - r_baseline_i)
        comp_i = (w_current - w_baseline) * r_baseline
        rate_i = w_current * (r_current - r_baseline)
        composition_effect += comp_i
        rate_effect += rate_i
        baseline_agg_rate += w_baseline * r_baseline

        segments.append({
            "channel": r.channel,
            "current_size": r.current_size,
            "baseline_size": r.baseline_size,
            "current_rate": round(r_current, 4),
            "baseline_rate": round(r_baseline, 4),
            "weight_current": round(w_current, 4),
            "weight_baseline": round(w_baseline, 4),
            "composition_contribution": round(comp_i, 4),
            "rate_contribution": round(rate_i, 4),
        })

    total_change = composition_effect + rate_effect

    # Only a component that pushes the metric DOWN can explain a drop.  A mix
    # shift toward better channels (positive composition effect) explains nothing.
    comp_down = max(0.0, -composition_effect)
    rate_down = max(0.0, -rate_effect)
    comp_share = comp_down / (comp_down + rate_down + 1e-9)
    rate_share = rate_down / (comp_down + rate_down + 1e-9)

    # Determine dominant driver and update hypothesis confidences
    hypothesis_updates = {}
    if comp_down + rate_down < 0.02:
        summary = (
            f"Neither the user mix nor within-segment behavior lowered age-matched retention "
            f"(composition {composition_effect*100:+.1f}pp, rate {rate_effect*100:+.1f}pp). "
            f"Users who are old enough to have returned did return as before."
        )
        hypothesis_updates["composition_shift"] = -0.15
        hypothesis_updates["behavioral_change"] = -0.15
    elif comp_share > 0.6:
        summary = (
            f"Composition effect dominates ({comp_share*100:.0f}% of change). "
            f"The user mix shifted — a lower-quality acquisition channel gained share."
        )
        hypothesis_updates["composition_shift"] = +0.35
        hypothesis_updates["behavioral_change"] = -0.20
        hypothesis_updates["data_artifact"] = -0.05
    elif rate_share > 0.6:
        summary = (
            f"Rate effect dominates ({rate_share*100:.0f}% of change). "
            f"Users are genuinely behaving differently — not just a different mix."
        )
        hypothesis_updates["behavioral_change"] = +0.35
        hypothesis_updates["composition_shift"] = -0.25
        hypothesis_updates["cohort_age_effect"] = -0.10
    else:
        summary = (
            f"Mixed signal: composition ({comp_share*100:.0f}%) and rate ({rate_share*100:.0f}%) "
            f"both contribute. Further tests needed."
        )
        hypothesis_updates["composition_shift"] = +0.10
        hypothesis_updates["behavioral_change"] = +0.10

    return TestResult(
        test_id="kitagawa_oaxaca",
        summary=summary,
        p_value=None,  # decomposition, not a hypothesis test
        effect_size=round(total_change, 4),
        evidence={
            "composition_effect": round(composition_effect, 4),
            "rate_effect": round(rate_effect, 4),
            "composition_share_pct": round(comp_share * 100, 1),
            "rate_share_pct": round(rate_share * 100, 1),
            "segments": segments,
        },
        hypothesis_updates=hypothesis_updates,
    )


def run_segment_share_drift(db, context: dict) -> TestResult:
    """Tests whether acquisition channel mix changed significantly (chi-squared test)."""
    from sqlalchemy import text
    from datetime import datetime, timedelta

    current_end = datetime.utcnow()
    current_start = current_end - timedelta(days=context.get("window_days", 7))
    baseline_start = current_start - timedelta(days=context.get("window_days", 7))
    baseline_end = current_start

    q = text("""
        SELECT acquisition_channel,
               SUM(CASE WHEN timestamp BETWEEN :current_start AND :current_end THEN 1 ELSE 0 END) AS current_count,
               SUM(CASE WHEN timestamp BETWEEN :baseline_start AND :baseline_end THEN 1 ELSE 0 END) AS baseline_count
        FROM events
        WHERE event_name = 'signup'
          AND acquisition_channel IS NOT NULL
        GROUP BY acquisition_channel
    """)
    rows = db.execute(q, {
        "current_start": current_start,
        "current_end": current_end,
        "baseline_start": baseline_start,
        "baseline_end": baseline_end,
    }).fetchall()

    if not rows or len(rows) < 2:
        return TestResult(
            test_id="segment_share_drift",
            summary="Not enough segments to test.",
            p_value=None, effect_size=None, evidence={},
            hypothesis_updates={}
        )

    current_counts = np.array([r.current_count for r in rows], dtype=float)
    baseline_counts = np.array([r.baseline_count for r in rows], dtype=float)

    # Chi-squared test of independence on the contingency table
    contingency = np.vstack([current_counts, baseline_counts])
    chi2, p_value, _, _ = stats.chi2_contingency(contingency)

    current_shares = current_counts / current_counts.sum()
    baseline_shares = baseline_counts / baseline_counts.sum()

    # Largest absolute share shift
    max_shift_idx = np.argmax(np.abs(current_shares - baseline_shares))
    max_channel = rows[max_shift_idx].acquisition_channel
    max_shift = current_shares[max_shift_idx] - baseline_shares[max_shift_idx]

    significant = p_value < 0.05
    summary = (
        f"Acquisition mix {'DID shift significantly' if significant else 'did NOT shift significantly'} "
        f"(χ²={chi2:.2f}, p={p_value:.3f}). "
        f"Largest change: {max_channel} {'+' if max_shift>0 else ''}{max_shift*100:.1f}pp share."
    )

    hypothesis_updates = {}
    if significant:
        hypothesis_updates["composition_shift"] = +0.20
        hypothesis_updates["cohort_age_effect"] = +0.05
        hypothesis_updates["behavioral_change"] = -0.10
    else:
        hypothesis_updates["composition_shift"] = -0.15
        hypothesis_updates["cohort_age_effect"] = -0.08

    return TestResult(
        test_id="segment_share_drift",
        summary=summary,
        p_value=round(p_value, 4),
        effect_size=round(float(max_shift), 4),
        evidence={
            "chi2": round(float(chi2), 3),
            "p_value": round(float(p_value), 4),
            "segments": [
                {
                    "channel": rows[i].acquisition_channel,
                    "current_share_pct": round(float(current_shares[i]) * 100, 1),
                    "baseline_share_pct": round(float(baseline_shares[i]) * 100, 1),
                    "shift_pp": round(float(current_shares[i] - baseline_shares[i]) * 100, 1),
                }
                for i in range(len(rows))
            ],
        },
        hypothesis_updates=hypothesis_updates,
    )


def run_funnel_drop_test(db, context: dict) -> TestResult:
    """Identifies which funnel step dropped most — signup → activation → core feature."""
    from sqlalchemy import text
    from datetime import datetime, timedelta

    current_end = datetime.utcnow()
    current_start = current_end - timedelta(days=context.get("window_days", 7))
    baseline_start = current_start - timedelta(days=context.get("window_days", 7))
    baseline_end = current_start

    funnel_steps = ["signup", "onboarding_complete", "feature_used", "session_start"]

    q = text("""
        SELECT event_name,
               SUM(CASE WHEN timestamp BETWEEN :current_start AND :current_end THEN 1 ELSE 0 END) AS current_count,
               SUM(CASE WHEN timestamp BETWEEN :baseline_start AND :baseline_end THEN 1 ELSE 0 END) AS baseline_count
        FROM events
        WHERE event_name IN ('signup', 'onboarding_complete', 'feature_used', 'session_start')
        GROUP BY event_name
    """)
    rows = db.execute(q, {
        "current_start": current_start,
        "current_end": current_end,
        "baseline_start": baseline_start,
        "baseline_end": baseline_end,
    }).fetchall()

    counts = {r.event_name: (r.current_count, r.baseline_count) for r in rows}

    funnel_data = []
    worst_step = None
    worst_drop = 0.0

    for step in funnel_steps:
        curr, base = counts.get(step, (0, 0))
        if base > 0:
            change_pct = (curr - base) / base * 100
            funnel_data.append({
                "step": step,
                "current_count": curr,
                "baseline_count": base,
                "change_pct": round(change_pct, 1),
            })
            if change_pct < worst_drop:
                worst_drop = change_pct
                worst_step = step

    if not funnel_data:
        return TestResult(
            test_id="funnel_drop_test",
            summary="Not enough funnel data.",
            p_value=None, effect_size=None, evidence={},
            hypothesis_updates={}
        )

    # Tracking-loss signature: server-side signups hold steady while every
    # client-side step falls by about the same amount.  A real behavioral change
    # hits one stage (e.g. the core feature) much harder than the others.
    changes = {f["step"]: f["change_pct"] for f in funnel_data}
    client_changes = [changes[s] for s in funnel_steps[1:] if s in changes]
    uniform_client_drop = (
        changes.get("signup", 0) > -10
        and len(client_changes) >= 2
        and max(client_changes) < -25
        and max(client_changes) - min(client_changes) < 20
    )

    if uniform_client_drop:
        summary = (
            f"Every client-side funnel step fell by a similar amount "
            f"({min(client_changes):.0f}% to {max(client_changes):.0f}%) while signups held steady. "
            f"A uniform drop across all tracked steps points to lost tracking, not a change at one stage."
        )
        hypothesis_updates = {
            "data_artifact": +0.30,
            "behavioral_change": -0.10,
            "feature_rollout": -0.05,
        }
    elif worst_step:
        summary = (
            f"Biggest funnel drop at step '{worst_step}' ({worst_drop:.1f}% decline). "
            f"This points to a behavioral change at that stage."
        )
        hypothesis_updates = {
            "behavioral_change": +0.25,
            "feature_rollout": +0.10,
            "composition_shift": -0.10,
        }
    else:
        summary = "Funnel steps are stable — no single step accounts for the metric drop."
        hypothesis_updates = {
            "behavioral_change": -0.15,
            "data_artifact": +0.10,
        }

    return TestResult(
        test_id="funnel_drop_test",
        summary=summary,
        p_value=None,
        effect_size=round(worst_drop / 100, 4) if worst_step else 0.0,
        evidence={"funnel": funnel_data, "worst_step": worst_step},
        hypothesis_updates=hypothesis_updates,
    )


def run_feature_adoption_test(db, context: dict) -> TestResult:
    """Checks if a specific feature's usage dropped, suggesting a rollout issue."""
    from sqlalchemy import text
    from datetime import datetime, timedelta

    current_end = datetime.utcnow()
    current_start = current_end - timedelta(days=context.get("window_days", 7))
    baseline_start = current_start - timedelta(days=context.get("window_days", 7))
    baseline_end = current_start

    q = text("""
        SELECT
            SUM(CASE WHEN timestamp BETWEEN :current_start AND :current_end THEN 1 ELSE 0 END) AS current_feature_events,
            SUM(CASE WHEN timestamp BETWEEN :baseline_start AND :baseline_end THEN 1 ELSE 0 END) AS baseline_feature_events,
            COUNT(DISTINCT CASE WHEN timestamp BETWEEN :current_start AND :current_end THEN user_id END) AS current_users,
            COUNT(DISTINCT CASE WHEN timestamp BETWEEN :baseline_start AND :baseline_end THEN user_id END) AS baseline_users
        FROM events
        WHERE event_name = 'feature_used'
    """)
    row = db.execute(q, {
        "current_start": current_start,
        "current_end": current_end,
        "baseline_start": baseline_start,
        "baseline_end": baseline_end,
    }).fetchone()

    if not row or row.baseline_users == 0:
        return TestResult(
            test_id="feature_adoption_test",
            summary="Insufficient feature usage data.",
            p_value=None, effect_size=None, evidence={},
            hypothesis_updates={}
        )

    current_rate = row.current_feature_events / max(row.current_users, 1)
    baseline_rate = row.baseline_feature_events / max(row.baseline_users, 1)
    change_pct = (current_rate - baseline_rate) / baseline_rate * 100

    significant_drop = change_pct < -10

    summary = (
        f"Feature usage per user {'dropped {:.1f}%'.format(change_pct) if significant_drop else 'is stable ({:.1f}% change)'.format(change_pct)}. "
        f"{'Suggests a rollout issue or UX regression.' if significant_drop else 'Feature adoption is not the driver.'}"
    )

    hypothesis_updates = {}
    if significant_drop:
        hypothesis_updates["feature_rollout"] = +0.30
        hypothesis_updates["behavioral_change"] = +0.15
        hypothesis_updates["composition_shift"] = -0.10
    else:
        hypothesis_updates["feature_rollout"] = -0.20

    return TestResult(
        test_id="feature_adoption_test",
        summary=summary,
        p_value=None,
        effect_size=round(change_pct / 100, 4),
        evidence={
            "current_events_per_user": round(current_rate, 2),
            "baseline_events_per_user": round(baseline_rate, 2),
            "change_pct": round(change_pct, 1),
        },
        hypothesis_updates=hypothesis_updates,
    )


def run_cohort_age_test(db, context: dict) -> TestResult:
    """
    Checks whether the drop is just younger cohorts that haven't had time to return.

    Compares age-matched retention: among users old enough to be fully observed
    (signed up 3+ days ago), what share came back within 2 days of signing up?
    If that is unchanged while the aggregate metric fell, the drop is a
    mathematical effect of cohort age.  If it also fell, users really are
    returning less, so cohort age is ruled out.
    """
    from sqlalchemy import text
    from datetime import datetime, timedelta

    current_end = datetime.utcnow()
    current_start = current_end - timedelta(days=context.get("window_days", 7))
    baseline_start = current_start - timedelta(days=context.get("window_days", 7))
    baseline_end = current_start
    observable_until = current_end - timedelta(days=3)   # newer users not fully observed yet

    q = text("""
        WITH signups AS (
            SELECT user_id, MIN(timestamp) AS signup_ts
            FROM events
            WHERE event_name = 'signup'
            GROUP BY user_id
        ),
        cohorts AS (
            SELECT user_id, signup_ts,
                   CASE WHEN signup_ts BETWEEN :current_start AND :observable_until THEN 'current'
                        WHEN signup_ts BETWEEN :baseline_start AND :baseline_end THEN 'baseline'
                   END AS cohort
            FROM signups
        )
        SELECT c.cohort,
               COUNT(*) AS users,
               SUM(CASE WHEN EXISTS (
                       SELECT 1 FROM events e
                       WHERE e.user_id = c.user_id
                         AND e.event_name = 'session_start'
                         AND julianday(e.timestamp) - julianday(c.signup_ts) BETWEEN 0.5 AND 2.0
                   ) THEN 1 ELSE 0 END) AS returned
        FROM cohorts c
        WHERE c.cohort IS NOT NULL
        GROUP BY c.cohort
    """)
    rows = db.execute(q, {
        "current_start": current_start,
        "observable_until": observable_until,
        "baseline_start": baseline_start,
        "baseline_end": baseline_end,
    }).fetchall()
    by_cohort = {r.cohort: (r.users, r.returned) for r in rows}

    if "current" not in by_cohort or "baseline" not in by_cohort:
        return TestResult(
            test_id="cohort_age_test",
            summary="Not enough fully-observed cohorts to compare.",
            p_value=None, effect_size=None, evidence={},
            hypothesis_updates={}
        )

    cur_users, cur_ret = by_cohort["current"]
    base_users, base_ret = by_cohort["baseline"]
    cur_rate = cur_ret / max(cur_users, 1)
    base_rate = base_ret / max(base_users, 1)

    # One-sided two-proportion z-test: did age-matched retention fall?
    pooled = (cur_ret + base_ret) / max(cur_users + base_users, 1)
    se = np.sqrt(pooled * (1 - pooled) * (1 / max(cur_users, 1) + 1 / max(base_users, 1)))
    z = (cur_rate - base_rate) / se if se > 0 else 0.0
    p_value = float(stats.norm.cdf(z))
    relative_change = (cur_rate - base_rate) / base_rate if base_rate > 0 else 0.0

    really_dropped = p_value < 0.05 and relative_change < -0.10

    if really_dropped:
        summary = (
            f"Age-matched 2-day return rate fell from {base_rate*100:.1f}% to {cur_rate*100:.1f}% "
            f"(p={p_value:.3f}). Even users old enough to have returned are returning less — "
            f"this is not just a cohort age effect."
        )
        hypothesis_updates = {"cohort_age_effect": -0.30}
    else:
        summary = (
            f"Age-matched 2-day return rate did not fall ({base_rate*100:.1f}% → {cur_rate*100:.1f}%, "
            f"p={p_value:.3f}). Users return as often as before once they are old enough — the aggregate "
            f"drop comes from recent cohorts being too young to have returned yet."
        )
        hypothesis_updates = {
            "cohort_age_effect": +0.45,
            "behavioral_change": -0.20,
            "composition_shift": -0.20,
            "data_artifact": -0.05,
        }

    return TestResult(
        test_id="cohort_age_test",
        summary=summary,
        p_value=round(p_value, 4),
        effect_size=round(relative_change, 4),
        evidence={
            "current_cohort_users": cur_users,
            "baseline_cohort_users": base_users,
            "current_return_rate": round(cur_rate, 4),
            "baseline_return_rate": round(base_rate, 4),
        },
        hypothesis_updates=hypothesis_updates,
    )


def run_event_volume_test(db, context: dict) -> TestResult:
    """
    Checks whether client-side event volume collapsed (data pipeline / SDK issue).

    Compares each recent day's client-side event count (everything except the
    server-side 'signup' event) with the baseline daily mean.  Looking day by
    day catches an outage that started partway through the window, which a
    single 7-day total would dilute.
    """
    from sqlalchemy import text
    from datetime import datetime, timedelta

    current_end = datetime.utcnow()
    current_start = current_end - timedelta(days=context.get("window_days", 7))
    baseline_start = current_start - timedelta(days=context.get("window_days", 7))

    # Bucket by whole days counted back from now, so the newest bucket is a full 24h
    q = text("""
        SELECT CAST((julianday(:now) - julianday(timestamp)) AS INTEGER) AS days_ago,
               COUNT(*) AS n
        FROM events
        WHERE event_name != 'signup'
          AND timestamp BETWEEN :baseline_start AND :now
        GROUP BY days_ago
    """)
    rows = db.execute(q, {"now": current_end, "baseline_start": baseline_start}).fetchall()
    by_day = {r.days_ago: r.n for r in rows}

    window = context.get("window_days", 7)
    baseline_daily = [by_day.get(d, 0) for d in range(window, 2 * window)]
    current_daily = [by_day.get(d, 0) for d in range(0, window)]
    baseline_mean = float(np.mean(baseline_daily)) if baseline_daily else 0.0

    if baseline_mean == 0:
        return TestResult(
            test_id="event_volume_test",
            summary="No baseline event volume to compare against.",
            p_value=None, effect_size=None, evidence={},
            hypothesis_updates={}
        )

    day_ratios = [n / baseline_mean for n in current_daily]
    collapsed_days = [d for d, r in enumerate(day_ratios) if r < 0.5]
    worst_ratio = min(day_ratios)

    # One collapsed day can be noise; an outage shows up as several in a row
    outage = len(collapsed_days) >= 2

    if outage:
        summary = (
            f"Client-side event volume collapsed on {len(collapsed_days)} of the last {window} days "
            f"(lowest day: {worst_ratio*100:.0f}% of the baseline daily average) while signups kept arriving. "
            f"This is the signature of a tracking / SDK outage, not of user behavior."
        )
        hypothesis_updates = {
            "data_artifact": +0.60,
            "behavioral_change": -0.30,
            "composition_shift": -0.15,
            "feature_rollout": -0.10,
        }
    else:
        summary = (
            f"Client-side event volume is healthy (lowest recent day: {worst_ratio*100:.0f}% of the baseline "
            f"daily average). The tracking pipeline is working."
        )
        hypothesis_updates = {"data_artifact": -0.25}

    return TestResult(
        test_id="event_volume_test",
        summary=summary,
        p_value=None,
        effect_size=round(worst_ratio - 1.0, 4),
        evidence={
            "baseline_daily_mean": round(baseline_mean, 1),
            "current_daily": current_daily[::-1],   # oldest → newest
            "collapsed_days": len(collapsed_days),
            "worst_day_ratio": round(worst_ratio, 3),
        },
        hypothesis_updates=hypothesis_updates,
    )


# ── Catalog registry ────────────────────────────────────────────────────────

CATALOG: dict[str, StatTest] = {
    t.id: t for t in [
        StatTest(
            id="kitagawa_oaxaca",
            name="Kitagawa-Oaxaca Decomposition",
            description="Decomposes metric change into composition shift vs within-segment rate change. Eliminates ~half the hypothesis space in one query.",
            hypotheses_targeted=["composition_shift", "behavioral_change"],
            cost=1,
            _run_fn=run_kitagawa_oaxaca,
        ),
        StatTest(
            id="segment_share_drift",
            name="Acquisition Mix Chi-Squared Test",
            description="Tests whether the share of users from each acquisition channel changed significantly.",
            hypotheses_targeted=["composition_shift", "cohort_age_effect"],
            cost=1,
            _run_fn=run_segment_share_drift,
        ),
        StatTest(
            id="funnel_drop_test",
            name="Funnel Step Drop Analysis",
            description="Identifies which funnel stage (signup → activation → core feature) declined most, or whether all tracked stages fell uniformly (tracking loss).",
            hypotheses_targeted=["behavioral_change", "feature_rollout", "data_artifact"],
            cost=1,
            _run_fn=run_funnel_drop_test,
        ),
        StatTest(
            id="feature_adoption_test",
            name="Feature Adoption Rate Test",
            description="Measures whether feature usage per user dropped, indicating a rollout regression.",
            hypotheses_targeted=["feature_rollout", "behavioral_change"],
            cost=1,
            _run_fn=run_feature_adoption_test,
        ),
        StatTest(
            id="cohort_age_test",
            name="Age-Matched Retention Test",
            description="Compares retention of fully-observed cohorts to check whether the drop is only younger cohorts that haven't had time to return.",
            hypotheses_targeted=["cohort_age_effect", "composition_shift", "behavioral_change"],
            cost=1,
            _run_fn=run_cohort_age_test,
        ),
        StatTest(
            id="event_volume_test",
            name="Event Volume Integrity Check",
            description="Checks day by day whether client-side event volume collapsed (data pipeline / SDK tracking gap).",
            hypotheses_targeted=["data_artifact"],
            cost=1,
            _run_fn=run_event_volume_test,
        ),
    ]
}
