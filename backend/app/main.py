from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Iterable

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from .nilm_engine import NILMEngine, DisaggResult

DB_PATH = os.path.join("data", "readings.db")
MODEL_DIR = os.path.join("models")

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# WebSocket / SSE connection manager  – broadcasts every new reading
# ---------------------------------------------------------------------------

class ConnectionManager:
    """Manages WebSocket connections and SSE subscribers for real-time push."""

    def __init__(self) -> None:
        self._ws_clients: list[WebSocket] = []
        self._sse_queues: list[asyncio.Queue[dict[str, Any]]] = []

    # -- WebSocket ----------------------------------------------------------
    async def ws_connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._ws_clients.append(ws)

    def ws_disconnect(self, ws: WebSocket) -> None:
        self._ws_clients.remove(ws)

    # -- SSE ----------------------------------------------------------------
    def sse_subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._sse_queues.append(q)
        return q

    def sse_unsubscribe(self, q: asyncio.Queue[dict[str, Any]]) -> None:
        self._sse_queues.remove(q)

    # -- Broadcast to all connected clients ---------------------------------
    async def broadcast(self, payload: dict[str, Any]) -> None:
        message = json.dumps(payload)

        # WebSocket clients
        stale: list[WebSocket] = []
        for ws in self._ws_clients:
            try:
                await ws.send_text(message)
            except Exception:
                stale.append(ws)
        for ws in stale:
            self._ws_clients.remove(ws)

        # SSE subscribers
        for q in self._sse_queues:
            await q.put(payload)


manager = ConnectionManager()
nilm_engine: NILMEngine | None = None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS meter_readings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                received_at TEXT NOT NULL,
                device_id TEXT NOT NULL,
                meter_id TEXT,
                site_id TEXT,
                timestamp TEXT,
                voltage_v REAL,
                current_a REAL,
                power_w REAL,
                energy_kwh REAL,
                frequency_hz REAL,
                power_factor REAL,
                raw_json TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS disaggregated_readings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                received_at TEXT NOT NULL,
                device_id TEXT NOT NULL,
                site_id TEXT,
                timestamp TEXT,
                appliance_id TEXT NOT NULL,
                appliance_label TEXT,
                power_w REAL,
                energy_kwh REAL,
                raw_json TEXT
            )
            """
        )


def _insert_reading(conn: sqlite3.Connection, reading: "MeterReading") -> None:
    conn.execute(
        """
        INSERT INTO meter_readings (
            received_at,
            device_id,
            meter_id,
            site_id,
            timestamp,
            voltage_v,
            current_a,
            power_w,
            energy_kwh,
            frequency_hz,
            power_factor,
            raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            reading.received_at.isoformat(),
            reading.device_id,
            reading.meter_id,
            reading.site_id,
            reading.timestamp.isoformat() if reading.timestamp else None,
            reading.voltage_v,
            reading.current_a,
            reading.power_w,
            reading.energy_kwh,
            reading.frequency_hz,
            reading.power_factor,
            json.dumps(reading.raw) if reading.raw else None,
        ),
    )


def _insert_disaggregated(
    conn: sqlite3.Connection, reading: "DisaggregatedReading"
) -> None:
    conn.execute(
        """
        INSERT INTO disaggregated_readings (
            received_at,
            device_id,
            site_id,
            timestamp,
            appliance_id,
            appliance_label,
            power_w,
            energy_kwh,
            raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            reading.received_at.isoformat(),
            reading.device_id,
            reading.site_id,
            reading.timestamp.isoformat() if reading.timestamp else None,
            reading.appliance_id,
            reading.appliance_label,
            reading.power_w,
            reading.energy_kwh,
            json.dumps(reading.raw) if reading.raw else None,
        ),
    )


def _insert_disagg_result(conn: sqlite3.Connection, r: DisaggResult) -> None:
    """Persist a DisaggResult from the NILM engine."""
    conn.execute(
        """
        INSERT INTO disaggregated_readings (
            received_at, device_id, site_id, timestamp,
            appliance_id, appliance_label, power_w, energy_kwh, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
        """,
        (
            _utc_now().isoformat(),
            r.device_id,
            r.site_id,
            r.timestamp.isoformat(),
            r.appliance_id,
            r.appliance_label,
            r.power_w,
            r.energy_kwh,
        ),
    )


class MeterReading(BaseModel):
    device_id: str = Field(..., description="Unique device identifier.")
    meter_id: str | None = Field(None, description="Meter identifier.")
    site_id: str | None = Field(None, description="House/site identifier.")
    timestamp: datetime | None = Field(
        None, description="Timestamp from the device, UTC preferred."
    )
    voltage_v: float | None = Field(None, description="Voltage in volts.")
    current_a: float | None = Field(None, description="Current in amps.")
    power_w: float | None = Field(None, description="Power in watts.")
    energy_kwh: float | None = Field(None, description="Energy in kWh.")
    frequency_hz: float | None = Field(None, description="Frequency in Hz.")
    power_factor: float | None = Field(None, description="Power factor (0-1).")
    raw: dict[str, Any] | None = Field(
        None, description="Raw payload for forward compatibility."
    )
    received_at: datetime = Field(default_factory=_utc_now)

    @field_validator(
        "voltage_v",
        "current_a",
        "power_w",
        "energy_kwh",
        "frequency_hz",
        "power_factor",
    )
    @classmethod
    def _non_negative(cls, value: float | None) -> float | None:
        if value is None:
            return value
        if value < 0:
            raise ValueError("value must be >= 0")
        return value


class MeterReadingBatch(BaseModel):
    readings: list[MeterReading] = Field(..., min_length=1)


class DisaggregatedReading(BaseModel):
    device_id: str = Field(..., description="Aggregator device identifier.")
    site_id: str | None = Field(None, description="House/site identifier.")
    timestamp: datetime | None = Field(
        None, description="Timestamp from the device, UTC preferred."
    )
    appliance_id: str = Field(
        ..., description="Disaggregated appliance identifier."
    )
    appliance_label: str | None = Field(
        None, description="Human label, e.g. fridge or kettle."
    )
    power_w: float | None = Field(None, description="Estimated power in watts.")
    energy_kwh: float | None = Field(None, description="Estimated energy in kWh.")
    raw: dict[str, Any] | None = Field(
        None, description="Raw payload for forward compatibility."
    )
    received_at: datetime = Field(default_factory=_utc_now)

    @field_validator("power_w", "energy_kwh")
    @classmethod
    def _non_negative(cls, value: float | None) -> float | None:
        if value is None:
            return value
        if value < 0:
            raise ValueError("value must be >= 0")
        return value


class DisaggregatedReadingBatch(BaseModel):
    readings: list[DisaggregatedReading] = Field(..., min_length=1)


@asynccontextmanager
async def lifespan(_: FastAPI) -> Iterable[None]:
    global nilm_engine
    _ensure_db()
    nilm_engine = NILMEngine(model_dir=MODEL_DIR)
    log.info("NILM engine initialised in '%s' mode", nilm_engine.mode)
    yield


app = FastAPI(title="NILM Meter Ingestion API", lifespan=lifespan)

# Allow any origin so the frontend (and ESP32) can reach the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# NILM engine helper — feed a reading and persist/broadcast any results
# ---------------------------------------------------------------------------

async def _process_nilm(reading: MeterReading) -> None:
    if nilm_engine is None:
        return

    results = nilm_engine.feed(
        device_id=reading.device_id,
        timestamp=reading.timestamp or reading.received_at,
        power_w=reading.power_w,
        site_id=reading.site_id,
    )

    if not results:
        return

    try:
        with sqlite3.connect(DB_PATH) as conn:
            for r in results:
                _insert_disagg_result(conn, r)
    except sqlite3.Error:
        log.exception("Failed to persist disaggregation results")

    for r in results:
        await manager.broadcast({
            "type": "disaggregation",
            "device_id": r.device_id,
            "site_id": r.site_id,
            "timestamp": r.timestamp.isoformat(),
            "received_at": _utc_now().isoformat(),
            "appliance_id": r.appliance_id,
            "appliance_label": r.appliance_label,
            "power_w": r.power_w,
            "energy_kwh": r.energy_kwh,
        })


# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/v1/nilm/status")
def nilm_status() -> dict[str, Any]:
    """Return current NILM engine state (model mode, buffer fill, appliances)."""
    if nilm_engine is None:
        return {"mode": "unavailable", "appliances": [], "buffers": {}}
    return nilm_engine.status()


def _reading_to_broadcast(reading: MeterReading) -> dict[str, Any]:
    """Serialise a MeterReading to a JSON-friendly dict for broadcasting."""
    return {
        "type": "meter",
        "received_at": reading.received_at.isoformat(),
        "device_id": reading.device_id,
        "meter_id": reading.meter_id,
        "site_id": reading.site_id,
        "timestamp": reading.timestamp.isoformat() if reading.timestamp else None,
        "voltage_v": reading.voltage_v,
        "current_a": reading.current_a,
        "power_w": reading.power_w,
        "energy_kwh": reading.energy_kwh,
        "frequency_hz": reading.frequency_hz,
        "power_factor": reading.power_factor,
    }


@app.post("/api/v1/readings")
async def ingest_reading(reading: MeterReading) -> dict[str, Any]:
    try:
        with sqlite3.connect(DB_PATH) as conn:
            _insert_reading(conn, reading)
    except sqlite3.Error as exc:
        raise HTTPException(status_code=500, detail="db_write_failed") from exc

    # Broadcast to all real-time subscribers (WebSocket + SSE)
    await manager.broadcast(_reading_to_broadcast(reading))

    # Feed into NILM disaggregation engine
    await _process_nilm(reading)

    return {"status": "stored", "received_at": reading.received_at.isoformat()}


@app.post("/api/v1/readings/batch")
async def ingest_batch(payload: MeterReadingBatch) -> dict[str, Any]:
    try:
        with sqlite3.connect(DB_PATH) as conn:
            for reading in payload.readings:
                _insert_reading(conn, reading)
    except sqlite3.Error as exc:
        raise HTTPException(status_code=500, detail="db_write_failed") from exc

    for reading in payload.readings:
        await manager.broadcast(_reading_to_broadcast(reading))
        await _process_nilm(reading)

    return {"status": "stored", "count": len(payload.readings)}


@app.post("/api/v1/disaggregation")
def ingest_disaggregation(reading: DisaggregatedReading) -> dict[str, Any]:
    try:
        with sqlite3.connect(DB_PATH) as conn:
            _insert_disaggregated(conn, reading)
    except sqlite3.Error as exc:
        raise HTTPException(status_code=500, detail="db_write_failed") from exc

    return {"status": "stored", "received_at": reading.received_at.isoformat()}


@app.post("/api/v1/disaggregation/batch")
def ingest_disaggregation_batch(
    payload: DisaggregatedReadingBatch,
) -> dict[str, Any]:
    try:
        with sqlite3.connect(DB_PATH) as conn:
            for reading in payload.readings:
                _insert_disaggregated(conn, reading)
    except sqlite3.Error as exc:
        raise HTTPException(status_code=500, detail="db_write_failed") from exc

    return {"status": "stored", "count": len(payload.readings)}


@app.get("/api/v1/disaggregation/recent")
def recent_disaggregation(limit: int = 50) -> list[dict[str, Any]]:
    if limit < 1 or limit > 500:
        raise HTTPException(status_code=400, detail="limit_out_of_range")

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT
                received_at,
                device_id,
                site_id,
                timestamp,
                appliance_id,
                appliance_label,
                power_w,
                energy_kwh,
                raw_json
            FROM disaggregated_readings
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    results: list[dict[str, Any]] = []
    for row in rows:
        result = dict(row)
        if result.get("raw_json"):
            result["raw"] = json.loads(result.pop("raw_json"))
        else:
            result.pop("raw_json", None)
        results.append(result)
    return results


@app.get("/api/v1/readings/recent")
def recent_readings(limit: int = 50) -> list[dict[str, Any]]:
    if limit < 1 or limit > 500:
        raise HTTPException(status_code=400, detail="limit_out_of_range")

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT
                received_at,
                device_id,
                meter_id,
                site_id,
                timestamp,
                voltage_v,
                current_a,
                power_w,
                energy_kwh,
                frequency_hz,
                power_factor,
                raw_json
            FROM meter_readings
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    results: list[dict[str, Any]] = []
    for row in rows:
        result = dict(row)
        if result.get("raw_json"):
            result["raw"] = json.loads(result.pop("raw_json"))
        else:
            result.pop("raw_json", None)
        results.append(result)
    return results


# ---------------------------------------------------------------------------
# Real-time endpoints
# ---------------------------------------------------------------------------


@app.websocket("/ws/readings")
async def ws_readings(ws: WebSocket) -> None:
    """WebSocket endpoint – frontend connects here to receive live readings."""
    await manager.ws_connect(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.ws_disconnect(ws)


async def _sse_generator(
    queue: asyncio.Queue[dict[str, Any]],
) -> AsyncGenerator[str, None]:
    """Yield Server-Sent Events from an asyncio queue."""
    try:
        while True:
            payload = await queue.get()
            yield f"data: {json.dumps(payload)}\n\n"
    except asyncio.CancelledError:
        return


@app.get("/api/v1/readings/stream")
async def stream_readings() -> StreamingResponse:
    """SSE endpoint – alternative to WebSocket for simpler clients."""
    queue = manager.sse_subscribe()

    async def event_stream() -> AsyncGenerator[str, None]:
        try:
            async for chunk in _sse_generator(queue):
                yield chunk
        finally:
            manager.sse_unsubscribe(queue)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
