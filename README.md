# NILM Smart Meter Integrated Project

End-to-end NILM (Non-Intrusive Load Monitoring) stack that combines:

- Real-time meter ingestion API (FastAPI + SQLite)
- NILM disaggregation pipeline (engine inside backend)
- Live frontend dashboard (React + Vite)
- ESP32 simulator for local testing without hardware

This repository is designed for a demo-to-deployment workflow: you can start with simulated data, validate charts and APIs, then switch to real ESP32/PZEM data.

## 1) Project Overview

The system flow is:

1. A smart meter source sends readings (real ESP32 or simulator).
2. Backend stores raw readings in SQLite.
3. Backend runs NILM disaggregation and stores appliance-level estimates.
4. Backend pushes live updates over WebSocket/SSE.
5. Frontend consumes live or recent data for dashboard visualization.

### High-level Architecture

```text
ESP32/PZEM or Simulator
        |
        | POST /api/v1/readings
        v
FastAPI Backend (port 8000)
  - Stores meter_readings (SQLite)
  - Runs NILM engine
  - Stores disaggregated_readings
  - Broadcasts via WebSocket/SSE
        |
        +--> REST endpoints for recent data
        +--> WS /ws/readings
        +--> SSE /api/v1/readings/stream
        |
        v
React Frontend Dashboard (port 5173)
```

## 2) Repository Structure

```text
NILM-smart-meter/
  arduino.c                  # ESP32-side reference sketch
  main.py                    # Optional local script (if used)
  backend/
    app/
      main.py                # FastAPI app and routes
      nilm_engine.py         # NILM inference/disaggregation logic
      nilm_model.py          # Model helpers
    data/                    # SQLite DB path (auto-created)
    models/                  # Trained model artifacts (if available)
    setup_data.py            # Data/model setup helper
    train_model.py           # Training script
    simulate_esp32.py        # Sends realistic mock readings every second
    requirements.txt
    tests/
  frontend/
    src/
    package.json
```

## 3) Prerequisites

- Python 3.10+ (3.11/3.12 recommended)
- Node.js 18+ and npm
- Git

Verify tools:

```bash
python --version
node --version
npm --version
```

## 4) Run the Full Stack (Backend + Frontend)

Use two terminals minimum (three if running simulator).

### Terminal A: Start Backend

From repository root:

```bash
cd backend
python -m venv .venv
```

Activate virtual environment:

Windows PowerShell:

```bash
.venv\Scripts\Activate.ps1
```

Windows CMD:

```bash
.venv\Scripts\activate.bat
```

macOS/Linux:

```bash
source .venv/bin/activate
```

Install dependencies and run server:

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Backend URLs:

- API base: http://localhost:8000
- Swagger docs: http://localhost:8000/docs
- Health check: http://localhost:8000/health

### Terminal B: Start Frontend

From repository root:

```bash
cd frontend
npm install
npm run dev
```

Open the Vite URL shown in terminal (typically http://localhost:5173).

### Terminal C (Optional): Simulate ESP32 Data

If you do not have physical hardware connected, send test readings using simulator:

```bash
cd backend
```

Activate the same backend virtual environment, then:

```bash
python simulate_esp32.py
```

You should see continuous readings and live dashboard updates.

## 5) Backend API Overview

### Core Health/Status

- GET /health
- GET /api/v1/nilm/status

### Meter Readings

- POST /api/v1/readings
- POST /api/v1/readings/batch
- GET /api/v1/readings/recent?limit=50

### Disaggregation Readings

- POST /api/v1/disaggregation
- POST /api/v1/disaggregation/batch
- GET /api/v1/disaggregation/recent?limit=50

### Live Streaming

- WebSocket: /ws/readings
- SSE: /api/v1/readings/stream

Tip: open Swagger docs at http://localhost:8000/docs to inspect request schemas and try endpoints interactively.

## 6) Quick Validation Checklist

After startup, verify in order:

1. Backend health returns status ok.
2. Frontend page loads without console/API errors.
3. Simulator prints sent cycles (or hardware posts data).
4. /api/v1/readings/recent returns non-empty list.
5. Dashboard charts/tables update over time.

## 7) Running Tests

From backend directory with virtual environment active:

```bash
pytest tests -v
```

## 8) Production Notes

- Replace wildcard CORS with specific frontend origins.
- Run behind a process manager/reverse proxy.
- Move from SQLite to a production DB when scaling.
- Add authentication and rate limiting for public deployments.

## 9) Common Issues and Fixes

### Frontend cannot reach backend

- Confirm backend is running on port 8000.
- Check browser network tab for failed API calls.
- Ensure no local firewall blocks localhost traffic.

### No live data appears

- Start simulator: python simulate_esp32.py
- Check backend logs for request validation errors.
- Verify readings exist at /api/v1/readings/recent.

### Python dependency install fails

- Upgrade pip first: python -m pip install --upgrade pip
- Recreate virtual environment and reinstall requirements.

## 10) Hardware Integration (Optional)

If using real ESP32 + PZEM:

1. Adapt firmware from arduino.c.
2. Point firmware HTTP POST target to your backend host and port.
3. Send payloads matching the reading schema used by POST /api/v1/readings.

For local LAN testing from device, replace localhost with your machine LAN IP in firmware and frontend config where required.