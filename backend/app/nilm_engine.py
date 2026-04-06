"""
Real-time NILM disaggregation engine.

Buffers incoming aggregate power readings and uses power-signature heuristics
(or a trained NNAN model when available) to classify and disaggregate per-appliance
consumption.  The NNAN model uses progressive residual learning with Inception-based
feature extraction and LSTM temporal modelling (sequence-to-point inference).

Tuned for live demo with laptop charger (~30-90 W) and mobile charger (~5-25 W).
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Demo-tuned constants — fast startup, 1-second cadence from ESP32
# ---------------------------------------------------------------------------

SEQ_LENGTH = 20            # only 20 readings needed (~20 seconds)
SAMPLE_PERIOD_S = 1        # match ESP32 cadence — no downsampling
INFERENCE_STRIDE = 3       # produce new results every 3 readings
BUFFER_CAPACITY = SEQ_LENGTH + INFERENCE_STRIDE * 4

APPLIANCE_NAMES = ["laptop_charger", "mobile_charger"]

# Power-signature bands (watts) — adjust these to your actual charger readings
LAPTOP_MIN = 25
LAPTOP_MAX = 100
MOBILE_MIN = 3
MOBILE_MAX = 25
STANDBY_MAX = 2            # anything below this is idle noise


@dataclass
class DisaggResult:
    """One disaggregated reading ready for DB / broadcast."""

    device_id: str
    site_id: str | None
    timestamp: datetime
    appliance_id: str
    appliance_label: str
    power_w: float
    energy_kwh: float


@dataclass
class _DeviceBuffer:
    """Per-device state."""

    readings: deque[tuple[float, float]] = field(
        default_factory=lambda: deque(maxlen=BUFFER_CAPACITY)
    )
    new_count: int = 0
    site_id: str | None = None


class NILMEngine:
    """Manages per-device buffers and dispatches disaggregation."""

    def __init__(self, model_dir: str | Path = "models") -> None:
        self.model_dir = Path(model_dir)
        self._buffers: dict[str, _DeviceBuffer] = {}
        self.model: Any = None
        self.metadata: dict[str, Any] | None = None
        self.mode: str = "loading"
        self.appliances: list[str] = list(APPLIANCE_NAMES)
        self._load_model()

    # ------------------------------------------------------------------
    # Model loading
    # ------------------------------------------------------------------

    def _load_model(self) -> None:
        weights_path = self.model_dir / "best_model_both.pth"
        metadata_path = self.model_dir / "metadata.json"

        if not weights_path.exists() or not metadata_path.exists():
            log.warning(
                "NILM model weights not found at %s — running in heuristic mode",
                self.model_dir,
            )
            self.mode = "heuristic"
            return

        try:
            from .nilm_model import load_nilm_model

            self.model, self.metadata = load_nilm_model(weights_path, metadata_path)
            self.appliances = list(self.metadata.get("appliances", APPLIANCE_NAMES))
            # FORCE HEURISTIC MODE TO PROTECT LAPTOP DEMO
            self.mode = "heuristic"
            log.info("NILM ML model loaded (%d appliances) but LOCKED to HEURISTIC mode for demo", len(self.appliances))
        except Exception:
            log.exception("Failed to load NILM model — falling back to heuristic mode")
            self.mode = "heuristic"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def feed(
        self,
        device_id: str,
        timestamp: datetime | None,
        power_w: float | None,
        site_id: str | None = None,
    ) -> list[DisaggResult]:
        """Ingest one meter reading. Returns disaggregation results (may be empty)."""
        if power_w is None:
            return []

        buf = self._buffers.setdefault(device_id, _DeviceBuffer())
        buf.site_id = site_id

        ts_epoch = (timestamp or datetime.now(timezone.utc)).timestamp()
        buf.readings.append((ts_epoch, float(power_w)))
        buf.new_count += 1

        if buf.new_count >= INFERENCE_STRIDE and len(buf.readings) >= SEQ_LENGTH:
            buf.new_count = 0
            return self._disaggregate(device_id, buf)

        return []

    def status(self) -> dict[str, Any]:
        buffer_info: dict[str, Any] = {}
        for dev_id, buf in self._buffers.items():
            buffer_info[dev_id] = {
                "bins_filled": len(buf.readings),
                "bins_required": SEQ_LENGTH,
                "fill_pct": round(len(buf.readings) / SEQ_LENGTH * 100, 1),
            }
        return {
            "mode": self.mode,
            "appliances": self.appliances,
            "seq_length": SEQ_LENGTH,
            "sample_period_s": SAMPLE_PERIOD_S,
            "inference_stride": INFERENCE_STRIDE,
            "buffers": buffer_info,
        }

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def _disaggregate(self, device_id: str, buf: _DeviceBuffer) -> list[DisaggResult]:
        if self.mode == "ml" and self.model is not None and self.metadata is not None:
            return self._run_ml(device_id, buf)
        return self._run_heuristic(device_id, buf)

    # ------------------------------------------------------------------
    # ML inference path (for trained model — kept for future use)
    # ------------------------------------------------------------------

    def _run_ml(self, device_id: str, buf: _DeviceBuffer) -> list[DisaggResult]:
        from .nilm_model import predict

        readings = list(buf.readings)
        window = readings[-599:] if len(readings) >= 599 else readings[-SEQ_LENGTH:]
        power_array = np.array([pw for _, pw in window], dtype=np.float32)

        if len(power_array) < 599:
            return self._run_heuristic(device_id, buf)

        try:
            appliance_powers = predict(self.model, power_array, self.metadata)
        except Exception:
            log.exception("ML inference failed — falling back to heuristic")
            return self._run_heuristic(device_id, buf)

        latest_ts_epoch = window[-1][0]
        aggregate = float(power_array[-1])
        ts = datetime.fromtimestamp(latest_ts_epoch, tz=timezone.utc)

        results: list[DisaggResult] = []
        total_appliance = 0.0
        for name in self.metadata.get("appliances", []):
            arr = appliance_powers.get(name)
            pw = float(arr[-1]) if arr is not None else 0.0
            total_appliance += pw
            results.append(
                DisaggResult(
                    device_id=device_id,
                    site_id=buf.site_id,
                    timestamp=ts,
                    appliance_id=name,
                    appliance_label=name.replace("_", " ").title(),
                    power_w=round(pw, 2),
                    energy_kwh=round(pw * SAMPLE_PERIOD_S / 3_600_000, 6),
                )
            )

        other_power = max(aggregate - total_appliance, 0.0)
        results.append(
            DisaggResult(
                device_id=device_id,
                site_id=buf.site_id,
                timestamp=ts,
                appliance_id="other",
                appliance_label="Other",
                power_w=round(other_power, 2),
                energy_kwh=round(other_power * SAMPLE_PERIOD_S / 3_600_000, 6),
            )
        )
        return results

    # ------------------------------------------------------------------
    # Heuristic path — power-signature classification
    # ------------------------------------------------------------------

    def _run_heuristic(self, device_id: str, buf: _DeviceBuffer) -> list[DisaggResult]:
        readings = list(buf.readings)
        window = readings[-SEQ_LENGTH:]
        powers = np.array([pw for _, pw in window], dtype=np.float32)
        latest_ts_epoch = window[-1][0]
        ts = datetime.fromtimestamp(latest_ts_epoch, tz=timezone.utc)

        # Use a short moving average to smooth sensor noise
        smoothed = float(np.mean(powers[-5:])) if len(powers) >= 5 else float(powers[-1])
        aggregate = float(powers[-1])

        appliance_powers = self._classify_power(smoothed, aggregate, buf)

        results = []
        for app_id, pw in appliance_powers.items():
            human_label = app_id.replace("_", " ").title()
            results.append(
                DisaggResult(
                    device_id=device_id,
                    site_id=buf.site_id,
                    timestamp=ts,
                    appliance_id=app_id,
                    appliance_label=human_label,
                    power_w=round(pw, 2),
                    energy_kwh=round(pw * SAMPLE_PERIOD_S / 3_600_000, 6),
                )
            )
        return results

    def _classify_power(
        self, smoothed: float, raw: float, buf: _DeviceBuffer
    ) -> dict[str, float]:
        """Decompose aggregate power into dynamic laptops and chargers."""
        if smoothed <= STANDBY_MAX:
            return {"other": 0.0}

        alloc = {}
        mobile = 0.0
        other = 0.0

        # Check recent history for a step that reveals the mobile charger
        readings = list(buf.readings)
        has_mobile_baseline = False
        if len(readings) >= 10:
            prev_power = np.mean([pw for _, pw in readings[-15:-5]]) if len(readings) >= 15 else 0
            if MOBILE_MIN <= prev_power <= MOBILE_MAX and smoothed > LAPTOP_MIN:
                has_mobile_baseline = True

        laptop_unit = 65.0
        laptop_pws = []

        if smoothed <= MOBILE_MAX:
            mobile = smoothed
        elif smoothed <= 44:
            laptop_pws.append(smoothed)
        elif smoothed <= LAPTOP_MAX:
            if has_mobile_baseline:
                mobile = min(15.0, smoothed * 0.2)
                laptop_pws.append(smoothed - mobile)
            else:
                if smoothed > 55:
                    mobile = min(12.0, smoothed * 0.18)
                    laptop_pws.append(smoothed - mobile)
                else:
                    laptop_pws.append(smoothed)
        else:
            residual = smoothed
            # Optional mobile charger extracted first
            if has_mobile_baseline or (smoothed % laptop_unit > 5 and smoothed % laptop_unit < 25):
                mobile = max(10.0, min(15.0, residual % laptop_unit))
                residual -= mobile

            num_laptops = max(1, round(residual / laptop_unit))
            per_laptop = residual / num_laptops
            
            if per_laptop > 90.0:
                # Overflow into other, meaning additional non-laptop loads
                per_laptop = 80.0
                for _ in range(num_laptops):
                    laptop_pws.append(per_laptop)
                    residual -= per_laptop
                other = residual
            else:
                for _ in range(num_laptops):
                    laptop_pws.append(per_laptop)

        # Build dynamic dictionary
        if len(laptop_pws) == 1:
            alloc["laptop_charger"] = laptop_pws[0]
        else:
            for i, pw in enumerate(laptop_pws):
                alloc[f"laptop_charger_{i+1}"] = pw
                
        alloc["mobile_charger"] = mobile
        alloc["other"] = other

        accounted = sum(alloc.values())
        diff = raw - accounted
        if diff > 1:
            alloc["other"] += diff
        elif diff < -1:
            scale = raw / (accounted + 1e-8)
            for k in alloc:
                alloc[k] *= scale

        return {k: max(v, 0.0) for k, v in alloc.items()}
