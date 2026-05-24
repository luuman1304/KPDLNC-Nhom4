from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr


def md_table(df: pd.DataFrame) -> str:
    if df.empty:
        return "(empty)"
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
    for _, row in df.iterrows():
        vals = []
        for col in cols:
            val = row[col]
            vals.append(f"{val:.6g}" if isinstance(val, float) else str(val))
        lines.append("| " + " | ".join(vals) + " |")
    return "\n".join(lines)


def aggregate_importance(fi: pd.DataFrame) -> pd.DataFrame:
    # For cluster-specific model, average cluster model importances per origin.
    agg = (
        fi.groupby(["origin", "model", "feature"])
        .agg(importance_gain=("importance_gain", "mean"), importance_split=("importance_split", "mean"))
        .reset_index()
    )
    return agg


def drift_rows(fi: pd.DataFrame, top_n: int) -> pd.DataFrame:
    agg = aggregate_importance(fi)
    rows = []
    for model, model_df in agg.groupby("model"):
        origins = sorted(model_df["origin"].unique())
        for prev, cur in zip(origins[:-1], origins[1:]):
            prev_df = model_df.loc[model_df["origin"] == prev]
            cur_df = model_df.loc[model_df["origin"] == cur]
            top_features = (
                prev_df.sort_values("importance_gain", ascending=False)
                .head(top_n)["feature"]
                .tolist()
            )
            merged = (
                pd.DataFrame({"feature": top_features})
                .merge(prev_df[["feature", "importance_gain"]], on="feature", how="left")
                .merge(cur_df[["feature", "importance_gain"]], on="feature", how="left", suffixes=("_prev", "_cur"))
                .fillna(0.0)
            )
            corr = spearmanr(merged["importance_gain_prev"], merged["importance_gain_cur"]).correlation
            prev_vec = merged["importance_gain_prev"].to_numpy(dtype=float)
            cur_vec = merged["importance_gain_cur"].to_numpy(dtype=float)
            cosine = float(np.dot(prev_vec, cur_vec) / ((np.linalg.norm(prev_vec) * np.linalg.norm(cur_vec)) + 1e-12))
            rows.append(
                {
                    "model": model,
                    "origin_prev": prev,
                    "origin_cur": cur,
                    "top_n": top_n,
                    "spearman_top_gain": float(corr) if not np.isnan(corr) else np.nan,
                    "drift_loss_1_minus_spearman": float(1 - corr) if not np.isnan(corr) else np.nan,
                    "cosine_top_gain": cosine,
                    "top_features_prev": ",".join(top_features),
                }
            )
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--feature-importance", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--top-n", type=int, default=20)
    args = parser.parse_args()

    fi = pd.read_csv(args.feature_importance)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    drift = drift_rows(fi, args.top_n)
    summary = (
        drift.groupby("model")[["spearman_top_gain", "drift_loss_1_minus_spearman", "cosine_top_gain"]]
        .mean()
        .reset_index()
        .sort_values("drift_loss_1_minus_spearman")
    )
    top_features = (
        aggregate_importance(fi)
        .groupby(["model", "feature"])["importance_gain"]
        .mean()
        .reset_index()
        .sort_values(["model", "importance_gain"], ascending=[True, False])
        .groupby("model")
        .head(args.top_n)
    )
    drift.to_csv(out_dir / "feature_importance_drift_by_window.csv", index=False)
    summary.to_csv(out_dir / "feature_importance_drift_summary.csv", index=False)
    top_features.to_csv(out_dir / "feature_importance_top_features.csv", index=False)

    lines = [
        "# Feature Importance Drift Assessment",
        "",
        f"Input: `{args.feature_importance}`.",
        "",
        "## Drift Summary",
        "",
        md_table(summary),
        "",
        "## Window-Level Drift",
        "",
        md_table(drift.drop(columns=["top_features_prev"])),
        "",
        "## Top Features",
        "",
        md_table(top_features),
    ]
    Path(args.report).write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
