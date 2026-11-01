"""
InsightFlow — Multi-Scenario Seed Data Generator

Run this instead of seed_data.py to load one of four distinct anomaly scenarios.
Each scenario causes a different root cause so the investigation engine and
Gemini take a different path every time.

Usage:
    python seed_scenarios.py 1   # Composition Shift       (Google Ads surge)
    python seed_scenarios.py 2   # Behavioral Change       (product regression)
    python seed_scenarios.py 3   # Cohort Age Effect       (viral signup spike)
    python seed_scenarios.py 4   # Data Pipeline Artifact  (SDK drop)

Scenario summary:
  1 — Google Ads campaign floods with low-retention users → mix shifts downward
  2 — A product change makes users drop off at the core feature step → within-group drop
  3 — Viral spike floods DB with brand-new users who haven't had time to return yet
  4 — SDK stops firing events for 4 days → retention looks collapsed but data is missing
"""

import os
import sys
import random
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database import engine, SessionLocal
from app.models import Base, Event

# ── Shared config ─────────────────────────────────────────────────────────────

COUNTRIES = ["India", "USA", "UK", "Germany", "Singapore"]
PLAN_TIERS = ["free", "free", "free", "pro"]   # 75% free


def random_user_id(prefix: str, day: int, i: int) -> str:
    return f"u_{prefix}_{day:03d}_{i:04d}"


def make_events_for_user(
    user_id: str,
    signup_dt: datetime,
    channel: str,
    activation_rate: float,
    retention_rate: float,
    feature_use_rate: float,
    days_remaining: int,
    skip_feature_events: bool = False,   # Scenario 2: suppress feature events
    event_dropout_rate: float = 0.0,     # Scenario 4: randomly drop session events
) -> list[Event]:
    events = []
    country = random.choice(COUNTRIES)
    plan = random.choice(PLAN_TIERS)

    # Signup
    events.append(Event(
        event_name="signup",
        user_id=user_id,
        timestamp=signup_dt,
        acquisition_channel=channel,
        country=country,
        plan_tier=plan,
    ))

    if random.random() < activation_rate:
        events.append(Event(
            event_name="onboarding_complete",
            user_id=user_id,
            timestamp=signup_dt + timedelta(minutes=random.randint(5, 45)),
            acquisition_channel=channel,
            country=country,
            plan_tier=plan,
        ))

        for _ in range(random.randint(2, 6)):
            events.append(Event(
                event_name="page_view",
                user_id=user_id,
                timestamp=signup_dt + timedelta(minutes=random.randint(1, 50)),
                acquisition_channel=channel,
                country=country,
                plan_tier=plan,
            ))

        events.append(Event(
            event_name="session_start",
            user_id=user_id,
            timestamp=signup_dt + timedelta(minutes=random.randint(1, 10)),
            acquisition_channel=channel,
            country=country,
            plan_tier=plan,
        ))

        if not skip_feature_events and random.random() < feature_use_rate:
            events.append(Event(
                event_name="feature_used",
                user_id=user_id,
                timestamp=signup_dt + timedelta(minutes=random.randint(15, 60)),
                acquisition_channel=channel,
                country=country,
                plan_tier=plan,
            ))

        for day_offset in range(1, days_remaining):
            if random.random() < retention_rate:
                # Scenario 4: drop some events entirely (simulates SDK outage)
                if random.random() < event_dropout_rate:
                    continue
                session_dt = signup_dt + timedelta(
                    days=day_offset, minutes=random.randint(0, 1439)
                )
                events.append(Event(
                    event_name="session_start",
                    user_id=user_id,
                    timestamp=session_dt,
                    acquisition_channel=channel,
                    country=country,
                    plan_tier=plan,
                ))
                if not skip_feature_events and random.random() < feature_use_rate:
                    events.append(Event(
                        event_name="feature_used",
                        user_id=user_id,
                        timestamp=session_dt + timedelta(minutes=random.randint(5, 30)),
                        acquisition_channel=channel,
                        country=country,
                        plan_tier=plan,
                    ))

    return events


def _clear_and_init(db):
    print("Creating tables and clearing existing data...")
    Base.metadata.create_all(bind=engine)
    db.query(Event).delete()
    db.commit()


def _bulk_insert(db, all_events):
    print(f"Inserting {len(all_events)} events...")
    chunk = 1000
    for i in range(0, len(all_events), chunk):
        db.bulk_save_objects(all_events[i:i + chunk])
        db.commit()
        print(f"  {min(i + chunk, len(all_events))}/{len(all_events)}")
    db.close()


# ── Scenario 1: Composition Shift ─────────────────────────────────────────────

def seed_scenario_1():
    """
    Google Ads runs a new campaign in the last 7 days, flooding signups with
    low-retention users.  Within-group behaviour is UNCHANGED.
    Root cause: composition shift (Kitagawa-Oaxaca confirms it).
    """
    random.seed(42)
    CHANNELS = {
        "organic":      dict(base=40, anomaly=42,  act=0.72, ret=0.55, feat=0.60),
        "google_ads":   dict(base=25, anomaly=95,  act=0.35, ret=0.22, feat=0.28),
        "facebook_ads": dict(base=20, anomaly=22,  act=0.58, ret=0.48, feat=0.50),
        "referral":     dict(base=15, anomaly=14,  act=0.85, ret=0.70, feat=0.78),
    }

    now = datetime.utcnow()
    anomaly_start = now - timedelta(days=7)
    baseline_start = now - timedelta(days=30)
    db = SessionLocal()
    _clear_and_init(db)
    all_events, total_users = [], 0

    print("Baseline period (days -30 to -7)...")
    cur = baseline_start
    while cur < anomaly_start:
        day_idx = (cur - baseline_start).days
        for ch, cfg in CHANNELS.items():
            for i in range(cfg["base"] + random.randint(-3, 3)):
                uid = random_user_id(ch[:3], day_idx, i)
                dt = cur + timedelta(hours=random.randint(0, 23), minutes=random.randint(0, 59))
                all_events.extend(make_events_for_user(
                    uid, dt, ch, cfg["act"], cfg["ret"], cfg["feat"],
                    days_remaining=(now - cur).days,
                ))
                total_users += 1
        cur += timedelta(days=1)

    print("Anomaly period (last 7 days) — Google Ads surge...")
    cur = anomaly_start
    while cur < now:
        day_idx = (cur - baseline_start).days
        for ch, cfg in CHANNELS.items():
            for i in range(cfg["anomaly"] + random.randint(-3, 3)):
                uid = random_user_id(ch[:3], day_idx, i) + "_a1"
                dt = cur + timedelta(hours=random.randint(0, 23), minutes=random.randint(0, 59))
                all_events.extend(make_events_for_user(
                    uid, dt, ch, cfg["act"], cfg["ret"], cfg["feat"],
                    days_remaining=(now - cur).days,
                ))
                total_users += 1
        cur += timedelta(days=1)

    _bulk_insert(db, all_events)
    print(f"\n✅ Scenario 1 loaded — {total_users} users, {len(all_events)} events")
    print("   Root cause: COMPOSITION SHIFT (Google Ads flood)")
    print("   Expected: Kitagawa-Oaxaca confirms composition, not behaviour")


# ── Scenario 2: Behavioral Change ─────────────────────────────────────────────

def seed_scenario_2():
    """
    All channels stay stable in volume and user mix, but in the last 7 days
    feature_used events drop ~75% across ALL segments — simulating a UI regression
    that blocks users from reaching the core feature.
    Root cause: within-group behavioral change (funnel drop analysis confirms it).
    """
    random.seed(99)
    CHANNELS = {
        "organic":      dict(base=40, act=0.72, ret=0.55, feat=0.60),
        "google_ads":   dict(base=25, act=0.55, ret=0.42, feat=0.50),
        "facebook_ads": dict(base=20, act=0.58, ret=0.48, feat=0.50),
        "referral":     dict(base=15, act=0.85, ret=0.70, feat=0.78),
    }

    now = datetime.utcnow()
    anomaly_start = now - timedelta(days=7)
    baseline_start = now - timedelta(days=30)
    db = SessionLocal()
    _clear_and_init(db)
    all_events, total_users = [], 0

    print("Baseline period (days -30 to -7) — normal behaviour...")
    cur = baseline_start
    while cur < anomaly_start:
        day_idx = (cur - baseline_start).days
        for ch, cfg in CHANNELS.items():
            for i in range(cfg["base"] + random.randint(-2, 2)):
                uid = random_user_id(ch[:3], day_idx, i)
                dt = cur + timedelta(hours=random.randint(0, 23), minutes=random.randint(0, 59))
                all_events.extend(make_events_for_user(
                    uid, dt, ch, cfg["act"], cfg["ret"], cfg["feat"],
                    days_remaining=(now - cur).days,
                ))
                total_users += 1
        cur += timedelta(days=1)

    print("Anomaly period (last 7 days) — UI regression, feature_used drops 75%...")
    cur = anomaly_start
    while cur < now:
        day_idx = (cur - baseline_start).days
        for ch, cfg in CHANNELS.items():
            for i in range(cfg["base"] + random.randint(-2, 2)):
                uid = random_user_id(ch[:3], day_idx, i) + "_a2"
                dt = cur + timedelta(hours=random.randint(0, 23), minutes=random.randint(0, 59))
                # Retention also drops because users who can't use the feature churn faster
                degraded_ret = cfg["ret"] * 0.45
                degraded_feat = cfg["feat"] * 0.15   # feature_used collapses
                all_events.extend(make_events_for_user(
                    uid, dt, ch, cfg["act"], degraded_ret, degraded_feat,
                    days_remaining=(now - cur).days,
                ))
                total_users += 1
        cur += timedelta(days=1)

    _bulk_insert(db, all_events)
    print(f"\n✅ Scenario 2 loaded — {total_users} users, {len(all_events)} events")
    print("   Root cause: BEHAVIORAL CHANGE (feature regression blocks core action)")
    print("   Expected: funnel_drop_test confirms drop at feature step across all segments")


# ── Scenario 3: Cohort Age Effect ─────────────────────────────────────────────

def seed_scenario_3():
    """
    A press mention causes a viral signup spike in the last 7 days.
    The new users are NORMAL quality — same retention rates as everyone else.
    But because they're so new, they haven't had time to return yet, so aggregate
    retention collapses mathematically.
    Root cause: cohort age effect (cohort_age_test confirms it).
    """
    random.seed(17)
    CHANNELS = {
        "organic":      dict(base=40, viral=180, act=0.72, ret=0.55, feat=0.60),
        "google_ads":   dict(base=25, viral=30,  act=0.55, ret=0.42, feat=0.48),
        "facebook_ads": dict(base=20, viral=25,  act=0.58, ret=0.48, feat=0.50),
        "referral":     dict(base=15, viral=90,  act=0.85, ret=0.70, feat=0.78),
    }

    now = datetime.utcnow()
    anomaly_start = now - timedelta(days=7)
    baseline_start = now - timedelta(days=30)
    db = SessionLocal()
    _clear_and_init(db)
    all_events, total_users = [], 0

    print("Baseline period (days -30 to -7) — steady state...")
    cur = baseline_start
    while cur < anomaly_start:
        day_idx = (cur - baseline_start).days
        for ch, cfg in CHANNELS.items():
            for i in range(cfg["base"] + random.randint(-3, 3)):
                uid = random_user_id(ch[:3], day_idx, i)
                dt = cur + timedelta(hours=random.randint(0, 23), minutes=random.randint(0, 59))
                all_events.extend(make_events_for_user(
                    uid, dt, ch, cfg["act"], cfg["ret"], cfg["feat"],
                    days_remaining=(now - cur).days,
                ))
                total_users += 1
        cur += timedelta(days=1)

    print("Anomaly period (last 7 days) — viral signup spike, same-quality users...")
    cur = anomaly_start
    while cur < now:
        day_idx = (cur - baseline_start).days
        for ch, cfg in CHANNELS.items():
            for i in range(cfg["viral"] + random.randint(-5, 5)):
                uid = random_user_id(ch[:3], day_idx, i) + "_a3"
                dt = cur + timedelta(hours=random.randint(0, 23), minutes=random.randint(0, 59))
                # Same quality users — but days_remaining is very small (0-6 days)
                # so even at 55% daily retention they barely have time to return
                all_events.extend(make_events_for_user(
                    uid, dt, ch, cfg["act"], cfg["ret"], cfg["feat"],
                    days_remaining=(now - cur).days,
                ))
                total_users += 1
        cur += timedelta(days=1)

    _bulk_insert(db, all_events)
    print(f"\n✅ Scenario 3 loaded — {total_users} users, {len(all_events)} events")
    print("   Root cause: COHORT AGE EFFECT (viral spike floods denominator with brand-new users)")
    print("   Expected: cohort_age_test shows normal per-cohort retention; aggregate drop is mathematical")


# ── Scenario 4: Data Pipeline Artifact ────────────────────────────────────────

def seed_scenario_4():
    """
    Normal user behaviour throughout, but for the last 4 days the client SDK
    stops firing 90% of its events (simulates a broken SDK deploy).  The outage
    hits every user active in that period, not just new signups.
    Signups still fire (server-side code path) so the user base looks fine,
    but activity events vanish — making retention look like it collapsed.
    Root cause: data pipeline artifact (event_volume_test detects the gap).
    """
    random.seed(7)
    CHANNELS = {
        "organic":      dict(base=40, act=0.72, ret=0.55, feat=0.60),
        "google_ads":   dict(base=25, act=0.55, ret=0.42, feat=0.50),
        "facebook_ads": dict(base=20, act=0.58, ret=0.48, feat=0.50),
        "referral":     dict(base=15, act=0.85, ret=0.70, feat=0.78),
    }

    now = datetime.utcnow()
    sdk_break_start = now - timedelta(days=4)   # SDK broke 4 days ago
    baseline_start = now - timedelta(days=30)
    db = SessionLocal()
    _clear_and_init(db)
    all_events, total_users = [], 0

    print("Full period (days -30 to now) — normal user behaviour...")
    cur = baseline_start
    while cur < now:
        day_idx = (cur - baseline_start).days
        suffix = "_a4" if cur >= sdk_break_start else ""
        for ch, cfg in CHANNELS.items():
            for i in range(cfg["base"] + random.randint(-3, 3)):
                uid = random_user_id(ch[:3], day_idx, i) + suffix
                dt = cur + timedelta(hours=random.randint(0, 23), minutes=random.randint(0, 59))
                all_events.extend(make_events_for_user(
                    uid, dt, ch, cfg["act"], cfg["ret"], cfg["feat"],
                    days_remaining=(now - cur).days,
                ))
                total_users += 1
        cur += timedelta(days=1)

    # SDK outage: every client-side event in the last 4 days is lost with 90%
    # probability, whoever the user is.  Signups are server-side and survive.
    print("Last 4 days — SDK broken, 90% of client-side events lost...")
    all_events = [
        e for e in all_events
        if e.event_name == "signup" or e.timestamp < sdk_break_start or random.random() >= 0.90
    ]

    _bulk_insert(db, all_events)
    print(f"\n✅ Scenario 4 loaded — {total_users} users, {len(all_events)} events")
    print("   Root cause: DATA PIPELINE ARTIFACT (SDK stopped firing session events)")
    print("   Expected: event_volume_test detects the sharp drop in non-signup events")


# ── Entry point ───────────────────────────────────────────────────────────────

SCENARIOS = {
    "1": (seed_scenario_1, "Composition Shift       — Google Ads surge with low-retention users"),
    "2": (seed_scenario_2, "Behavioral Change       — UI regression blocks core feature"),
    "3": (seed_scenario_3, "Cohort Age Effect       — Viral signup spike floods denominator"),
    "4": (seed_scenario_4, "Data Pipeline Artifact  — SDK stops firing session events"),
}

def run_scenario(scenario_id: int) -> dict:
    """
    Callable entry point for the FastAPI endpoint.
    Runs the requested scenario and returns stats dict.
    """
    key = str(scenario_id)
    if key not in SCENARIOS:
        raise ValueError(f"scenario_id must be 1–4, got {scenario_id}")

    fn, desc = SCENARIOS[key]
    print(f"\n{'='*60}")
    print(f"Loading Scenario {key}: {desc}")
    print(f"{'='*60}\n")
    fn()

    # Count what's now in the DB
    db = SessionLocal()
    try:
        from sqlalchemy import func
        event_count = db.query(func.count(Event.id)).scalar() or 0
        # Distinct users = distinct user_ids
        user_count = db.query(func.count(func.distinct(Event.user_id))).scalar() or 0
    finally:
        db.close()

    return {"users": user_count, "events": event_count}


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in SCENARIOS:
        print("Usage: python seed_scenarios.py <scenario_number>")
        print()
        print("Available scenarios:")
        for num, (_, desc) in SCENARIOS.items():
            print(f"  {num}  {desc}")
        sys.exit(1)

    fn, desc = SCENARIOS[sys.argv[1]]
    print(f"\n{'='*60}")
    print(f"Loading Scenario {sys.argv[1]}: {desc}")
    print(f"{'='*60}\n")
    fn()
