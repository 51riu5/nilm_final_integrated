import json
import threading
import time

import app.main as main
from fastapi.testclient import TestClient
import pytest


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "readings.db"
    monkeypatch.setattr(main, "DB_PATH", str(db_path))
    main._ensure_db()
    with TestClient(main.app) as test_client:
        yield test_client


# ── Existing tests ────────────────────────────────────────────


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ingest_reading_and_recent(client):
    payload = {
        "device_id": "device-123",
        "meter_id": "meter-1",
        "site_id": "site-a",
        "timestamp": "2026-01-30T12:00:00Z",
        "voltage_v": 230.5,
        "current_a": 1.2,
        "power_w": 280.0,
        "energy_kwh": 0.15,
        "frequency_hz": 50.0,
        "power_factor": 0.92,
        "raw": {"firmware": "1.2.3"},
    }
    response = client.post("/api/v1/readings", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "stored"
    assert "received_at" in data

    recent = client.get("/api/v1/readings/recent?limit=1")
    assert recent.status_code == 200
    rows = recent.json()
    assert len(rows) == 1
    assert rows[0]["device_id"] == "device-123"


def test_ingest_batch(client):
    payload = {
        "readings": [
            {
                "device_id": "device-123",
                "meter_id": "meter-1",
                "site_id": "site-a",
                "timestamp": "2026-01-30T12:00:00Z",
                "power_w": 100.0,
            },
            {
                "device_id": "device-123",
                "meter_id": "meter-1",
                "site_id": "site-a",
                "timestamp": "2026-01-30T12:01:00Z",
                "power_w": 120.0,
            },
        ]
    }
    response = client.post("/api/v1/readings/batch", json=payload)
    assert response.status_code == 200
    assert response.json() == {"status": "stored", "count": 2}


def test_disaggregation_and_recent(client):
    payload = {
        "device_id": "agg-77",
        "site_id": "site-a",
        "timestamp": "2026-01-30T12:05:00Z",
        "appliance_id": "kettle",
        "appliance_label": "Kettle",
        "power_w": 1500.0,
        "energy_kwh": 0.02,
        "raw": {"model": "demo"},
    }
    response = client.post("/api/v1/disaggregation", json=payload)
    assert response.status_code == 200

    recent = client.get("/api/v1/disaggregation/recent?limit=1")
    assert recent.status_code == 200
    rows = recent.json()
    assert len(rows) == 1
    assert rows[0]["appliance_id"] == "kettle"


def test_recent_limit_out_of_range(client):
    response = client.get("/api/v1/readings/recent?limit=0")
    assert response.status_code == 400
    assert response.json()["detail"] == "limit_out_of_range"


# ── ESP32 hardware payload (no timestamp, no raw) ────────────


def test_esp32_payload(client):
    """The ESP32 sends exactly these fields – make sure the backend accepts them."""
    payload = {
        "device_id": "esp32_1",
        "meter_id": "pzem_1",
        "site_id": "home_1",
        "voltage_v": 229.5,
        "current_a": 0.22,
        "power_w": 45.4,
        "energy_kwh": 0.04,
        "frequency_hz": 50.0,
        "power_factor": 0.9,
    }
    response = client.post("/api/v1/readings", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "stored"

    recent = client.get("/api/v1/readings/recent?limit=1")
    rows = recent.json()
    assert len(rows) == 1
    assert rows[0]["device_id"] == "esp32_1"
    assert rows[0]["voltage_v"] == 229.5
    # timestamp should be null since ESP32 doesn't send one
    assert rows[0]["timestamp"] is None


# ── WebSocket real-time test ──────────────────────────────────


def test_websocket_receives_broadcast(client):
    """Connect via WebSocket, POST a reading, assert the WS gets it."""
    with client.websocket_connect("/ws/readings") as ws:
        # POST a reading while the WS is connected
        payload = {
            "device_id": "esp32_ws",
            "meter_id": "pzem_1",
            "site_id": "home_1",
            "voltage_v": 230.0,
            "current_a": 0.5,
            "power_w": 115.0,
            "energy_kwh": 1.2,
            "frequency_hz": 50.0,
            "power_factor": 0.95,
        }
        resp = client.post("/api/v1/readings", json=payload)
        assert resp.status_code == 200

        msg = ws.receive_text()
        data = json.loads(msg)
        assert data["device_id"] == "esp32_ws"
        assert data["power_w"] == 115.0
