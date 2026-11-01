# InsightFlow — Agentic AI-Powered Product Analytics Platform

> **Course Project: Advanced Software Engineering, IIT BHU**
> 
> **Novel Contribution**: Budget-Aware Adaptive Causal Investigation of Product Metric Anomalies using a Greedy Information-Gain Selector

---

## What it does

InsightFlow is a Mixpanel-style product analytics platform. When a metric anomaly is detected, an **agentic investigation engine** kicks in that adaptively decides which statistical test to run next based on the evidence already collected — rather than following a fixed pipeline like all prior work.

### The Novel Core
Most existing automated RCA systems (LLMDebug 2026, Context-RCA 2026, RCLAgent 2026) run a **predetermined sequence of tests**. InsightFlow's engine:
1. Generates candidate hypotheses for the anomaly
2. **Scores each available test** by how many high-confidence hypotheses it can discriminate (info-gain)
3. Runs the highest-scoring test
4. Updates hypothesis confidences from the result
5. **Eliminates ruled-out hypotheses** and re-scores remaining tests
6. Loops until one hypothesis is confirmed or budget exhausted

It always runs at least 4 tests (`MIN_TESTS`) and at most 6 (`MAX_TESTS`), stopping early once one hypothesis passes 70% confidence. The order of tests is chosen adaptively from the evidence so far, so different anomalies are investigated along different paths.

---

## Quick Start (5 minutes)

### 1. Backend

```bash
cd insightflow/backend

# Install dependencies
pip install fastapi "uvicorn[standard]" sqlalchemy pydantic scipy numpy python-dateutil --break-system-packages

# Seed demo data (40K events with an injected anomaly)
python seed_data.py

# Start the API server
uvicorn app.main:app --reload --port 8000
```

API docs at: http://localhost:8000/docs

### 2. Frontend

```bash
cd insightflow/frontend
npm install
npm start
```

Dashboard at: http://localhost:3000

---

## Demo Script (for tomorrow's presentation)

### Step 1 — Show the Anomaly
Open the **Metrics** tab. You'll see:
- Aggregate retention dropped ~30% in the last 7 days
- The channel-breakdown chart shows Google Ads users have much lower retention
- Red anomaly alert banner fires

### Step 2 — Trigger the Investigation
Click the red **"🚨 Trigger Investigation"** button in the header.

### Step 3 — Watch the Adaptive Investigation
Switch to the **Investigation Trace** tab. You'll see steps appearing one by one:

```
Step 1: Age-Matched Retention Test
  → Result: "2-day return rate fell from 30.4% to 22.8% (p=0.001)"
  → Cohort age effect ruled down — users really are returning less

Step 2: Funnel Step Drop Analysis
  → Result: "Funnel steps are stable"

Step 3: Kitagawa-Oaxaca Decomposition
  → Result: "Composition effect dominates (100% of change)"
  → Eliminates: behavioral_change

Step 4: Acquisition Mix Chi-Squared Test
  → Result: "google_ads +30.8pp share (p < 0.001)"

... (continues adaptively until one cause passes 70%)

Conclusion: composition shift (≈82% confidence)
```

Results from the fallback (no Gemini key) run, with no hint about the cause:

| Scenario | Tests run | Agent's conclusion |
|---|---|---|
| 1 — Composition Shift | 5 | composition_shift (82%) |
| 2 — Behavioral Change | 4 | behavioral_change (70%) |
| 3 — Cohort Age Effect | 4 | cohort_age_effect (96%) |
| 4 — Data Pipeline Artifact | 6 | data_artifact (69%) |

### Step 4 — Explain the Novelty
**Key talking point**: "Fixed pipeline systems like LLMDebug and Context-RCA always run the same tests in the same order. Our selector picks each next test from the evidence so far — in Scenario 3 the age-matched test immediately points to cohort age and the investigation wraps up after 4 tests, while in Scenario 4 the uniform funnel drop raises the data-artifact hypothesis and the agent goes on to run the event-volume check that confirms it. This is the greedy information-gain selector in action."

**Note**: neither 🚨 Trigger nor 📡 Auto-Detect tells the agent which scenario is loaded. Both measure the metric from the event data and pass only those numbers to the hypothesis generator, so the root cause is found from the statistical tests alone.

---

## Architecture

```
Event SDK → FastAPI Ingestion → SQLite (simulates TimescaleDB)
                                      ↓
                            Anomaly Detector (KS test)
                                      ↓
                    ┌─── Adaptive Investigation Engine ───┐
                    │  1. Hypothesis Generator             │
                    │  2. Greedy Info-Gain Selector  ←★   │
                    │  3. Investigator Agent               │
                    │  4. Evidence Store                   │
                    │  5. Loop Decision                    │
                    │  6. Synthesis Agent                  │
                    └─────────────────────────────────────┘
                                      ↓
                              React Dashboard
```

---

## Paper Positioning

| Paper | Venue | What it does | Our advantage |
|-------|-------|-------------|---------------|
| RCLAgent (2026) | IEEE TDSC | Recursive agent decomposition on microservice traces | Infrastructure domain; topology-driven not info-gain-driven |
| Context-RCA (2026) | IEEE JCC | Iterative consensus loop for microservice RCA | Verifies agreement; doesn't select next test |
| Detecting Process Anomalies (2026) | IEEE TSC | Causal ML on process event logs | Process timing, not product behavioral metrics; fixed pipeline |
| LLMDebug (2026) | AAIML | Multi-agent hypothesis pipeline on microservice logs | Most similar structure; **fixed pipeline** |
| CHASE (2026) | IEEE TBD | Multimodal RCA via causal hypergraph + GNN | Fixed fusion; infrastructure domain |

**Our claim**: First adaptive sequential investigation framework for *product behavioral metric anomalies* using greedy information-gain test selection.

---

## File Structure

```
insightflow/
├── backend/
│   ├── app/
│   │   ├── main.py                  # FastAPI app
│   │   ├── models.py                # SQLAlchemy ORM
│   │   ├── schemas.py               # Pydantic schemas
│   │   ├── database.py              # SQLite connection
│   │   ├── routers/
│   │   │   ├── events.py            # Event ingestion API
│   │   │   ├── metrics.py           # Metrics API
│   │   │   └── investigations.py    # Investigation API
│   │   └── services/
│   │       └── investigation_engine/
│   │           ├── engine.py        # Main adaptive loop ★
│   │           ├── hypothesis_generator.py  # Initial hypotheses
│   │           ├── selector.py      # Greedy info-gain selector ★
│   │           ├── test_catalog.py  # 6 statistical tests
│   │           ├── evidence_store.py # Confidence updates
│   │           └── synthesis.py     # Conclusion generation
│   ├── seed_data.py                 # Demo data with anomaly
│   └── requirements.txt
└── frontend/
    └── src/
        ├── App.js
        └── components/
            ├── MetricsDashboard.js  # Charts
            ├── InvestigationPanel.js # Step-by-step trace
            └── InvestigationsList.js # History
```
