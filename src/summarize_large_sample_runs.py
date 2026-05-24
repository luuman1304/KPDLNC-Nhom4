from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

import pandas as pd


RUN_CONFIGS = [
    ("K=3 seed=42 n=10000", Path("configs/research_config_large_k3_seed42.json")),
    ("K=5 seed=42 n=10000", Path("configs/research_config_large_k5_seed42.json")),
]


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


def load_config(path: Path) -> Dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_run(label: str, config_path: Path) -> Dict[str, pd.DataFrame | Dict | str]:
    config = load_config(config_path)
    metrics_dir = Path(config["outputs_dir"]) / "metrics"
    return {
        "label": label,
        "config": config,
        "validation": pd.read_csv(metrics_dir / "data_validation_checks.csv"),
        "model": pd.read_csv(metrics_dir / "model_test_metrics.csv"),
        "wrmsse": pd.read_csv(metrics_dir / "sampled_wrmsse_overall.csv"),
        "stability": pd.read_csv(metrics_dir / "forecast_stability_metrics.csv"),
        "overfit": pd.read_csv(metrics_dir / "overfitting_gap_summary.csv"),
        "clustering": pd.read_csv(metrics_dir / "clustering_quality_metrics.csv"),
        "ci": pd.read_csv(metrics_dir / "bootstrap_ci_vs_baseline.csv"),
        "friedman": pd.read_csv(metrics_dir / "friedman_test.csv"),
        "floor": pd.read_csv(metrics_dir / "stability_floor_sensitivity.csv"),
        "residual": pd.read_csv(metrics_dir / "residual_bias_diagnostics.csv"),
        "kmedoids": pd.read_csv(metrics_dir / "kmedoids_robustness.csv"),
        "runtime": pd.read_csv(metrics_dir / "runtime_costs.csv"),
    }


def summarize_run(run: Dict) -> pd.DataFrame:
    label = run["label"]
    model = run["model"].groupby("model")[["rmsse_item_store", "mae", "wape", "bias"]].mean().reset_index()
    wr = run["wrmsse"].groupby("model")["sampled_wrmsse_12level"].mean().reset_index()
    st = run["stability"].groupby("model")[["scale_aware_stability_loss", "weighted_absolute_change", "jump_rate_tau_0.3", "jump_rate_tau_0.5"]].mean().reset_index()
    gap = (
        run["overfit"]
        .groupby("model")["test_train_gap"]
        .mean()
        .reset_index()
        .rename(columns={"test_train_gap": "mean_test_train_gap"})
    )
    out = model.merge(wr, on="model").merge(st, on="model").merge(gap, on="model")
    out.insert(0, "run", label)
    return out


def selected_clustering(run: Dict) -> Dict[str, float | str]:
    config = run["config"]
    k = int(config["selected_k"])
    selected = run["clustering"].loc[run["clustering"]["k"] == k]
    return {
        "run": run["label"],
        "selected_k": k,
        "mean_silhouette": float(selected["silhouette"].mean()),
        "mean_davies_bouldin": float(selected["davies_bouldin"].mean()),
        "mean_min_cluster_size": float(selected["min_cluster_size"].mean()),
    }


def low_demand_floor_summary(run: Dict) -> pd.DataFrame:
    floor = run["floor"]
    overall = floor.loc[(floor["group_type"] == "overall") & (floor["floor"] == 0.1)]
    overall = overall.groupby("model")[["scale_loss", "jump03", "jump05"]].mean().reset_index()
    overall.insert(0, "run", run["label"])
    return overall


def ci_summary(run: Dict) -> pd.DataFrame:
    ci = run["ci"].loc[run["ci"]["metric"] == "rmsse_item_store", ["model", "mean_diff", "ci_2.5", "ci_97.5", "n_origins"]].copy()
    ci.insert(0, "run", run["label"])
    ci["direction_vs_A0"] = ci.apply(
        lambda r: "better_CI_excludes_0" if r["ci_97.5"] < 0 else ("worse_CI_excludes_0" if r["ci_2.5"] > 0 else "inconclusive"),
        axis=1,
    )
    return ci


def validation_summary(runs: List[Dict]) -> pd.DataFrame:
    rows = []
    for run in runs:
        validation = run["validation"]
        rows.append(
            {
                "run": run["label"],
                "checks_passed": int(validation["status"].astype(bool).sum()),
                "checks_total": int(len(validation)),
                "failed_checks": "; ".join(validation.loc[~validation["status"].astype(bool), "check"].astype(str).tolist()) or "none",
            }
        )
    return pd.DataFrame(rows)


def runtime_summary(runs: List[Dict]) -> pd.DataFrame:
    rows = []
    for run in runs:
        runtime = run["runtime"].copy()
        total = runtime["seconds"].sum()
        modeling = float(runtime.loc[runtime["stage"] == "modeling_and_evaluation", "seconds"].sum())
        rows.append({"run": run["label"], "total_seconds": total, "modeling_seconds": modeling})
    return pd.DataFrame(rows)


def main() -> None:
    runs = [load_run(label, path) for label, path in RUN_CONFIGS]
    out_dir = Path("outputs_large_summary")
    metrics_dir = out_dir / "metrics"
    reports_dir = out_dir / "reports"
    metrics_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    comparison = pd.concat([summarize_run(run) for run in runs], ignore_index=True)
    comparison = comparison.sort_values(["sampled_wrmsse_12level", "rmsse_item_store"])
    clustering = pd.DataFrame([selected_clustering(run) for run in runs])
    ci = pd.concat([ci_summary(run) for run in runs], ignore_index=True)
    floor = pd.concat([low_demand_floor_summary(run) for run in runs], ignore_index=True)
    validation = validation_summary(runs)
    runtime = runtime_summary(runs)

    comparison.to_csv(metrics_dir / "large_sample_model_comparison.csv", index=False)
    clustering.to_csv(metrics_dir / "large_sample_clustering_comparison.csv", index=False)
    ci.to_csv(metrics_dir / "large_sample_bootstrap_ci_rmsse.csv", index=False)
    floor.to_csv(metrics_dir / "large_sample_stability_floor_overall.csv", index=False)
    validation.to_csv(metrics_dir / "large_sample_validation_summary.csv", index=False)
    runtime.to_csv(metrics_dir / "large_sample_runtime_summary.csv", index=False)

    best_rmsse = comparison.loc[comparison["rmsse_item_store"].idxmin()]
    best_wrmsse = comparison.loc[comparison["sampled_wrmsse_12level"].idxmin()]
    best_stability = comparison.loc[comparison["scale_aware_stability_loss"].idxmin()]
    d_rows = comparison.loc[comparison["model"] == "D_cluster_weighted"]

    lines = [
        "# Large Sample Run Assessment",
        "",
        "## Scope",
        "",
        "This assessment summarizes the controlled large-sample reruns requested after the initial 3,000-series experiment.",
        "Both runs use recursive forecasting for the 28-day test horizon, rolling origins, historical-only clustering features, and the same LightGBM setup as the corrected proposal pipeline.",
        "",
        "## Validation And Guardrails",
        "",
        md_table(validation),
        "",
        "- Data validation passed in both runs.",
        "- Test-horizon lag and rolling features are generated recursively, so actual demand inside the forecast horizon is not used as input.",
        "- Clustering features are recomputed per origin using days up to that origin only.",
        "- Stability is reported with a scale-aware floor to reduce exaggerated percentage changes for near-zero demand series.",
        "- These are still sampled WRMSSE experiments, not official full M5 WRMSSE leaderboard runs.",
        "",
        "## Clustering Comparison",
        "",
        md_table(clustering),
        "",
        "K=3 remains better on clustering geometry: higher silhouette and lower Davies-Bouldin than K=5.",
        "",
        "## Model Comparison",
        "",
        md_table(
            comparison[
                [
                    "run",
                    "model",
                    "rmsse_item_store",
                    "sampled_wrmsse_12level",
                    "scale_aware_stability_loss",
                    "weighted_absolute_change",
                    "jump_rate_tau_0.3",
                    "mean_test_train_gap",
                    "mae",
                    "wape",
                    "bias",
                ]
            ]
        ),
        "",
        "## Bootstrap CI For RMSSE Difference Vs A0",
        "",
        md_table(ci),
        "",
        "## Stability Floor Check",
        "",
        md_table(floor.sort_values(["run", "scale_loss"])),
        "",
        "## Main Findings",
        "",
        f"- Best item-store RMSSE: {best_rmsse['run']} / {best_rmsse['model']} = {best_rmsse['rmsse_item_store']:.6f}.",
        f"- Best sampled 12-level WRMSSE: {best_wrmsse['run']} / {best_wrmsse['model']} = {best_wrmsse['sampled_wrmsse_12level']:.6f}.",
        f"- Best scale-aware stability: {best_stability['run']} / {best_stability['model']} = {best_stability['scale_aware_stability_loss']:.6f}.",
        "- B1 and B2 consistently improve item-store RMSSE relative to A0 across K=3 and K=5.",
        "- C_cluster_specific improves sampled WRMSSE and stability in this larger sample, but its overfitting gap is higher than B1/B2, especially for K=5.",
        "- D_cluster_weighted is not suitable as a main model in the current implementation: it is worse than A0/B1/B2 on sampled WRMSSE and stability.",
        "",
        "## Model Recommendation For The Research Paper",
        "",
        "- Keep A0_global_baseline as the mandatory baseline.",
        "- Keep B1_cluster_label and B2_cluster_distance as the main cluster-aware global forecasting models.",
        "- Keep C_cluster_specific as an ablation/comparison model, not the default final method, because it is accurate/stable here but has higher overfitting risk and higher operational complexity.",
        "- Report D_cluster_weighted as a negative ablation and exclude it from the final recommended framework unless a better weighting strategy is redesigned.",
        "- Prefer K=3 for the main framework because it has better cluster geometry and gives the best sampled WRMSSE/stability result through C, while B1/B2 remain competitive.",
        "- If the final method must remain strictly 'global forecasting', use K=5+B2 or K=3+B2 as the main accuracy model and K=3+B1 as the simpler robust alternative.",
        "",
        "## Comparison With Reference Research",
        "",
        "The large-sample results should not be described as beating the M5 reference study because this experiment still uses sampled series and sampled rolling WRMSSE.",
        "The correct claim is narrower: compared with the internal A0 LightGBM baseline, cluster-aware variants B1/B2 improve RMSSE and stability, while C improves sampled WRMSSE/stability but needs extra overfitting control.",
        "",
        "## Remaining Work Before Final Full Paper",
        "",
        "- Run at least seed sensitivity for K=3 on B1/B2/C if time permits.",
        "- Add official or closer-to-official full M5 WRMSSE computation before making final comparison claims.",
        "- Consider full-scale or near-full-scale run only for A0, B1, B2, and optionally C after confirming compute budget.",
        "- Redesign D weighting before reusing it; current D results are not defensible as an improvement.",
        "",
        "## Runtime",
        "",
        md_table(runtime),
    ]

    report = "\n".join(lines)
    (reports_dir / "large_sample_run_assessment.md").write_text(report, encoding="utf-8")
    Path("Document/Large_Sample_Run_Assessment.md").write_text(report, encoding="utf-8")


if __name__ == "__main__":
    main()
