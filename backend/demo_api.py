from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx

BASE_URL = "http://127.0.0.1:8000"


def _print(title: str, response: httpx.Response) -> None:
    print(f"\n== {title} ==")
    print(f"Status: {response.status_code}")
    try:
        print(json.dumps(response.json(), indent=2))
    except ValueError:
        print(response.text)


def main() -> None:
    now = datetime.now(timezone.utc).isoformat()

    with httpx.Client(base_url=BASE_URL, timeout=10.0) as client:
        _print("Health", client.get("/health"))

        reading = {
            "device_id": "demo-device",
            "meter_id": "main-meter",
            "site_id": "demo-site",
            "timestamp": now,
            "voltage_v": 230.0,
            "current_a": 1.1,
            "power_w": 250.0,
            "energy_kwh": 0.12,
            "frequency_hz": 50.0,
            "power_factor": 0.9,
            "raw": {"source": "demo"},
        }
        _print("POST /api/v1/readings", client.post("/api/v1/readings", json=reading))

        batch = {
            "readings": [
                {
                    "device_id": "demo-device",
                    "meter_id": "main-meter",
                    "site_id": "demo-site",
                    "timestamp": now,
                    "power_w": 120.0,
                },
                {
                    "device_id": "demo-device",
                    "meter_id": "main-meter",
                    "site_id": "demo-site",
                    "timestamp": now,
                    "power_w": 180.0,
                },
            ]
        }
        _print(
            "POST /api/v1/readings/batch",
            client.post("/api/v1/readings/batch", json=batch),
        )

        disaggregation = {
            "device_id": "demo-agg",
            "site_id": "demo-site",
            "timestamp": now,
            "appliance_id": "kettle",
            "appliance_label": "Kettle",
            "power_w": 1500.0,
            "energy_kwh": 0.03,
            "raw": {"model": "demo"},
        }
        _print(
            "POST /api/v1/disaggregation",
            client.post("/api/v1/disaggregation", json=disaggregation),
        )

        _print(
            "GET /api/v1/readings/recent",
            client.get("/api/v1/readings/recent", params={"limit": 3}),
        )
        _print(
            "GET /api/v1/disaggregation/recent",
            client.get("/api/v1/disaggregation/recent", params={"limit": 3}),
        )


if __name__ == "__main__":
    main()
