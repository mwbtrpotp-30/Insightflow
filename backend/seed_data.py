"""
Seed Data Generator for InsightFlow Demo.

Creates a realistic 30-day event history with an injected anomaly:
  - Days 1-23 (baseline): normal retention across all acquisition channels
  - Days 24-30 (anomaly window): Google Ads channel surges in volume but
    brings lower-quality users with much lower activation rate.
    This is a COMPOSITION SHIFT anomaly — the aggregate retention drops
    not because users behave differently, but because a lower-quality
    segment now dominates the mix.

This is exactly the scenario our Kitagawa-Oaxaca decomposition detects first.
"""

import os
import sys
import random
from datetime import datetime, timedelta

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database import engine, SessionLocal
from app.models import Base, Event

random.seed(42)

# ── Configuration ──────────────────────────────────────────────────────────────

CHANNELS = {
    "organic": {
        "baseline_daily_signups": 40,
        "anomaly_daily_signups": 42,          # stable
        "activation_rate": 0.72,              # % who complete onboarding
        "retention_rate": 0.55,              # % who return next day
        "feature_use_rate": 0.60,
    },
    "google_ads": {
        "baseline_daily_signups": 25,
        "anomaly_daily_signups": 95,          # ← BIG SURGE: new campaign
        "activation_rate": 0.35,              # ← LOW quality: bounce after signup
        "retention_rate": 0.22,              # ← LOW retention
        "feature_use_rate": 0.28,
    },
    "facebook_ads": {
        "baseline_daily_signups": 20,
        "anomaly_daily_signups": 22,          # stable
        "activation_rate": 0.58,
        "retention_rate": 0.48,
        "feature_use_rate": 0.50,
    },
    "referral": {
        "baseline_daily_signups": 15,
        "anomaly_daily_signups": 14,          # slightly declining
        "activation_rate": 0.85,              # highest quality
        "retention_rate": 0.70,
        "feature_use_rate": 0.78,
    },
}

COUNTRIES = ["India", "USA", "UK", "Germany", "Singapore"]
PLAN_TIERS = ["free", "free", "free", "pro"]   # 75% free


def random_user_id(channel: str, day: int, i: int) -> str:
    return f"u_{channel[:3]}_{day:03d}_{i:04d}"


def make_events_for_user(
    user_id: str,
    signup_dt: datetime,
    channel: str,
    activation_rate: float,
    retention_rate: float,
    feature_use_rate: float,
    days_remaining: int,
) -> list[Event]:
    events = []
    country = random.choice(COUNTRIES)
    plan = random.choice(PLAN_TIERS)

    # Signup event
    events.append(Event(
        event_name="signup",
        user_id=user_id,
        timestamp=signup_dt,
        acquisition_channel=channel,
        country=country,
        plan_tier=plan,
    ))

    # Onboarding (activation)
    if random.random() < activation_rate:
        events.append(Event(
            event_name="onboarding_complete",
            user_id=user_id,
            timestamp=signup_dt + timedelta(minutes=random.randint(5, 45)),
            acquisition_channel=channel,
            country=country,
            plan_tier=plan,
        ))

        # Page views during signup session
        for _ in range(random.randint(2, 6)):
            events.append(Event(
                event_name="page_view",
                user_id=user_id,
                timestamp=signup_dt + timedelta(minutes=random.randint(1, 50)),
                acquisition_channel=channel,
                country=country,
                plan_tier=plan,
            ))

        # Session start on signup day
        events.append(Event(
            event_name="session_start",
            user_id=user_id,
            timestamp=signup_dt + timedelta(minutes=random.randint(1, 10)),
            acquisition_channel=channel,
            country=country,
            plan_tier=plan,
        ))

        # Feature usage on signup day
        if random.random() < feature_use_rate:
            events.append(Event(
                event_name="feature_used",
                user_id=user_id,
                timestamp=signup_dt + timedelta(minutes=random.randint(15, 60)),
                acquisition_channel=channel,
                country=country,
                plan_tier=plan,
            ))

        # Subsequent days: each day user returns with retention_rate probability
        for day_offset in range(1, days_remaining):
            if random.random() < retention_rate:
                session_dt = signup_dt + timedelta(days=day_offset, minutes=random.randint(0, 1439))
                events.append(Event(
                    event_name="session_start",
                    user_id=user_id,
                    timestamp=session_dt,
                    acquisition_channel=channel,
                    country=country,
                    plan_tier=plan,
                ))
                if random.random() < feature_use_rate:
                    events.append(Event(
                        event_name="feature_used",
                        user_id=user_id,
                        timestamp=session_dt + timedelta(minutes=random.randint(5, 30)),
                        acquisition_channel=channel,
                        country=country,
                        plan_tier=plan,
                    ))

    return events


def seed(clear_existing: bool = True):
    print("Creating database tables...")
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()

    if clear_existing:
        print("Clearing existing data...")
        db.query(Event).delete()
        db.commit()

    now = datetime.utcnow()
    anomaly_start = now - timedelta(days=7)
    baseline_start = now - timedelta(days=30)

    all_events = []
    total_users = 0

    print("Generating baseline period (days -30 to -7)...")
    current = baseline_start
    while current < anomaly_start:
        day_offset = (current - baseline_start).days
        for channel, cfg in CHANNELS.items():
            n_signups = cfg["baseline_daily_signups"] + random.randint(-3, 3)
            days_remaining = (now - current).days

            for i in range(n_signups):
                user_id = random_user_id(channel, day_offset, i)
                signup_dt = current + timedelta(
                    hours=random.randint(0, 23),
                    minutes=random.randint(0, 59),
                )
                events = make_events_for_user(
                    user_id=user_id,
                    signup_dt=signup_dt,
                    channel=channel,
                    activation_rate=cfg["activation_rate"],
                    retention_rate=cfg["retention_rate"],
                    feature_use_rate=cfg["feature_use_rate"],
                    days_remaining=days_remaining,
                )
                all_events.extend(events)
                total_users += 1

        current += timedelta(days=1)

    print(f"Generating anomaly period (last 7 days) — Google Ads surge...")
    current = anomaly_start
    while current < now:
        day_offset = (current - baseline_start).days
        for channel, cfg in CHANNELS.items():
            n_signups = cfg["anomaly_daily_signups"] + random.randint(-3, 3)
            days_remaining = (now - current).days

            for i in range(n_signups):
                user_id = random_user_id(channel, day_offset, i) + "_anomaly"
                signup_dt = current + timedelta(
                    hours=random.randint(0, 23),
                    minutes=random.randint(0, 59),
                )
                events = make_events_for_user(
                    user_id=user_id,
                    signup_dt=signup_dt,
                    channel=channel,
                    activation_rate=cfg["activation_rate"],
                    retention_rate=cfg["retention_rate"],
                    feature_use_rate=cfg["feature_use_rate"],
                    days_remaining=days_remaining,
                )
                all_events.extend(events)
                total_users += 1

        current += timedelta(days=1)

    print(f"Inserting {len(all_events)} events for {total_users} users...")
    # Batch insert in chunks of 1000
    chunk_size = 1000
    for i in range(0, len(all_events), chunk_size):
        db.bulk_save_objects(all_events[i:i + chunk_size])
        db.commit()
        print(f"  Inserted {min(i + chunk_size, len(all_events))}/{len(all_events)} events...")

    db.close()
    print(f"\n✅ Seed complete!")
    print(f"   Total events: {len(all_events)}")
    print(f"   Total users: {total_users}")
    print(f"\n🔍 Anomaly injected:")
    print(f"   Google Ads signups jumped from ~25/day to ~95/day in the last 7 days")
    print(f"   But Google Ads users have only 22% retention (vs 55-70% for other channels)")
    print(f"   → Aggregate retention will drop ~8-12pp")
    print(f"   → Kitagawa-Oaxaca will attribute this to composition shift, not behavioral change")


if __name__ == "__main__":
    seed()
