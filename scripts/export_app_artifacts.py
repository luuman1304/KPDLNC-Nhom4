from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUN = ROOT / os.environ.get("APP_ARTIFACT_SOURCE_RUN", "outputs_full_k3_seed42_tweedie_a0_b1_c")
APP_ARTIFACTS = ROOT / "app" / "artifacts"


def copy_if_exists(src: Path, dst: Path) -> bool:
    if not src.exists():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return True


def main() -> None:
    metrics_dir = DEFAULT_RUN / "metrics"
    copied = {}
    copied["cluster_profiles"] = copy_if_exists(
        metrics_dir / "cluster_profiles.csv",
        APP_ARTIFACTS / "metadata" / "cluster_profiles.csv",
    )
    copied["model_metric_summary"] = copy_if_exists(
        metrics_dir / "model_test_metrics.csv",
        APP_ARTIFACTS / "metadata" / "model_metric_summary.csv",
    )

    model_files = list((DEFAULT_RUN / "models").glob("**/*")) if (DEFAULT_RUN / "models").exists() else []
    model_files = [p for p in model_files if p.is_file()]
    for model_file in model_files:
        relative = model_file.relative_to(DEFAULT_RUN / "models")
        copy_if_exists(model_file, APP_ARTIFACTS / "models" / relative)
    copied["trained_model_artifacts_found"] = len(model_files) > 0

    manifest = {
        "version": "0.1.0",
        "mode": "artifact_available" if copied["trained_model_artifacts_found"] else "demo",
        "source_run": str(DEFAULT_RUN.relative_to(ROOT)),
        "copied": copied,
        "note": (
            "No trained model files were found in the selected research output. "
            "Backend will run in demo mode until LightGBM/scaler/encoder/clustering artifacts are exported."
        )
        if not copied["trained_model_artifacts_found"]
        else (
            "Trained artifacts were exported. Backend still needs the production LightGBM inference adapter "
            "to use these artifacts instead of the demo forecaster."
        ),
    }
    (APP_ARTIFACTS / "metadata").mkdir(parents=True, exist_ok=True)
    (APP_ARTIFACTS / "metadata" / "artifact_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(json.dumps(manifest, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
