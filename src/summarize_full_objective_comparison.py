from __future__ import annotations

from pathlib import Path

import pandas as pd


RUNS = {
    "poisson": {
        "metrics": Path("outputs_full_k3_seed42_a0_b1_c/metrics"),
        "official_like": Path("outputs_full_official_like_wrmsse/metrics/official_like_wrmsse_model_summary.csv"),
    },
    "tweedie": {
        "metrics": Path("outputs_full_k3_seed42_tweedie_a0_b1_c/metrics"),
        "official_like": Path("outputs_full_tweedie_official_like_wrmsse/metrics/official_like_wrmsse_model_summary.csv"),
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
            vals.append(f"{val:.6g}" if isinstance(val, float) else str(val))
        lines.append("| " + " | ".join(vals) + " |")
    return "\n".join(lines)


def load_run(label: str, paths: dict) -> pd.DataFrame:
    metrics_dir = paths["metrics"]
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
    official = pd.read_csv(paths["official_like"])
    out = model.merge(wr, on="model").merge(st, on="model").merge(gap, on="model").merge(official, on="model", how="left")
    out.insert(0, "objective", label)
    return out


def main() -> None:
    out_dir = Path("outputs_full_objective_comparison")
    metrics_dir = out_dir / "metrics"
    reports_dir = out_dir / "reports"
    metrics_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    all_runs = pd.concat([load_run(label, paths) for label, paths in RUNS.items()], ignore_index=True)
    poisson = all_runs.loc[all_runs["objective"] == "poisson"].set_index("model")
    tweedie = all_runs.loc[all_runs["objective"] == "tweedie"].set_index("model")
    rows = []
    for model in sorted(set(poisson.index) & set(tweedie.index)):
        rows.append(
            {
                "model": model,
                "rmsse_diff_tweedie_minus_poisson": tweedie.at[model, "rmsse_item_store"] - poisson.at[model, "rmsse_item_store"],
                "rolling_wrmsse_diff_tweedie_minus_poisson": tweedie.at[model, "rolling_wrmsse_mean"] - poisson.at[model, "rolling_wrmsse_mean"],
                "validation_wrmsse_diff_tweedie_minus_poisson": tweedie.at[model, "validation_origin_wrmsse_mean"] - poisson.at[model, "validation_origin_wrmsse_mean"],
                "stability_diff_tweedie_minus_poisson": tweedie.at[model, "scale_aware_stability_loss"] - poisson.at[model, "scale_aware_stability_loss"],
                "gap_diff_tweedie_minus_poisson": tweedie.at[model, "mean_test_train_gap"] - poisson.at[model, "mean_test_train_gap"],
                "bias_diff_tweedie_minus_poisson": tweedie.at[model, "bias"] - poisson.at[model, "bias"],
            }
        )
    diff = pd.DataFrame(rows)
    all_runs.to_csv(metrics_dir / "full_objective_comparison_all_metrics.csv", index=False)
    diff.to_csv(metrics_dir / "full_objective_comparison_diff.csv", index=False)

    best_by_validation = all_runs.sort_values("validation_origin_wrmsse_mean").iloc[0]
    best_by_rolling = all_runs.sort_values("rolling_wrmsse_mean").iloc[0]
    best_by_stability = all_runs.sort_values("scale_aware_stability_loss").iloc[0]

    lines = [
        "# Full-Scale Objective Comparison",
        "",
        "## Scope",
        "",
        "This report compares the full-scale K=3 A0/B1/C runs under Poisson and Tweedie LightGBM objectives.",
        "Both runs forecast all 30,490 M5 item-store series with recursive 28-day forecasts across five rolling origins.",
        "",
        "## All Metrics",
        "",
        md_table(
            all_runs[
                [
                    "objective",
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
        "## Tweedie Minus Poisson",
        "",
        md_table(diff),
        "",
        "## Main Findings",
        "",
        f"- Best validation-origin WRMSSE: {best_by_validation['objective']} / {best_by_validation['model']} = {best_by_validation['validation_origin_wrmsse_mean']:.6f}.",
        f"- Best rolling WRMSSE: {best_by_rolling['objective']} / {best_by_rolling['model']} = {best_by_rolling['rolling_wrmsse_mean']:.6f}.",
        f"- Best stability: {best_by_stability['objective']} / {best_by_stability['model']} = {best_by_stability['scale_aware_stability_loss']:.6f}.",
        "- Tweedie improves A0 substantially versus Poisson on WRMSSE and stability.",
        "- Under Tweedie, B1 no longer improves over A0; it is slightly worse on WRMSSE and stability.",
        "- C remains the strongest model under both objectives and is strongest overall under Tweedie.",
        "",
        "## Recommendation",
        "",
        "- Update the final research conclusion: the best empirical configuration is K=3 + C_cluster_specific + Tweedie.",
        "- Keep K=3 + B1_cluster_label + Poisson as the cleanest global cluster-aware variant, but note that under Tweedie the cluster-label feature does not improve A0.",
        "- Position C as the best-performing cluster-aware extension; position B1 as the interpretable global framework variant rather than the absolute best model.",
        "- Do not claim M5 leaderboard superiority; this remains a research rolling-origin evaluation.",
    ]
    report = "\n".join(lines)
    (reports_dir / "full_objective_comparison.md").write_text(report, encoding="utf-8")
    Path("Document/Full_Objective_Comparison_Assessment.md").write_text(report, encoding="utf-8")


if __name__ == "__main__":
    main()
