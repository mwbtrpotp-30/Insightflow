from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Event
from ..schemas import EventIn, EventOut, EventBatchIn

router = APIRouter(prefix="/events", tags=["events"])


@router.post("/", response_model=EventOut, status_code=201)
def ingest_event(event: EventIn, db: Session = Depends(get_db)):
    db_event = Event(
        event_name=event.event_name,
        user_id=event.user_id,
        timestamp=event.timestamp or datetime.utcnow(),
        acquisition_channel=event.acquisition_channel,
        country=event.country,
        plan_tier=event.plan_tier,
        properties=str(event.properties),
    )
    db.add(db_event)
    db.commit()
    db.refresh(db_event)
    return db_event


@router.post("/batch", status_code=201)
def ingest_batch(batch: EventBatchIn, db: Session = Depends(get_db)):
    db_events = []
    for event in batch.events:
        db_events.append(Event(
            event_name=event.event_name,
            user_id=event.user_id,
            timestamp=event.timestamp or datetime.utcnow(),
            acquisition_channel=event.acquisition_channel,
            country=event.country,
            plan_tier=event.plan_tier,
            properties=str(event.properties or {}),
        ))
    db.bulk_save_objects(db_events)
    db.commit()
    return {"inserted": len(db_events)}


@router.get("/count")
def event_count(db: Session = Depends(get_db)):
    return {"count": db.query(Event).count()}
