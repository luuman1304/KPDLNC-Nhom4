from __future__ import annotations

from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[4]
APP_DIR = ROOT_DIR / "app"
ARTIFACT_DIR = APP_DIR / "artifacts"
SAMPLE_DATA_DIR = APP_DIR / "sample_data"

FORECAST_HORIZON = 28
MIN_HISTORY_DAYS = 28
SUPPORTED_MODELS = {
    "A0": "A0_global_baseline",
    "B1": "B1_cluster_label",
    "C": "C_cluster_specific",
}

