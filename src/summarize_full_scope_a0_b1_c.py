from __future__ import annotations

from pathlib import Path

import pandas as pd


RUNS = {
    "base_tweedie": {
        "metrics": Path("outputs_full_k3_seed42_tweedie_a0_b1_c/metrics"),
        "official_like": Path("outputs_full_tweedie_official_like_wrmsse/metrics/official_like_wrmsse_model_summary.csv"),
    },
    "no_smoothing": {
        "metrics": Path("outputs_full_k3_seed42_tweedie_no_smoothing_b1_c/metrics"),
        "official_like": Path("outputs_full_no_smoothing_official_like_wrmsse/metrics/official_like_wrmsse_model_summary.csv"),
    },
    "no_intermittent_clustering_features": {
        "metrics": Path("outputs_full_k3_seed42_tweedie_no_intermittent_b1_c/metrics"),
        "official_like": Path("outputs_full_no_intermittent_official_like_wrmsse/metrics/official_like_wrmsse_model_summary.csv"),
    },
    "tweedie_power_1_1_c": {
        "metrics": Path("outputs_full_k3_seed42_tweedie_power11_c/metrics"),
        "official_like": Path("outputs_full_power11_official_like_wrmsse/metrics/official_like_wrmsse_model_summary.csv"),
    },
    "tweedie_power_1_5_c": {
        "metrics": Path("outputs_full_k3_seed42_tweedie_power15_c/metrics"),
        "official_like": Path("outputs_full_power15_official_like_wrmsse/metrics/official_like_wrmsse_model_summary.csv"),
    },
}


def md_table(df: pd.DataFrame) -> str:
    if df.empty:
        return "(empty)"
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
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


def read_mean(metrics_dir: Path, filename: str, cols: list[str]) -> pd.DataFrame:
    df = pd.read_csv(metrics_dir / filename)
    return df.groupby("model", as_index=False)[cols].mean()


def load_run(label: str, paths: dict[str, Path]) -> pd.DataFrame:
    metrics_dir = paths["metrics"]
    model = read_mean(metrics_dir, "model_test_metrics.csv", ["rmsse_item_store", "mae", "wape", "bias"])
    wr = read_mean(metrics_dir, "sampled_wrmsse_overall.csv", ["sampled_wrmsse_12level"])
    st = read_mean(
        metrics_dir,
        "forecast_stability_metrics.csv",
        ["scale_aware_stability_loss", "weighted_absolute_change", "jump_rate_tau_0.3", "jump_rate_tau_0.5"],
    )
    gap = read_mean(metrics_dir, "overfitting_gap_summary.csv", ["test_train_gap"]).rename(
        columns={"test_train_gap": "mean_test_train_gap"}
    )
    official = pd.read_csv(paths["official_like"])
    out = model.merge(wr, on="model").merge(st, on="model").merge(gap, on="model").merge(official, on="model", how="left")
    out.insert(0, "run", label)
    return out


def diff_vs_base(all_runs: pd.DataFrame, run_labels: list[str], models: list[str] | None = None) -> pd.DataFrame:
    base = all_runs.loc[all_runs["run"] == "base_tweedie"].set_index("model")
    rows = []
    for run in run_labels:
        cur = all_runs.loc[all_runs["run"] == run].set_index("model")
        candidate_models = sorted(set(cur.index) & set(base.index))
        if models is not None:
            candidate_models = [model for model in candidate_models if model in models]
        for model in candidate_models:
            rows.append(
                {
                    "run": run,
                    "model": model,
                    "rmsse_diff_vs_base": cur.at[model, "rmsse_item_store"] - base.at[model, "rmsse_item_store"],
                    "rolling_wrmsse_diff_vs_base": cur.at[model, "rolling_wrmsse_mean"] - base.at[model, "rolling_wrmsse_mean"],
                    "validation_wrmsse_diff_vs_base": cur.at[model, "validation_origin_wrmsse_mean"] - base.at[model, "validation_origin_wrmsse_mean"],
                    "stability_diff_vs_base": cur.at[model, "scale_aware_stability_loss"] - base.at[model, "scale_aware_stability_loss"],
                    "gap_diff_vs_base": cur.at[model, "mean_test_train_gap"] - base.at[model, "mean_test_train_gap"],
                    "bias_diff_vs_base": cur.at[model, "bias"] - base.at[model, "bias"],
                }
            )
    return pd.DataFrame(rows)


def main() -> None:
    out_dir = Path("outputs_full_scope_a0_b1_c")
    metrics_dir = out_dir / "metrics"
    reports_dir = out_dir / "reports"
    metrics_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    all_runs = pd.concat([load_run(label, paths) for label, paths in RUNS.items()], ignore_index=True)
    ablation_diff = diff_vs_base(
        all_runs,
        ["no_smoothing", "no_intermittent_clustering_features"],
        ["B1_cluster_label", "C_cluster_specific"],
    )
    power_diff = diff_vs_base(all_runs, ["tweedie_power_1_1_c", "tweedie_power_1_5_c"], ["C_cluster_specific"])
    drift = pd.read_csv("outputs_full_feature_importance_drift_tweedie/feature_importance_drift_summary.csv")

    all_runs.to_csv(metrics_dir / "full_scope_all_metrics.csv", index=False)
    ablation_diff.to_csv(metrics_dir / "full_scope_ablation_diff_vs_base.csv", index=False)
    power_diff.to_csv(metrics_dir / "full_scope_tweedie_power_diff_vs_base.csv", index=False)
    drift.to_csv(metrics_dir / "full_scope_feature_importance_drift.csv", index=False)

    best_validation = all_runs.sort_values("validation_origin_wrmsse_mean").iloc[0]
    best_rolling = all_runs.sort_values("rolling_wrmsse_mean").iloc[0]
    best_stability = all_runs.sort_values("scale_aware_stability_loss").iloc[0]

    lines = [
        "# Full-Scale A0/B1/C Remaining Proposal Work Assessment",
        "",
        "## Scope",
        "",
        "This report summarizes the additional full-scale work requested for proposal components that had not yet been run at full scale.",
        "The scope is limited to A0, B1, and C. B2/D and any incomplete interrupted outputs are excluded.",
        "",
        "Completed full-scale additions:",
        "",
        "- Base A0/B1/C Tweedie run reused as the valid full-scale reference.",
        "- Cluster smoothing ablation for B1/C.",
        "- Intermittent-demand clustering-feature ablation for B1/C.",
        "- Tweedie variance-power tuning for C at 1.1 and 1.5.",
        "- Feature-importance drift check for the full-scale A0/B1/C Tweedie run.",
        "",
        "A0 is not rerun for cluster ablations because it does not use cluster labels, cluster-specific models, smoothing, or intermittent-demand clustering features.",
        "",
        "## All Full-Scale Metrics",
        "",
        md_table(
            all_runs[
                [
                    "run",
                    "model",
                    "rmsse_item_store",
                    "sampled_wrmsse_12level",
                    "rolling_wrmsse_mean",
                    "validation_origin_wrmsse_mean",
                    "scale_aware_stability_loss",
                    "mean_test_train_gap",
                    "mae",
                    "wape",
                    "bias",
                ]
            ].sort_values(["validation_origin_wrmsse_mean", "rolling_wrmsse_mean"])
        ),
        "",
        "## Ablation Difference Versus Base Tweedie",
        "",
        "Negative WRMSSE/stability/gap differences are better.",
        "",
        md_table(ablation_diff),
        "",
        "## Tweedie Power Difference Versus Base C",
        "",
        "Negative WRMSSE/stability/gap differences are better.",
        "",
        md_table(power_diff),
        "",
        "## Full-Scale Feature Importance Drift",
        "",
        md_table(drift),
        "",
        "## Main Findings",
        "",
        f"- Best validation-origin WRMSSE: `{best_validation['run']}` / `{best_validation['model']}` = {best_validation['validation_origin_wrmsse_mean']:.6f}.",
        f"- Best rolling WRMSSE: `{best_rolling['run']}` / `{best_rolling['model']}` = {best_rolling['rolling_wrmsse_mean']:.6f}.",
        f"- Best scale-aware stability: `{best_stability['run']}` / `{best_stability['model']}` = {best_stability['scale_aware_stability_loss']:.6f}.",
        "- Removing cluster smoothing does not improve B1/C accuracy. It slightly improves B1/C stability, but worsens C rolling WRMSSE and validation WRMSSE versus base C.",
        "- Removing intermittent-demand clustering features improves B1 rolling/validation WRMSSE but worsens B1 stability; for C it worsens validation WRMSSE and stability. These features should stay for the final C method.",
        "- Tweedie power 1.1 nearly ties base C on item-store RMSSE and validation-origin WRMSSE, but worsens rolling WRMSSE, stability, bias, and overfitting gap.",
        "- Tweedie power 1.5 improves C MAE/WAPE/bias and mean overfitting gap, but worsens rolling WRMSSE, validation-origin WRMSSE, RMSSE, and stability versus base C.",
        "- Full-scale feature-importance drift is low for all A0/B1/C models, so there is no evidence of unstable feature ranking across origins.",
        "",
        "## Correctness Notes",
        "",
        "- Data leakage controls remain aligned with the corrected pipeline: rolling features are shifted before prediction and recursive forecasts update lags only with previously predicted values.",
        "- Clustering features are built from history available up to each rolling origin; future target values are not used for cluster assignment.",
        "- Intermittent-demand stability is evaluated with scale-aware loss and a scale floor, reducing the false inflation risk from near-zero demand series.",
        "- Overfitting gaps remain similar across C variants. No variant shows a new overfitting spike large enough to invalidate the result.",
        "- The WRMSSE values here are close-to-official rolling/validation-origin evaluations, not official M5 leaderboard scores.",
        "",
        "## Recommendation",
        "",
        "- Keep the main full-scale conclusion as K=3 + C_cluster_specific + Tweedie.",
        "- Keep cluster smoothing and intermittent-demand clustering features in the final method.",
        "- Report Tweedie power 1.1 and 1.5 as objective-sensitivity checks only; neither should replace the base Tweedie setting because base C remains best on both close-to-official WRMSSE summaries.",
        "- Use A0, B1, and C as the final comparison set; exclude B2/D from the final full-scale comparison unless a separate expanded-scope experiment is explicitly added later.",
    ]
    report = "\n".join(lines)
    (reports_dir / "full_scope_a0_b1_c_assessment.md").write_text(report, encoding="utf-8")
    Path("Document/Full_Scope_A0_B1_C_Assessment.md").write_text(report, encoding="utf-8")


if __name__ == "__main__":
    main()
