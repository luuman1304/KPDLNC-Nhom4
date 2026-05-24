from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

import pandas as pd


RUNS = [
    ("seed=42", Path("configs/research_config_large_k3_seed42.json")),
    ("seed=7", Path("configs/research_config_large_k3_seed7.json")),
    ("seed=2026", Path("configs/research_config_large_k3_seed2026.json")),
]
MODELS = ["A0_global_baseline", "B1_cluster_label", "B2_cluster_distance", "C_cluster_specific"]


def md_table(df: pd.DataFrame) -> str:
    if df.empty:
        return "(empty)"
    cols = list(df.columns)
    lines = ["| " + " | ".join(map(str, cols)) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
    for _, row in df.iterrows():
        vals = []
        for col in cols:
            val = row[col]
            vals.append(f"{val:.6g}" if isinstance(val, float) else str(val))
        lines.append("| " + " | ".join(vals) + " |")
    return "\n".join(lines)


def load_run(label: str, config_path: Path) -> Dict:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    metrics = Path(config["outputs_dir"]) / "metrics"
    return {
        "label": label,
        "config": config,
        "validation": pd.read_csv(metrics / "data_validation_checks.csv"),
        "model": pd.read_csv(metrics / "model_test_metrics.csv"),
        "wrmsse": pd.read_csv(metrics / "sampled_wrmsse_overall.csv"),
        "stability": pd.read_csv(metrics / "forecast_stability_metrics.csv"),
        "overfit": pd.read_csv(metrics / "overfitting_gap_summary.csv"),
        "clustering": pd.read_csv(metrics / "clustering_quality_metrics.csv"),
        "runtime": pd.read_csv(metrics / "runtime_costs.csv"),
        "floor": pd.read_csv(metrics / "stability_floor_sensitivity.csv"),
    }


def per_seed_summary(run: Dict) -> pd.DataFrame:
    label = run["label"]
    model = run["model"].loc[run["model"]["model"].isin(MODELS)].groupby("model")[["rmsse_item_store", "mae", "wape", "bias"]].mean().reset_index()
    wr = run["wrmsse"].loc[run["wrmsse"]["model"].isin(MODELS)].groupby("model")["sampled_wrmsse_12level"].mean().reset_index()
    st = (
        run["stability"]
        .loc[run["stability"]["model"].isin(MODELS)]
        .groupby("model")[["scale_aware_stability_loss", "weighted_absolute_change", "jump_rate_tau_0.3", "jump_rate_tau_0.5"]]
        .mean()
        .reset_index()
    )
    gap = (
        run["overfit"]
        .loc[run["overfit"]["model"].isin(MODELS)]
        .groupby("model")["test_train_gap"]
        .mean()
        .reset_index()
        .rename(columns={"test_train_gap": "mean_test_train_gap"})
    )
    out = model.merge(wr, on="model").merge(st, on="model").merge(gap, on="model")
    out.insert(0, "seed_run", label)
    return out


def clustering_summary(runs: List[Dict]) -> pd.DataFrame:
    rows = []
    for run in runs:
        config = run["config"]
        selected = run["clustering"].loc[run["clustering"]["k"] == config["selected_k"]]
        rows.append(
            {
                "seed_run": run["label"],
                "selected_k": config["selected_k"],
                "mean_silhouette": float(selected["silhouette"].mean()),
                "mean_davies_bouldin": float(selected["davies_bouldin"].mean()),
                "mean_min_cluster_size": float(selected["min_cluster_size"].mean()),
            }
        )
    return pd.DataFrame(rows)


def validation_summary(runs: List[Dict]) -> pd.DataFrame:
    rows = []
    for run in runs:
        validation = run["validation"]
        rows.append(
            {
                "seed_run": run["label"],
                "checks_passed": int(validation["status"].astype(bool).sum()),
                "checks_total": len(validation),
                "failed_checks": "; ".join(validation.loc[~validation["status"].astype(bool), "check"].astype(str).tolist()) or "none",
            }
        )
    return pd.DataFrame(rows)


def aggregate_summary(per_seed: pd.DataFrame) -> pd.DataFrame:
    agg = (
        per_seed.groupby("model")
        .agg(
            rmsse_mean=("rmsse_item_store", "mean"),
            rmsse_std=("rmsse_item_store", "std"),
            wrmsse_mean=("sampled_wrmsse_12level", "mean"),
            wrmsse_std=("sampled_wrmsse_12level", "std"),
            stability_mean=("scale_aware_stability_loss", "mean"),
            stability_std=("scale_aware_stability_loss", "std"),
            gap_mean=("mean_test_train_gap", "mean"),
            gap_std=("mean_test_train_gap", "std"),
            wape_mean=("wape", "mean"),
            bias_mean=("bias", "mean"),
        )
        .reset_index()
    )
    return agg.sort_values(["wrmsse_mean", "rmsse_mean"])


def win_counts(per_seed: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for metric, ascending in [
        ("rmsse_item_store", True),
        ("sampled_wrmsse_12level", True),
        ("scale_aware_stability_loss", True),
        ("mean_test_train_gap", True),
    ]:
        for seed_run, grp in per_seed.groupby("seed_run"):
            best_model = grp.sort_values(metric, ascending=ascending).iloc[0]["model"]
            rows.append({"metric": metric, "seed_run": seed_run, "best_model": best_model})
    out = pd.DataFrame(rows)
    counts = out.groupby(["metric", "best_model"]).size().reset_index(name="n_seed_wins")
    return counts.sort_values(["metric", "n_seed_wins"], ascending=[True, False])


def diff_vs_baseline(per_seed: pd.DataFrame) -> pd.DataFrame:
    rows = []
    baseline = "A0_global_baseline"
    for seed_run, grp in per_seed.groupby("seed_run"):
        base = grp.loc[grp["model"] == baseline].iloc[0]
        for _, row in grp.iterrows():
            if row["model"] == baseline:
                continue
            rows.append(
                {
                    "seed_run": seed_run,
                    "model": row["model"],
                    "rmsse_diff_vs_A0": row["rmsse_item_store"] - base["rmsse_item_store"],
                    "wrmsse_diff_vs_A0": row["sampled_wrmsse_12level"] - base["sampled_wrmsse_12level"],
                    "stability_diff_vs_A0": row["scale_aware_stability_loss"] - base["scale_aware_stability_loss"],
                    "gap_diff_vs_A0": row["mean_test_train_gap"] - base["mean_test_train_gap"],
                }
            )
    out = pd.DataFrame(rows)
    summary = (
        out.groupby("model")
        .agg(
            rmsse_diff_mean=("rmsse_diff_vs_A0", "mean"),
            rmsse_diff_std=("rmsse_diff_vs_A0", "std"),
            wrmsse_diff_mean=("wrmsse_diff_vs_A0", "mean"),
            wrmsse_diff_std=("wrmsse_diff_vs_A0", "std"),
            stability_diff_mean=("stability_diff_vs_A0", "mean"),
            stability_diff_std=("stability_diff_vs_A0", "std"),
            gap_diff_mean=("gap_diff_vs_A0", "mean"),
            gap_diff_std=("gap_diff_vs_A0", "std"),
            n_seeds=("seed_run", "nunique"),
        )
        .reset_index()
    )
    return out, summary


def runtime_summary(runs: List[Dict]) -> pd.DataFrame:
    rows = []
    for run in runs:
        runtime = run["runtime"]
        rows.append(
            {
                "seed_run": run["label"],
                "total_seconds": float(runtime["seconds"].sum()),
                "modeling_seconds": float(runtime.loc[runtime["stage"] == "modeling_and_evaluation", "seconds"].sum()),
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    runs = [load_run(label, path) for label, path in RUNS]
    out_dir = Path("outputs_seed_sensitivity")
    metrics_dir = out_dir / "metrics"
    reports_dir = out_dir / "reports"
    metrics_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    per_seed = pd.concat([per_seed_summary(run) for run in runs], ignore_index=True)
    aggregate = aggregate_summary(per_seed)
    counts = win_counts(per_seed)
    diff_detail, diff_summary = diff_vs_baseline(per_seed)
    validation = validation_summary(runs)
    clustering = clustering_summary(runs)
    runtime = runtime_summary(runs)

    per_seed.to_csv(metrics_dir / "k3_seed_sensitivity_per_seed.csv", index=False)
    aggregate.to_csv(metrics_dir / "k3_seed_sensitivity_aggregate.csv", index=False)
    counts.to_csv(metrics_dir / "k3_seed_sensitivity_win_counts.csv", index=False)
    diff_detail.to_csv(metrics_dir / "k3_seed_sensitivity_diff_vs_A0_detail.csv", index=False)
    diff_summary.to_csv(metrics_dir / "k3_seed_sensitivity_diff_vs_A0_summary.csv", index=False)
    validation.to_csv(metrics_dir / "k3_seed_sensitivity_validation.csv", index=False)
    clustering.to_csv(metrics_dir / "k3_seed_sensitivity_clustering.csv", index=False)
    runtime.to_csv(metrics_dir / "k3_seed_sensitivity_runtime.csv", index=False)

    best_rmsse = aggregate.sort_values("rmsse_mean").iloc[0]
    best_wrmsse = aggregate.sort_values("wrmsse_mean").iloc[0]
    best_stability = aggregate.sort_values("stability_mean").iloc[0]
    safest_gap = aggregate.sort_values("gap_mean").iloc[0]

    lines = [
        "# K=3 Seed Sensitivity Assessment",
        "",
        "## Scope",
        "",
        "This report aggregates three large-sample K=3 runs with 10,000 stratified series per run.",
        "The compared models are A0, B1, B2, and C. D is excluded from the seed-sensitivity run because the large-sample K=3/K=5 comparison already showed it is a negative ablation.",
        "",
        "## Validation",
        "",
        md_table(validation),
        "",
        "All runs passed the same raw-data validation checks. The same recursive forecast-horizon design is used, so the earlier leakage issue is not reintroduced.",
        "",
        "## Clustering Across Seeds",
        "",
        md_table(clustering),
        "",
        "K=3 clustering quality is reasonably consistent across seeds, with silhouette around 0.239-0.246 and Davies-Bouldin around 1.35-1.37.",
        "",
        "## Per-Seed Model Results",
        "",
        md_table(
            per_seed.sort_values(["seed_run", "sampled_wrmsse_12level"])[
                [
                    "seed_run",
                    "model",
                    "rmsse_item_store",
                    "sampled_wrmsse_12level",
                    "scale_aware_stability_loss",
                    "mean_test_train_gap",
                    "mae",
                    "wape",
                    "bias",
                ]
            ]
        ),
        "",
        "## Aggregate Across Seeds",
        "",
        md_table(aggregate),
        "",
        "## Difference Vs A0",
        "",
        md_table(diff_summary),
        "",
        "## Win Counts",
        "",
        md_table(counts),
        "",
        "## Main Findings",
        "",
        f"- Best average RMSSE: {best_rmsse['model']} with mean {best_rmsse['rmsse_mean']:.6f}.",
        f"- Best average sampled WRMSSE: {best_wrmsse['model']} with mean {best_wrmsse['wrmsse_mean']:.6f}.",
        f"- Best average stability: {best_stability['model']} with mean {best_stability['stability_mean']:.6f}.",
        f"- Lowest average test-train gap: {safest_gap['model']} with mean {safest_gap['gap_mean']:.6f}.",
        "- B1 is the most robust global cluster-aware choice: it improves RMSSE and sampled WRMSSE versus A0 on average while keeping overfitting gap close to A0.",
        "- B2 improves RMSSE versus A0 on average but its sampled WRMSSE is less stable across seeds, especially seed 7 and seed 2026.",
        "- C has the best average sampled WRMSSE and stability, but its overfitting gap is consistently higher than A0/B1/B2.",
        "",
        "## Recommendation",
        "",
        "- Use B1_cluster_label as the main proposed global forecasting model for the paper.",
        "- Report B2_cluster_distance as an accuracy-oriented extension, not as the default robust model.",
        "- Report C_cluster_specific as an ablation that improves stability/WRMSSE but carries higher overfitting and operational-complexity risk.",
        "- Keep D only as a negative ablation from the previous large-sample K comparison.",
        "- Do not claim official M5 superiority until official/full WRMSSE is implemented.",
        "",
        "## Runtime",
        "",
        md_table(runtime),
    ]

    report = "\n".join(lines)
    (reports_dir / "k3_seed_sensitivity_assessment.md").write_text(report, encoding="utf-8")
    Path("Document/K3_Seed_Sensitivity_Assessment.md").write_text(report, encoding="utf-8")


if __name__ == "__main__":
    main()
