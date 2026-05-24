from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


SEEDS = [42, 52, 62, 72, 82]
CONFIG_TEMPLATE = "configs/research_config_full_multiseed_k3_seed{seed}_tweedie_a0_b1_c.json"
REQUIRED_OUTPUTS = [
    "metrics/model_test_metrics.csv",
    "metrics/sampled_wrmsse_overall.csv",
    "metrics/forecast_stability_metrics.csv",
    "metrics/overfitting_gap_summary.csv",
    "metrics/feature_importance_by_origin.csv",
    "metrics/test_forecasts.parquet",
]


def completed(config_path: Path) -> bool:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    out_dir = Path(config["outputs_dir"])
    return all((out_dir / rel).exists() for rel in REQUIRED_OUTPUTS)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="rerun even when required outputs exist")
    args = parser.parse_args()

    for seed in SEEDS:
        config_path = Path(CONFIG_TEMPLATE.format(seed=seed))
        if not config_path.exists():
            raise FileNotFoundError(config_path)
        if completed(config_path) and not args.force:
            print(f"[skip] seed={seed} already completed")
            continue
        print(f"[run] seed={seed} config={config_path}", flush=True)
        subprocess.run(
            [sys.executable, "src/m5_research_pipeline.py", "--config", str(config_path)],
            check=True,
        )
        print(f"[done] seed={seed}", flush=True)


if __name__ == "__main__":
    main()
