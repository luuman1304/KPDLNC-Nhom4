from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import friedmanchisquare


def md_table(df: pd.DataFrame) -> str:
    if df.empty:
        return "(empty)"
    cols = list(df.columns)
    lines = ["| " + " | ".join(map(str, cols)) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
    for _, row in df.iterrows():
        vals = []
        for col in cols:
            val = row[col]
            if isinstance(val, float):
                vals.append(f"{val:.6g}")
            else:
                vals.append(str(val))
        lines.append("| " + " | ".join(vals) + " |")
    return "\n".join(lines)


def bootstrap_ci(values: np.ndarray, seed: int = 42, n_boot: int = 5000) -> tuple:
    values = np.asarray(values, dtype=float)
    values = values[~np.isnan(values)]
    if len(values) == 0:
        return np.nan, np.nan, np.nan
    rng = np.random.default_rng(seed)
    means = [rng.choice(values, size=len(values), replace=True).mean() for _ in range(n_boot)]
    return float(values.mean()), float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))


def evaluate_predictions(pred: pd.DataFrame) -> dict:
    abs_err = (pred["y"] - pred["yhat"]).abs()
    return {
        "mae": float(abs_err.mean()),
        "wape": float(abs_err.sum() / (pred["y"].abs().sum() + 1e-9)),
        "bias": float((pred["yhat"] - pred["y"]).sum() / (pred["y"].sum() + 1e-9)),
    }


def pareto_frontier(model_summary: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, row in model_summary.iterrows():
        dominated = False
        for _, other in model_summary.iterrows():
            if other["model"] == row["model"]:
                continue
            better_or_equal = (
                other["rmsse_item_store"] <= row["rmsse_item_store"]
                and other["scale_aware_stability_loss"] <= row["scale_aware_stability_loss"]
            )
            strictly_better = (
                other["rmsse_item_store"] < row["rmsse_item_store"]
                or other["scale_aware_stability_loss"] < row["scale_aware_stability_loss"]
            )
            if better_or_equal and strictly_better:
                dominated = True
                break
        out = row.to_dict()
        out["pareto_efficient"] = not dominated
        rows.append(out)
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/research_config.json")
    args = parser.parse_args()

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    metrics_dir = Path(config["outputs_dir"]) / "metrics"
    reports_dir = Path(config["reports_dir"])
    reports_dir.mkdir(exist_ok=True)

    model_metrics = pd.read_csv(metrics_dir / "model_test_metrics.csv")
    overfit = pd.read_csv(metrics_dir / "model_train_val_test_metrics.csv")
    stability = pd.read_csv(metrics_dir / "forecast_stability_metrics.csv")
    forecasts = pd.read_parquet(metrics_dir / "test_forecasts.parquet")
    sampled_wrmsse_path = metrics_dir / "sampled_wrmsse_overall.csv"
    sampled_wrmsse = pd.read_csv(sampled_wrmsse_path) if sampled_wrmsse_path.exists() else pd.DataFrame()
    cluster_specific_status_path = metrics_dir / "cluster_specific_model_status.csv"
    cluster_specific_status = pd.read_csv(cluster_specific_status_path) if cluster_specific_status_path.exists() else pd.DataFrame()

    # Friedman test over origins for item-store RMSSE.
    pivot = model_metrics.pivot_table(index="origin", columns="model", values="rmsse_item_store")
    friedman_rows = []
    if pivot.shape[0] >= 2 and pivot.shape[1] >= 3:
        stat, pvalue = friedmanchisquare(*[pivot[col].dropna().to_numpy() for col in pivot.columns])
        friedman_rows.append({"metric": "rmsse_item_store", "statistic": stat, "pvalue": pvalue, "n_origins": len(pivot), "n_models": len(pivot.columns)})
    friedman = pd.DataFrame(friedman_rows)
    friedman.to_csv(metrics_dir / "friedman_test.csv", index=False)

    # Bootstrap confidence intervals for model differences vs baseline.
    baseline = "A0_global_baseline"
    ci_rows = []
    for metric in ["rmsse_item_store", "mae", "wape"]:
        p = model_metrics.pivot_table(index="origin", columns="model", values=metric)
        if baseline not in p:
            continue
        for model in p.columns:
            if model == baseline:
                continue
            diffs = (p[model] - p[baseline]).dropna().to_numpy()
            mean, lo, hi = bootstrap_ci(diffs, seed=config["random_seed"])
            ci_rows.append({"metric": metric, "model": model, "mean_diff": mean, "ci_2.5": lo, "ci_97.5": hi, "n_origins": len(diffs)})
    ci = pd.DataFrame(ci_rows)
    ci.to_csv(metrics_dir / "bootstrap_ci_vs_baseline.csv", index=False)

    # Hierarchy-level sampled metrics.
    hierarchy_rows = []
    for level in ["cat_id", "store_id"]:
        for (model, group), grp in forecasts.groupby(["model", level], observed=True):
            hierarchy_rows.append({"level": level, "group": group, "model": model, **evaluate_predictions(grp)})
    hierarchy = pd.DataFrame(hierarchy_rows)
    hierarchy.to_csv(metrics_dir / "sample_hierarchy_metrics.csv", index=False)

    # Pareto frontier using average RMSSE and stability.
    acc = model_metrics.groupby("model")["rmsse_item_store"].mean().reset_index()
    stab = stability.groupby("model")["scale_aware_stability_loss"].mean().reset_index()
    pareto = pareto_frontier(acc.merge(stab, on="model", how="inner"))
    pareto.to_csv(metrics_dir / "accuracy_stability_pareto.csv", index=False)

    # Task execution status.
    task_status = pd.DataFrame(
        [
            {"area": "Data validation", "status": "done", "evidence": "outputs/metrics/data_validation_checks.csv"},
            {"area": "EDA", "status": "done", "evidence": "outputs/eda/*.csv, outputs/figures/*.png"},
            {"area": "Rolling-origin", "status": "done", "evidence": str(config["rolling_origins"])},
            {"area": "Anti-leakage design", "status": "done", "evidence": "window-specific feature construction; release-day handling"},
            {"area": "Forecasting features", "status": "done", "evidence": "lag, rolling, calendar, price, availability features in pipeline"},
            {"area": "Clustering features", "status": "done", "evidence": "outputs/processed/clustering_features_origin_*.parquet"},
            {"area": "Mini-batch K-Means", "status": "done", "evidence": "outputs/metrics/clustering_quality_metrics.csv"},
            {"area": "Label alignment and smoothing", "status": "done", "evidence": "cluster_labels_origin_*.csv with aligned/smoothed labels"},
            {"area": "K-Medoids robustness", "status": "not_run", "evidence": "not available in installed sklearn; requires extra implementation/package"},
            {
                "area": "LightGBM models",
                "status": "done_sampled",
                "evidence": f"A/B/C/D plus B2 variant; {config['model_sample_n_series']} stratified series sample; {metrics_dir / 'model_test_metrics.csv'}",
            },
            {"area": "Rolling WRMSSE", "status": "done_sampled", "evidence": "sampled 12-level rolling WRMSSE computed; official full WRMSSE still not computed"},
            {"area": "Forecast stability", "status": "done", "evidence": "outputs/metrics/forecast_stability_metrics.csv"},
            {"area": "Overfitting checks", "status": "done", "evidence": "outputs/metrics/overfitting_gap_summary.csv"},
            {"area": "Ablation study", "status": "partial", "evidence": "A0/B1/B2/C/D cover no-cluster, label, distance, cluster-specific, weighting; other ablations not run"},
            {"area": "Sensitivity analysis", "status": "partial", "evidence": "K values and jump thresholds run; objective/seed sensitivity not run"},
            {"area": "Statistical tests", "status": "done_minimal", "evidence": "friedman_test.csv, bootstrap_ci_vs_baseline.csv"},
            {"area": "Cost analysis", "status": "done", "evidence": "outputs/metrics/runtime_costs.csv"},
            {"area": "Hierarchy/cluster reporting", "status": "done_sampled", "evidence": "model_metrics_by_cluster.csv, sample_hierarchy_metrics.csv"},
        ]
    )
    task_status.to_csv(metrics_dir / "task_execution_status.csv", index=False)

    lines = ["# Research Output Audit", ""]
    lines.append("## Task Status")
    lines.append(md_table(task_status))
    lines.append("")
    lines.append("## Friedman Test")
    lines.append(md_table(friedman))
    lines.append("")
    lines.append("## Bootstrap CI vs Baseline")
    lines.append(md_table(ci))
    lines.append("")
    lines.append("## Accuracy-Stability Pareto")
    lines.append(md_table(pareto))
    lines.append("")
    lines.append("## Sampled Rolling WRMSSE")
    if not sampled_wrmsse.empty:
        lines.append(md_table(sampled_wrmsse.groupby("model")["sampled_wrmsse_12level"].mean().sort_values().reset_index()))
    else:
        lines.append("No sampled WRMSSE file found.")
    lines.append("")
    lines.append("## Cluster-specific Model Status")
    if not cluster_specific_status.empty:
        status_summary = (
            cluster_specific_status.groupby("status")
            .agg(n_cluster_origin_models=("cluster_label", "count"), min_train_rows=("train_rows", "min"), min_validation_rows=("inner_validation_rows", "min"))
            .reset_index()
        )
        lines.append(md_table(status_summary))
    else:
        lines.append("No cluster-specific status file found.")
    lines.append("")
    lines.append("## Interpretation Guardrails")
    lines.append("- Treat this as a controlled sampled experiment, not final official M5 benchmark.")
    lines.append("- Prefer B1/B2 only if improvement remains under full WRMSSE and additional origins/seeds.")
    lines.append("- D_cluster_weighted did not clearly improve accuracy in the previous sampled run; inspect current cluster-level metrics before using it.")
    lines.append("- C_cluster_specific is a comparison model; prefer it only if it improves validation/test without increasing overfitting or cost excessively.")
    lines.append("- No severe overfitting signal appears from test-train gaps alone, but full seed/objective sensitivity is still required for final claims.")
    (reports_dir / "research_output_audit.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
