"""
Train the NNAN (Progressive Multi-Appliance Neural Network) on UK-DALE data.

Produces ``models/best_model_both.pth`` ready for the inference engine.

Usage:
    python setup_data.py   # download data first (if not already present)
    python train_model.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader

# Ensure the app package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.nilm_model import NNAN

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DATA_DIR = Path("data") / "dl_ready"
OUTPUT_DIR = Path("models")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

BATCH_SIZE = 500
LEARNING_RATE = 0.001
NUM_EPOCHS = 100
PATIENCE = 15
DROPOUT_RATE = 0.2

# NNAN architecture hyper-parameters
INCEPTION_CHANNELS = 16
LSTM_HIDDEN = 64

USE_CLASS_WEIGHTS = True
ON_THRESHOLD_PHYSICAL = 50  # watts
ON_CLASS_WEIGHT = 10.0

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
SEED = 42


# ---------------------------------------------------------------------------
# Dataset — Sequence-to-Point: target is the midpoint of each window
# ---------------------------------------------------------------------------

class NILMDataset(Dataset):
    def __init__(self, X: np.ndarray, y: np.ndarray) -> None:
        self.X = torch.FloatTensor(X)
        # Sequence-to-point: extract midpoint target from full sequence
        mid = y.shape[1] // 2
        self.y = torch.FloatTensor(y[:, mid, :])  # (N, num_appliances)

    def __len__(self) -> int:
        return len(self.X)

    def __getitem__(self, idx: int):
        return self.X[idx], self.y[idx]


# ---------------------------------------------------------------------------
# Training loop
# ---------------------------------------------------------------------------

def train_epoch(model, loader, optimizer, device, on_threshold, on_weight):
    model.train()
    mse_fn = nn.MSELoss(reduction="none")
    mae_fn = nn.L1Loss(reduction="none")
    total_loss = 0.0

    for inputs, targets in loader:
        inputs, targets = inputs.to(device), targets.to(device)
        optimizer.zero_grad()
        outputs = model(inputs)  # (batch, num_appliances)

        if USE_CLASS_WEIGHTS:
            weights = torch.where(
                targets > on_threshold,
                torch.tensor(on_weight, device=device),
                torch.tensor(1.0, device=device),
            )
            loss = 0.7 * torch.mean(weights * mse_fn(outputs, targets)) + \
                   0.3 * torch.mean(weights * mae_fn(outputs, targets))
        else:
            loss = nn.functional.mse_loss(outputs, targets)

        loss.backward()
        nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
        optimizer.step()
        total_loss += loss.item()

    return total_loss / len(loader)


def validate_epoch(model, loader, device):
    model.eval()
    total_loss = 0.0
    with torch.no_grad():
        for inputs, targets in loader:
            inputs, targets = inputs.to(device), targets.to(device)
            outputs = model(inputs)
            total_loss += nn.functional.mse_loss(outputs, targets).item()
    return total_loss / len(loader)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    np.random.seed(SEED)
    torch.manual_seed(SEED)

    print("=" * 70)
    print("NNAN Model Training (Progressive Multi-Appliance Neural Network)")
    print("=" * 70)
    print(f"Device: {DEVICE}")

    # -- Load data ----------------------------------------------------------
    train_path = DATA_DIR / "train.npz"
    val_path = DATA_DIR / "val.npz"
    meta_path = DATA_DIR / "metadata.json"

    for p in (train_path, val_path, meta_path):
        if not p.exists():
            print(f"Missing: {p}  — run  python setup_data.py  first.")
            sys.exit(1)

    train_data = np.load(train_path)
    val_data = np.load(val_path)
    with open(meta_path) as f:
        metadata = json.load(f)

    X_train, y_train = train_data["X"], train_data["y"]
    X_val, y_val = val_data["X"], val_data["y"]

    num_targets = y_train.shape[2]
    seq_length = X_train.shape[1]
    appliances = metadata["appliances"]

    print(f"Appliances: {appliances}")
    print(f"Train: {X_train.shape[0]:,} samples  |  Val: {X_val.shape[0]:,} samples")
    print(f"Seq length: {seq_length}  |  Targets: {num_targets}")
    print(f"Learning: Sequence-to-Point (midpoint index {seq_length // 2})")

    # -- Normalised ON threshold --------------------------------------------
    on_thresholds = []
    for app_name in appliances:
        stats = metadata["normalization"]["appliances"][app_name]
        on_thresholds.append(
            (ON_THRESHOLD_PHYSICAL - stats["mean"]) / (stats["std"] + 1e-8)
        )
    on_threshold_tensor = min(on_thresholds)

    # -- Datasets -----------------------------------------------------------
    train_loader = DataLoader(
        NILMDataset(X_train, y_train), batch_size=BATCH_SIZE, shuffle=True, num_workers=0
    )
    val_loader = DataLoader(
        NILMDataset(X_val, y_val), batch_size=BATCH_SIZE, shuffle=False, num_workers=0
    )

    # -- Model --------------------------------------------------------------
    model = NNAN(
        seq_length=seq_length,
        num_appliances=num_targets,
        inception_channels=INCEPTION_CHANNELS,
        lstm_hidden=LSTM_HIDDEN,
        dropout_rate=DROPOUT_RATE,
    ).to(DEVICE)

    total_params = sum(p.numel() for p in model.parameters())
    print(f"Model parameters: {total_params:,}")
    print(f"Architecture: NNAN with {num_targets} sub-disaggregators")
    print(f"  Inception channels: {INCEPTION_CHANNELS} per branch")
    print(f"  LSTM hidden: {LSTM_HIDDEN}\n")

    optimizer = optim.Adam(model.parameters(), lr=LEARNING_RATE)
    scheduler = optim.lr_scheduler.ReduceLROnPlateau(
        optimizer, mode="min", factor=0.5, patience=3, min_lr=1e-6
    )

    # -- Training -----------------------------------------------------------
    best_val_loss = float("inf")
    patience_counter = 0
    best_path = OUTPUT_DIR / "best_model_both.pth"

    for epoch in range(1, NUM_EPOCHS + 1):
        train_loss = train_epoch(
            model, train_loader, optimizer, DEVICE, on_threshold_tensor, ON_CLASS_WEIGHT
        )
        val_loss = validate_epoch(model, val_loader, DEVICE)
        lr = optimizer.param_groups[0]["lr"]
        scheduler.step(val_loss)

        improved = ""
        if val_loss < best_val_loss:
            best_val_loss = val_loss
            patience_counter = 0
            torch.save(
                {
                    "model_state_dict": model.state_dict(),
                    "optimizer_state_dict": optimizer.state_dict(),
                    "epoch": epoch,
                    "val_loss": val_loss,
                    "train_loss": train_loss,
                    "appliances": appliances,
                    "seq_length": seq_length,
                    "num_targets": num_targets,
                },
                best_path,
            )
            improved = " *"
        else:
            patience_counter += 1

        print(
            f"Epoch {epoch:3d}/{NUM_EPOCHS}  "
            f"train={train_loss:.6f}  val={val_loss:.6f}  "
            f"lr={lr:.2e}  patience={patience_counter}/{PATIENCE}{improved}"
        )

        if patience_counter >= PATIENCE:
            print(f"\nEarly stopping at epoch {epoch}")
            break

    print(f"\nBest validation loss: {best_val_loss:.6f}")
    print(f"Model saved to: {best_path}")

    # Copy metadata beside the model
    meta_dst = OUTPUT_DIR / "metadata.json"
    meta_dst.write_text(json.dumps(metadata, indent=2))
    print(f"Metadata saved to: {meta_dst}")
    print("Done.\n")


if __name__ == "__main__":
    main()
