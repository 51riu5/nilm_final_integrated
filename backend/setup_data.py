"""
Download NILM training data and metadata from the GitHub repository.

Usage:
    python setup_data.py
"""

import os
import sys
import urllib.request
from pathlib import Path

REPO_BASE = (
    "https://raw.githubusercontent.com/Akashprasad123/NILM/main"
    "/Tutorial/Dataset/UKDALE_Processed/dl_ready"
)

FILES = ["train.npz", "val.npz", "metadata.json"]

DATA_DIR = Path("data") / "dl_ready"
MODELS_DIR = Path("models")


def download(url: str, dest: Path) -> None:
    print(f"  Downloading {url}")
    print(f"         -> {dest}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(url, str(dest))
    size_kb = dest.stat().st_size / 1024
    print(f"         OK ({size_kb:.1f} KB)")


def main() -> None:
    print("=" * 60)
    print("NILM Data Setup")
    print("=" * 60)

    for name in FILES:
        url = f"{REPO_BASE}/{name}"
        dest = DATA_DIR / name
        if dest.exists():
            print(f"  [skip] {dest} already exists")
            continue
        try:
            download(url, dest)
        except Exception as exc:
            print(f"  [FAIL] {name}: {exc}", file=sys.stderr)
            sys.exit(1)

    # Copy metadata.json into models/ so the inference engine can find it
    src = DATA_DIR / "metadata.json"
    dst = MODELS_DIR / "metadata.json"
    if src.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(src.read_bytes())
        print(f"\n  Copied metadata.json -> {dst}")

    print("\nDone. Training data is in:", DATA_DIR)
    print("Run  python train_model.py  to train the NILM model.\n")


if __name__ == "__main__":
    main()
