# NILM — Non-Intrusive Load Monitoring Backend

> Real-time energy monitoring backend that receives power readings from an **ESP32 + PZEM-004T** sensor and pushes them to any frontend via **WebSocket** and **SSE** (Server-Sent Events).

---

## How It Works

```
┌──────────────┐         POST /api/v1/readings         ┌─────────────────┐
│  ESP32 +     │  ──────────────────────────────────►  │  FastAPI Backend │
│  PZEM-004T   │         (every 5 seconds)             │                 │
└──────────────┘                                       │  ┌───────────┐  │
                                                       │  │  SQLite   │  │
                                                       │  │  (store)  │  │
                                                       │  └───────────┘  │
                                                       │        │        │
                                                       │    broadcast    │
                                                       │        │        │
                                                       └────────┼────────┘
                                                                │
                                          ┌─────────────────────┼─────────────────────┐
                                          │                     │                     │
                                   WebSocket              SSE Stream              REST GET
                                 ws://host:8000       /api/v1/readings/       /api/v1/readings/
                                  /ws/readings            stream                  recent
                                          │                     │                     │
                                          ▼                     ▼                     ▼
                                   ┌─────────────────────────────────────────────────────┐
                                   │                    Frontend App                     │
                                   └─────────────────────────────────────────────────────┘
```

The ESP32 sends a JSON reading every 5 seconds. The backend:
1. **Stores** it in SQLite
2. **Broadcasts** it instantly to every connected WebSocket and SSE client

---

## Quick Start

```bash
# 1. Clone
git clone https://github.com/51riu5/nilm_project.git
cd nilm_project

# 2. Create virtual environment
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run the server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The SQLite database is auto-created at `data/readings.db`.

Open **http://localhost:8000/docs** for the interactive Swagger UI.

---

## API Reference

### Health Check

| Method | Endpoint  | Description       |
|--------|-----------|-------------------|
| GET    | `/health` | Returns `{"status": "ok"}` |

### Meter Readings

| Method | Endpoint                      | Description                         |
|--------|-------------------------------|-------------------------------------|
| POST   | `/api/v1/readings`            | Ingest a **single** reading         |
| POST   | `/api/v1/readings/batch`      | Ingest **multiple** readings        |
| GET    | `/api/v1/readings/recent`     | Get recent readings (query: `limit`, default 50, max 500) |

### Disaggregation (NILM results)

| Method | Endpoint                            | Description                              |
|--------|-------------------------------------|------------------------------------------|
| POST   | `/api/v1/disaggregation`            | Ingest a single disaggregated reading    |
| POST   | `/api/v1/disaggregation/batch`      | Ingest a batch of disaggregated readings |
| GET    | `/api/v1/disaggregation/recent`     | Get recent disaggregated readings        |

### Real-Time Streaming (for Frontend)

| Method    | Endpoint                      | Description                          |
|-----------|-------------------------------|--------------------------------------|
| WebSocket | `/ws/readings`                | Live push via WebSocket              |
| GET       | `/api/v1/readings/stream`     | Live push via SSE (Server-Sent Events) |

---

## ESP32 Payload Format

The ESP32 firmware sends this JSON every 5 seconds — no `timestamp` or `raw` field needed (both are optional):

```json
{
  "device_id": "esp32_1",
  "meter_id": "pzem_1",
  "site_id": "home_1",
  "voltage_v": 229.5,
  "current_a": 0.22,
  "power_w": 45.4,
  "energy_kwh": 0.04,
  "frequency_hz": 50.0,
  "power_factor": 0.9
}
```

### Full Field Reference

| Field          | Type     | Required | Description                          |
|----------------|----------|----------|--------------------------------------|
| `device_id`    | string   | **yes**  | Unique device identifier             |
| `meter_id`     | string   | no       | Meter identifier (e.g. `pzem_1`)     |
| `site_id`      | string   | no       | House/site identifier                |
| `timestamp`    | ISO 8601 | no       | Device timestamp (UTC preferred). If omitted, server uses `received_at` |
| `voltage_v`    | float    | no       | Voltage in volts                     |
| `current_a`    | float    | no       | Current in amps                      |
| `power_w`      | float    | no       | Active power in watts                |
| `energy_kwh`   | float    | no       | Cumulative energy in kWh             |
| `frequency_hz` | float    | no       | Grid frequency in Hz                 |
| `power_factor` | float    | no       | Power factor (0 – 1)                 |
| `raw`          | object   | no       | Any extra data for forward compat    |

> All numeric fields must be **>= 0**. The server auto-fills `received_at` (UTC).

---

## Frontend Integration Guide

### Option 1 — WebSocket (recommended)

Best for dashboards that need instant updates with minimal latency.

```javascript
// Connect to the backend WebSocket
const ws = new WebSocket("ws://YOUR_BACKEND_IP:8000/ws/readings");

ws.onopen = () => {
  console.log("Connected to NILM live stream");
};

ws.onmessage = (event) => {
  const reading = JSON.parse(event.data);
  console.log("Live reading:", reading);

  // reading.voltage_v   → 229.5
  // reading.current_a   → 0.22
  // reading.power_w     → 45.4
  // reading.energy_kwh  → 0.04
  // reading.frequency_hz → 50.0
  // reading.power_factor → 0.9
  // reading.received_at → "2026-03-27T13:16:53.672704+00:00"
  // reading.device_id   → "esp32_1"
  // reading.meter_id    → "pzem_1"
  // reading.site_id     → "home_1"
};

ws.onclose = () => {
  console.log("Disconnected — consider auto-reconnect");
};
```

#### React example

```jsx
import { useEffect, useState } from "react";

function useNILMStream(url) {
  const [reading, setReading] = useState(null);

  useEffect(() => {
    const ws = new WebSocket(url);
    ws.onmessage = (e) => setReading(JSON.parse(e.data));
    return () => ws.close();
  }, [url]);

  return reading;
}

// Usage in a component
function Dashboard() {
  const reading = useNILMStream("ws://YOUR_BACKEND_IP:8000/ws/readings");

  if (!reading) return <p>Waiting for data...</p>;

  return (
    <div>
      <h2>Live Power: {reading.power_w} W</h2>
      <p>Voltage: {reading.voltage_v} V</p>
      <p>Current: {reading.current_a} A</p>
      <p>Power Factor: {reading.power_factor}</p>
    </div>
  );
}
```

### Option 2 — Server-Sent Events (SSE)

Simpler than WebSocket; works with `EventSource` (no library needed). Good fallback if WebSocket is blocked.

```javascript
const source = new EventSource("http://YOUR_BACKEND_IP:8000/api/v1/readings/stream");

source.onmessage = (event) => {
  const reading = JSON.parse(event.data);
  console.log("Live reading:", reading);
};

source.onerror = () => {
  console.log("SSE connection lost — browser will auto-reconnect");
};
```

### Option 3 — Polling (simple fallback)

If real-time isn't critical, poll the REST endpoint:

```javascript
async function fetchRecent() {
  const res = await fetch("http://YOUR_BACKEND_IP:8000/api/v1/readings/recent?limit=1");
  const data = await res.json();
  return data[0]; // latest reading
}

// Poll every 5 seconds
setInterval(async () => {
  const latest = await fetchRecent();
  console.log(latest);
}, 5000);
```

---

## Broadcast Message Shape

Every message pushed via WebSocket / SSE has this shape:

```json
{
  "received_at": "2026-03-27T13:16:53.672704+00:00",
  "device_id": "esp32_1",
  "meter_id": "pzem_1",
  "site_id": "home_1",
  "timestamp": null,
  "voltage_v": 229.5,
  "current_a": 0.22,
  "power_w": 45.4,
  "energy_kwh": 0.04,
  "frequency_hz": 50.0,
  "power_factor": 0.9
}
```

---

## Project Structure

```
nilm/
├── app/
│   ├── __init__.py
│   └── main.py            # FastAPI app (all routes + WebSocket + SSE)
├── data/
│   └── readings.db         # SQLite database (auto-created)
├── tests/
│   ├── conftest.py
│   └── test_api.py         # Pytest tests (REST + WebSocket)
├── demo_api.py             # Quick demo script to test all endpoints
├── requirements.txt
└── README.md
```

## Running Tests

```bash
python -m pytest tests/ -v
```

---

## Tech Stack

| Component  | Technology                |
|------------|---------------------------|
| Backend    | Python 3.12 + FastAPI     |
| Database   | SQLite                    |
| Real-time  | WebSocket + SSE           |
| Hardware   | ESP32 (XIAO C3) + PZEM-004T v3.0 |
| Protocol   | HTTP POST (JSON) from ESP32 to backend |

---

## CORS

CORS is **fully open** (`allow_origins=["*"]`) so any frontend on any port/domain can connect. Tighten this in production.
