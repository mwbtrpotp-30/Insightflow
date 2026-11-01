"""
InsightFlow — Agentic AI-Powered Product Analytics Platform
FastAPI main application entry point.
"""
import logging
import importlib
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .database import engine
from .models import Base
from .routers import events, metrics, investigations
from .routers.anomaly_detector import router as monitor_router
from .routers.nl_query import router as nl_query_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create all tables on startup
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="InsightFlow",
    description=(
        "Agentic AI-Powered Product Analytics Platform. "
        "Core contribution: Budget-Aware Adaptive Causal Investigation of Product Metric Anomalies."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

# Allow React dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(events.router)
app.include_router(metrics.router)
app.include_router(investigations.router)
app.include_router(monitor_router)
app.include_router(nl_query_router)


@app.get("/")
def root():
    return {
        "name": "InsightFlow",
        "version": "0.1.0",
        "docs": "/docs",
    }


@app.get("/health")
def health():
    return {"status": "ok"}


SCENARIO_LABELS = {
    1: "Composition Shift — Google Ads surge",
    2: "Behavioral Change — product regression",
    3: "Cohort Age Effect — viral signup spike",
    4: "Data Pipeline Artifact — SDK drop",
}


@app.post("/api/load-scenario/{scenario_id}")
def load_scenario(scenario_id: int):
    """
    Re-seeds the database with one of the four demo anomaly scenarios.
    Called from the frontend scenario picker — no terminal needed.
    """
    if scenario_id not in SCENARIO_LABELS:
        raise HTTPException(status_code=400, detail=f"scenario_id must be 1–4, got {scenario_id}")

    try:
        # Import seed_scenarios from the backend root (one level up from app/)
        import sys, os
        backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if backend_dir not in sys.path:
            sys.path.insert(0, backend_dir)

        import seed_scenarios
        importlib.reload(seed_scenarios)   # reload so any state is fresh

        result = seed_scenarios.run_scenario(scenario_id)

        logger.info(f"[ScenarioPicker] Loaded scenario {scenario_id}: {SCENARIO_LABELS[scenario_id]}")
        return {
            "ok": True,
            "scenario_id": scenario_id,
            "label": SCENARIO_LABELS[scenario_id],
            "users": result.get("users", 0),
            "events": result.get("events", 0),
        }

    except Exception as e:
        logger.error(f"[ScenarioPicker] Failed to load scenario {scenario_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
