from __future__ import annotations

import json
import os
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Iterable

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator

DB_PATH = os.path.join("data", "readings.db")


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
    _ensure_db()
    yield


app = FastAPI(title="NILM Meter Ingestion API", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/v1/readings")
def ingest_reading(reading: MeterReading) -> dict[str, Any]:
    try:
        with sqlite3.connect(DB_PATH) as conn:
            _insert_reading(conn, reading)
    except sqlite3.Error as exc:
        raise HTTPException(status_code=500, detail="db_write_failed") from exc

    return {"status": "stored", "received_at": reading.received_at.isoformat()}


@app.post("/api/v1/readings/batch")
def ingest_batch(payload: MeterReadingBatch) -> dict[str, Any]:
    try:
        with sqlite3.connect(DB_PATH) as conn:
            for reading in payload.readings:
                _insert_reading(conn, reading)
    except sqlite3.Error as exc:
        raise HTTPException(status_code=500, detail="db_write_failed") from exc

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