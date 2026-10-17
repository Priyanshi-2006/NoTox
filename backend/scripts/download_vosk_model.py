"""
Utility script to download and unpack the small English Vosk model.
Target model: vosk-model-small-en-us-0.15 (~40 MB)
Target directory: backend/models/vosk-model-small-en-us-0.15
"""

import os
import sys
import urllib.request
import zipfile
from pathlib import Path

MODEL_NAME = "vosk-model-small-en-us-0.15"
MODEL_URL = f"https://alphacephei.com/vosk/models/{MODEL_NAME}.zip"

BACKEND_DIR = Path(__file__).resolve().parent.parent
MODELS_DIR = BACKEND_DIR / "models"
TARGET_DIR = MODELS_DIR / MODEL_NAME


def download_model(force: bool = False) -> Path:
    if TARGET_DIR.exists() and not force:
        print(f"[Vosk Setup] Model directory already exists at: {TARGET_DIR}")
        return TARGET_DIR

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = MODELS_DIR / f"{MODEL_NAME}.zip"

    print(f"[Vosk Setup] Downloading {MODEL_NAME} from {MODEL_URL}...")
    urllib.request.urlretrieve(MODEL_URL, zip_path)

    print(f"[Vosk Setup] Extracting to {MODELS_DIR}...")
    with zipfile.ZipFile(zip_path, "r") as zip_ref:
        zip_ref.extractall(MODELS_DIR)

    if zip_path.exists():
        try:
            os.remove(zip_path)
        except OSError:
            pass

    if not TARGET_DIR.exists():
        raise RuntimeError(f"Extraction completed but {TARGET_DIR} not found.")

    print(f"[Vosk Setup] Model successfully installed at {TARGET_DIR}")
    return TARGET_DIR


if __name__ == "__main__":
    force_flag = "--force" in sys.argv
    try:
        download_model(force=force_flag)
    except Exception as exc:
        print(f"[Vosk Setup Error] {exc}", file=sys.stderr)
        sys.exit(1)
