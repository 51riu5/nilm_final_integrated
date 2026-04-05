"""
NILM Seq2Seq CNN model for energy disaggregation.

Extracted from UKDALE_DL_Training.ipynb — 1D CNN with residual blocks
that maps aggregate mains power to per-appliance power estimates.
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

class ResidualBlock(nn.Module):
    """Residual block with batch normalisation and optional channel projection."""

    def __init__(
        self,
        in_channels: int,
        out_channels: int,
        kernel_size: int,
        dropout_rate: float = 0.2,
    ) -> None:
        super().__init__()
        self.conv1 = nn.Conv1d(
            in_channels, out_channels, kernel_size, stride=1, padding=kernel_size // 2
        )
        self.bn1 = nn.BatchNorm1d(out_channels)
        self.relu = nn.ReLU()
        self.dropout = nn.Dropout(dropout_rate)

        self.projection: nn.Module | None = None
        if in_channels != out_channels:
            self.projection = nn.Sequential(
                nn.Conv1d(in_channels, out_channels, kernel_size=1),
                nn.BatchNorm1d(out_channels),
            )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        identity = x

        out = self.conv1(x)
        out = self.bn1(out)
        out = self.relu(out)
        out = self.dropout(out)

        if self.projection is not None:
            identity = self.projection(identity)

        if out.size(2) != identity.size(2):
            out = out[:, :, : identity.size(2)]

        out = out + identity
        return self.relu(out)


class Seq2PointCNN(nn.Module):
    """
    Sequence-to-sequence 1-D CNN for NILM.

    Progressive filter widths with residual connections, batch normalisation,
    and a 1×1 output convolution that preserves temporal resolution.
    """

    def __init__(
        self,
        seq_length: int = 599,
        num_targets: int = 2,
        conv_filters: list[int] | None = None,
        kernel_sizes: list[int] | None = None,
        dropout_rate: float = 0.2,
    ) -> None:
        super().__init__()
        if conv_filters is None:
            conv_filters = [30, 30, 40, 50, 50]
        if kernel_sizes is None:
            kernel_sizes = [10, 8, 6, 5, 5]

        self.seq_length = seq_length
        self.num_targets = num_targets

        self.initial_conv = nn.Sequential(
            nn.Conv1d(1, conv_filters[0], kernel_sizes[0], stride=1, padding=kernel_sizes[0] // 2),
            nn.BatchNorm1d(conv_filters[0]),
            nn.ReLU(),
        )

        self.residual_blocks = nn.ModuleList()
        for i in range(len(conv_filters) - 1):
            self.residual_blocks.append(
                ResidualBlock(conv_filters[i], conv_filters[i + 1], kernel_sizes[i + 1], dropout_rate)
            )

        self.dropout = nn.Dropout(dropout_rate)

        with torch.no_grad():
            dummy = torch.zeros(1, 1, seq_length)
            x = self.initial_conv(dummy)
            for block in self.residual_blocks:
                x = block(x)
            self.conv_out_channels = x.size(1)

        self.output_conv = nn.Conv1d(self.conv_out_channels, num_targets, kernel_size=1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (batch, seq_length, 1) -> permute to (batch, 1, seq_length)
        x = x.permute(0, 2, 1)
        x = self.initial_conv(x)
        for block in self.residual_blocks:
            x = block(x)
        x = self.dropout(x)
        x = self.output_conv(x)
        if x.size(2) != self.seq_length:
            x = x[:, :, : self.seq_length]
        # back to (batch, seq_length, num_targets)
        return x.permute(0, 2, 1)


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
) -> tuple["Seq2PointCNN", dict[str, Any]]:
    """Load a trained model checkpoint and its metadata.

    Returns ``(model_in_eval_mode, metadata_dict)``.
    """
    if device is None:
        device = torch.device("cpu")

    metadata = load_metadata(metadata_path)
    num_targets = len(metadata["appliances"])

    model = Seq2PointCNN(
        seq_length=metadata["seq_length"],
        num_targets=num_targets,
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
    model: Seq2PointCNN,
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
        output = model(tensor)  # (1, seq_len, num_targets)

    output_np = output.cpu().numpy()[0]  # (seq_len, num_targets)

    results: dict[str, np.ndarray] = {}
    for i, name in enumerate(metadata["appliances"]):
        results[name] = denormalize_appliance(output_np[:, i], name, metadata)

    return results
