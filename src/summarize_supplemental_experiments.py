from __future__ import annotations

from pathlib import Path

import pandas as pd


RUNS = {
    "base_poisson": "outputs_supp_k3_seed42_base_a0_b1_c",
    "no_smoothing": "outputs_supp_k3_seed42_no_smoothing_a0_b1_c",
    "no_intermittent_clustering_features": "outputs_supp_k3_seed42_no_intermittent_a0_b1_c",
    "tweedie": "outputs_supp_k3_seed42_tweedie_a0_b1_c",
    "regression": "outputs_supp_k3_seed42_regression_a0_b1_c",
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
            vals.append(f"{val:.6g}" if isinstance(val, float) else str(val))
        lines.append("| " + " | ".join(vals) + " |")
    return "\n".join(lines)


def load_run(label: str, out_dir: str) -> pd.DataFrame:
    metrics_dir = Path(out_dir) / "metrics"
    model = pd.read_csv(metrics_dir / "model_test_metrics.csv").groupby("model")[["rmsse_item_store", "mae", "wape", "bias"]].mean().reset_index()
    wr = pd.read_csv(metrics_dir / "sampled_wrmsse_overall.csv").groupby("model")["sampled_wrmsse_12level"].mean().reset_index()
    st = pd.read_csv(metrics_dir / "forecast_stability_metrics.csv").groupby("model")[["scale_aware_stability_loss", "weighted_absolute_change", "jump_rate_tau_0.3", "jump_rate_tau_0.5"]].mean().reset_index()
    gap = (
        pd.read_csv(metrics_dir / "overfitting_gap_summary.csv")
        .groupby("model")["test_train_gap"]
        .mean()
        .reset_index()
        .rename(columns={"test_train_gap": "mean_test_train_gap"})
    )
    out = model.merge(wr, on="model").merge(st, on="model").merge(gap, on="model")
    out.insert(0, "run", label)
    return out


def diff_against_base(all_runs: pd.DataFrame, runs: list[str]) -> pd.DataFrame:
    base = all_runs.loc[all_runs["run"] == "base_poisson"].set_index("model")
    rows = []
    for run in runs:
        cur = all_runs.loc[all_runs["run"] == run].set_index("model")
        for model in sorted(set(cur.index) & set(base.index)):
            rows.append(
                {
                    "run": run,
                    "model": model,
                    "rmsse_diff_vs_base": cur.at[model, "rmsse_item_store"] - base.at[model, "rmsse_item_store"],
                    "wrmsse_diff_vs_base": cur.at[model, "sampled_wrmsse_12level"] - base.at[model, "sampled_wrmsse_12level"],
                    "stability_diff_vs_base": cur.at[model, "scale_aware_stability_loss"] - base.at[model, "scale_aware_stability_loss"],
                    "gap_diff_vs_base": cur.at[model, "mean_test_train_gap"] - base.at[model, "mean_test_train_gap"],
                }
            )
    return pd.DataFrame(rows)


def main() -> None:
    out_dir = Path("outputs_supplemental_summary")
    metrics_dir = out_dir / "metrics"
    reports_dir = out_dir / "reports"
    metrics_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    all_runs = pd.concat([load_run(label, path) for label, path in RUNS.items()], ignore_index=True)
    ablation_diff = diff_against_base(all_runs, ["no_smoothing", "no_intermittent_clustering_features"])
    objective_diff = diff_against_base(all_runs, ["tweedie", "regression"])
    nemenyi_ranks = pd.read_csv("outputs_posthoc_stats/nemenyi_average_ranks.csv")
    nemenyi_pairs = pd.read_csv("outputs_posthoc_stats/nemenyi_pairwise.csv")
    drift = pd.read_csv("outputs_feature_importance_drift/feature_importance_drift_summary.csv")
    top_features = pd.read_csv("outputs_feature_importance_drift/feature_importance_top_features.csv")

    all_runs.to_csv(metrics_dir / "supplemental_all_runs.csv", index=False)
    ablation_diff.to_csv(metrics_dir / "supplemental_ablation_diff_vs_base.csv", index=False)
    objective_diff.to_csv(metrics_dir / "supplemental_objective_diff_vs_base.csv", index=False)

    base_summary = all_runs.loc[all_runs["run"] == "base_poisson"].sort_values("sampled_wrmsse_12level")
    objective_best = all_runs.loc[all_runs["run"].isin(["base_poisson", "tweedie", "regression"])].sort_values(["model", "sampled_wrmsse_12level"])
    ablation_focus = all_runs.loc[all_runs["run"].isin(["base_poisson", "no_smoothing", "no_intermittent_clustering_features"])].sort_values(["model", "sampled_wrmsse_12level"])

    lines = [
        "# Supplemental Experiment Assessment",
        "",
        "## Scope",
        "",
        "This report summarizes the four supplemental priorities requested after the full-scale run:",
        "",
        "1. Nemenyi post-hoc test.",
        "2. Feature Importance Drift.",
        "3. Ablation for cluster smoothing and intermittent-demand clustering features.",
        "4. Objective sensitivity: Poisson vs Tweedie vs Regression.",
        "",
        "All additional training runs use K=3, seed=42, 10,000 stratified series, five rolling origins, and models A0/B1/C.",
        "",
        "## Base Poisson Results",
        "",
        md_table(base_summary),
        "",
        "## Nemenyi Post-Hoc",
        "",
        "Average ranks:",
        "",
        md_table(nemenyi_ranks),
        "",
        "Pairwise critical-difference checks:",
        "",
        md_table(nemenyi_pairs),
        "",
        "Interpretation: Nemenyi is conservative with only five rolling-origin blocks. It does not mark all pairwise differences significant, even when bootstrap CI supports A0-vs-B1/C RMSSE improvements.",
        "",
        "## Feature Importance Drift",
        "",
        md_table(drift),
        "",
        "Top features by average gain:",
        "",
        md_table(top_features),
        "",
        "Interpretation: Lower `drift_loss_1_minus_spearman` means more stable top feature ranking across rolling origins.",
        "",
        "## Ablation Results",
        "",
        md_table(ablation_focus),
        "",
        "Ablation difference versus base Poisson:",
        "",
        md_table(ablation_diff),
        "",
        "## Objective Sensitivity",
        "",
        md_table(objective_best),
        "",
        "Objective difference versus base Poisson:",
        "",
        md_table(objective_diff),
        "",
        "## Main Findings",
        "",
        "- Nemenyi adds a conservative post-hoc check; with five origins it should be reported alongside bootstrap CI, not as the only significance evidence.",
        "- Feature-importance drift is now computed from saved LightGBM gain importances. This completes the proposal's model-internal stability component at sample scale.",
        "- Ablation checks quantify whether cluster label smoothing and intermittent-demand clustering features are actually useful.",
        "- Objective sensitivity checks whether Poisson remains a reasonable default versus Tweedie and regression.",
        "- These supplemental runs are sample-scale robustness checks; the full-scale headline result remains A0/B1/C from `Document/Full_Scale_Run_Assessment.md`.",
    ]
    report = "\n".join(lines)
    (reports_dir / "supplemental_experiment_assessment.md").write_text(report, encoding="utf-8")
    Path("Document/Supplemental_Experiment_Assessment.md").write_text(report, encoding="utf-8")


if __name__ == "__main__":
    main()
