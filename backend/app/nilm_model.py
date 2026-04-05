"""
NNAN — Progressive Multi-Appliance Neural Network for NILM.

Implements the architecture described in the project report:
  InceptionBlock (multi-scale Conv1d) → BatchNorm → LSTM → FC
with progressive residual learning for sequential appliance disaggregation.

Sequence-to-point learning: a window of aggregate power predicts the
appliance consumption at the midpoint of the window.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import torch
import torch.nn as nn


# ---------------------------------------------------------------------------
# Model architecture
# ---------------------------------------------------------------------------

class InceptionBlock(nn.Module):
    """Multi-scale feature extraction with parallel 1-D convolutions.

    Three parallel branches with kernel sizes 3, 5, and 7 capture features
    at different temporal resolutions.  Outputs are concatenated along the
    channel dimension.
    """

    def __init__(
        self,
        in_channels: int,
        out_channels_per_branch: int = 16,
        dropout_rate: float = 0.2,
    ) -> None:
        super().__init__()
        self.branch3 = nn.Sequential(
            nn.Conv1d(in_channels, out_channels_per_branch, kernel_size=3, padding=1),
            nn.BatchNorm1d(out_channels_per_branch),
            nn.ReLU(),
        )
        self.branch5 = nn.Sequential(
            nn.Conv1d(in_channels, out_channels_per_branch, kernel_size=5, padding=2),
            nn.BatchNorm1d(out_channels_per_branch),
            nn.ReLU(),
        )
        self.branch7 = nn.Sequential(
            nn.Conv1d(in_channels, out_channels_per_branch, kernel_size=7, padding=3),
            nn.BatchNorm1d(out_channels_per_branch),
            nn.ReLU(),
        )
        self.dropout = nn.Dropout(dropout_rate)

    @property
    def total_out_channels(self) -> int:
        return sum(
            b[0].out_channels for b in [self.branch3, self.branch5, self.branch7]
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (batch, in_channels, seq_len)
        b3 = self.branch3(x)
        b5 = self.branch5(x)
        b7 = self.branch7(x)
        out = torch.cat([b3, b5, b7], dim=1)  # (batch, 3 * out_ch, seq_len)
        return self.dropout(out)


class SubDisaggregator(nn.Module):
    """Single-appliance disaggregator.

    Pipeline: InceptionBlock → BatchNorm → LSTM → FC
    Predicts the midpoint power consumption (sequence-to-point).
    """

    def __init__(
        self,
        seq_length: int = 599,
        inception_channels: int = 16,
        lstm_hidden: int = 64,
        dropout_rate: float = 0.2,
    ) -> None:
        super().__init__()
        self.seq_length = seq_length

        self.inception = InceptionBlock(1, inception_channels, dropout_rate)
        total_inc = inception_channels * 3  # three branches concatenated

        self.bn = nn.BatchNorm1d(total_inc)

        self.lstm = nn.LSTM(
            input_size=total_inc,
            hidden_size=lstm_hidden,
            num_layers=1,
            batch_first=True,
            dropout=0,
        )

        self.fc = nn.Sequential(
            nn.Linear(lstm_hidden, 32),
            nn.ReLU(),
            nn.Dropout(dropout_rate),
            nn.Linear(32, 1),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (batch, seq_length, 1)
        x = x.permute(0, 2, 1)           # (batch, 1, seq_length)
        x = self.inception(x)            # (batch, 3*inc_ch, seq_length)
        x = self.bn(x)                   # (batch, 3*inc_ch, seq_length)
        x = x.permute(0, 2, 1)           # (batch, seq_length, 3*inc_ch)

        lstm_out, _ = self.lstm(x)        # (batch, seq_length, lstm_hidden)

        # Sequence-to-point: take the midpoint output
        mid_idx = lstm_out.size(1) // 2
        mid_repr = lstm_out[:, mid_idx, :]  # (batch, lstm_hidden)

        out = self.fc(mid_repr)           # (batch, 1)
        return out.squeeze(-1)            # (batch,)


class NNAN(nn.Module):
    """Progressive Multi-Appliance Neural Network for NILM.

    Contains one ``SubDisaggregator`` per target appliance.  During the
    forward pass, progressive residual learning is applied: each
    sub-disaggregator predicts one appliance's consumption and the
    prediction is subtracted from the aggregate before passing the
    residual to the next sub-disaggregator.

    Parameters
    ----------
    seq_length : int
        Number of time-steps in the input window.
    num_appliances : int
        Number of target appliances.
    inception_channels : int
        Output channels per branch in the InceptionBlock.
    lstm_hidden : int
        Hidden size of the LSTM layer.
    dropout_rate : float
        Dropout probability used throughout.
    """

    def __init__(
        self,
        seq_length: int = 599,
        num_appliances: int = 2,
        inception_channels: int = 16,
        lstm_hidden: int = 64,
        dropout_rate: float = 0.2,
    ) -> None:
        super().__init__()
        self.seq_length = seq_length
        self.num_appliances = num_appliances

        self.sub_disaggregators = nn.ModuleList([
            SubDisaggregator(
                seq_length=seq_length,
                inception_channels=inception_channels,
                lstm_hidden=lstm_hidden,
                dropout_rate=dropout_rate,
            )
            for _ in range(num_appliances)
        ])

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (batch, seq_length, 1)
        residual = x
        predictions: list[torch.Tensor] = []

        for sub_disagg in self.sub_disaggregators:
            pred = sub_disagg(residual)        # (batch,)
            predictions.append(pred)

            # Progressive residual: subtract predicted power from aggregate
            # Broadcast the scalar prediction across the sequence dimension
            pred_expanded = pred.unsqueeze(1).unsqueeze(2)  # (batch, 1, 1)
            residual = residual - pred_expanded

        # (batch, num_appliances)
        return torch.stack(predictions, dim=1)


# ---------------------------------------------------------------------------
# Backward-compatible alias so existing references still resolve
# ---------------------------------------------------------------------------

Seq2PointCNN = NNAN


# ---------------------------------------------------------------------------
# Metadata helpers
# ---------------------------------------------------------------------------

def load_metadata(metadata_path: str | Path) -> dict[str, Any]:
    with open(metadata_path, "r") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Model loading
# ---------------------------------------------------------------------------

def load_nilm_model(
    weights_path: str | Path,
    metadata_path: str | Path,
    device: torch.device | None = None,
) -> tuple["NNAN", dict[str, Any]]:
    """Load a trained model checkpoint and its metadata.

    Returns ``(model_in_eval_mode, metadata_dict)``.
    """
    if device is None:
        device = torch.device("cpu")

    metadata = load_metadata(metadata_path)
    num_targets = len(metadata["appliances"])

    model = NNAN(
        seq_length=metadata["seq_length"],
        num_appliances=num_targets,
    )

    checkpoint = torch.load(weights_path, map_location=device, weights_only=False)
    state = checkpoint.get("model_state_dict", checkpoint)
    model.load_state_dict(state)
    model.to(device)
    model.eval()
    return model, metadata


# ---------------------------------------------------------------------------
# Inference helpers
# ---------------------------------------------------------------------------

def normalize_mains(raw: np.ndarray, metadata: dict[str, Any]) -> np.ndarray:
    stats = metadata["normalization"]["mains"]
    return (raw - stats["mean"]) / (stats["std"] + 1e-8)


def denormalize_appliance(
    normalised: np.ndarray,
    appliance_name: str,
    metadata: dict[str, Any],
) -> np.ndarray:
    stats = metadata["normalization"]["appliances"][appliance_name]
    out = normalised * stats["std"] + stats["mean"]
    return np.clip(out, 0, None)


def predict(
    model: NNAN,
    raw_power: np.ndarray,
    metadata: dict[str, Any],
    device: torch.device | None = None,
) -> dict[str, np.ndarray]:
    """Run disaggregation on a raw aggregate power array.

    Parameters
    ----------
    raw_power : 1-D array of length ``seq_length`` (watts, un-normalised).

    Returns
    -------
    dict mapping appliance name -> 1-D array of estimated power (watts).
    Each array has length 1 (sequence-to-point prediction).
    """
    if device is None:
        device = torch.device("cpu")

    seq_len = metadata["seq_length"]
    raw_power = np.asarray(raw_power, dtype=np.float32)
    if raw_power.shape[0] != seq_len:
        raise ValueError(f"Expected {seq_len} samples, got {raw_power.shape[0]}")

    normed = normalize_mains(raw_power, metadata)
    tensor = torch.tensor(normed, dtype=torch.float32).reshape(1, seq_len, 1).to(device)

    with torch.no_grad():
        output = model(tensor)  # (1, num_appliances)

    output_np = output.cpu().numpy()[0]  # (num_appliances,)

    results: dict[str, np.ndarray] = {}
    for i, name in enumerate(metadata["appliances"]):
        results[name] = denormalize_appliance(
            np.array([output_np[i]]), name, metadata
        )

    return results
