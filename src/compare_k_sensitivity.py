from __future__ import annotations

from pathlib import Path

import pandas as pd


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


def load_outputs(label: str, outputs_dir: str) -> dict:
    metrics = Path(outputs_dir) / "metrics"
    return {
        "label": label,
        "model": pd.read_csv(metrics / "model_test_metrics.csv"),
        "wrmsse": pd.read_csv(metrics / "sampled_wrmsse_overall.csv"),
        "stability": pd.read_csv(metrics / "forecast_stability_metrics.csv"),
        "clustering": pd.read_csv(metrics / "clustering_quality_metrics.csv"),
        "overfit": pd.read_csv(metrics / "model_train_val_test_metrics.csv"),
        "cluster_status": pd.read_csv(metrics / "cluster_specific_model_status.csv"),
    }


def summarize_run(run: dict) -> dict:
    label = run["label"]
    model = run["model"].groupby("model")[["rmsse_item_store", "mae", "wape", "bias"]].mean().reset_index()
    model.insert(0, "k_config", label)
    wr = run["wrmsse"].groupby("model")["sampled_wrmsse_12level"].mean().reset_index()
    wr.insert(0, "k_config", label)
    st = run["stability"].groupby("model")[["scale_aware_stability_loss", "weighted_absolute_change", "jump_rate_tau_0.3", "jump_rate_tau_0.5"]].mean().reset_index()
    st.insert(0, "k_config", label)
    cl = run["clustering"]
    selected_k = int(label.replace("K=", ""))
    cl = cl.loc[cl["k"] == selected_k].groupby("k")[["silhouette", "davies_bouldin", "min_cluster_size"]].mean().reset_index()
    cl.insert(0, "k_config", label)
    of = run["overfit"].pivot_table(index=["origin", "model"], columns="split", values="rmsse_item_store").reset_index()
    of["test_train_gap"] = of["test"] - of["train"]
    of = of.groupby("model")["test_train_gap"].mean().reset_index()
    of.insert(0, "k_config", label)
    return {"model": model, "wrmsse": wr, "stability": st, "clustering": cl, "overfit": of}


def main() -> None:
    reports = Path("reports")
    reports.mkdir(exist_ok=True)
    out_metrics = Path("outputs/metrics")
    runs = [load_outputs("K=5", "outputs"), load_outputs("K=3", "outputs_k3")]
    summaries = [summarize_run(r) for r in runs]
    model = pd.concat([s["model"] for s in summaries], ignore_index=True)
    wr = pd.concat([s["wrmsse"] for s in summaries], ignore_index=True)
    st = pd.concat([s["stability"] for s in summaries], ignore_index=True)
    cl = pd.concat([s["clustering"] for s in summaries], ignore_index=True)
    of = pd.concat([s["overfit"] for s in summaries], ignore_index=True)

    merged = model.merge(wr, on=["k_config", "model"], how="left").merge(st, on=["k_config", "model"], how="left").merge(of, on=["k_config", "model"], how="left")
    merged = merged.sort_values(["sampled_wrmsse_12level", "rmsse_item_store"])
    merged.to_csv(out_metrics / "k_sensitivity_model_comparison.csv", index=False)
    cl.to_csv(out_metrics / "k_sensitivity_clustering_comparison.csv", index=False)

    best_by_metric = pd.DataFrame(
        [
            {"metric": "item_store_rmsse", **merged.loc[merged["rmsse_item_store"].idxmin()].to_dict()},
            {"metric": "sampled_wrmsse_12level", **merged.loc[merged["sampled_wrmsse_12level"].idxmin()].to_dict()},
            {"metric": "scale_aware_stability_loss", **merged.loc[merged["scale_aware_stability_loss"].idxmin()].to_dict()},
            {"metric": "weighted_absolute_change", **merged.loc[merged["weighted_absolute_change"].idxmin()].to_dict()},
        ]
    )
    best_by_metric.to_csv(out_metrics / "k_sensitivity_best_by_metric.csv", index=False)

    lines = ["# K Sensitivity Report", ""]
    lines.append("## Clustering Quality")
    lines.append(md_table(cl))
    lines.append("")
    lines.append("## Model Comparison")
    cols = [
        "k_config",
        "model",
        "rmsse_item_store",
        "sampled_wrmsse_12level",
        "scale_aware_stability_loss",
        "weighted_absolute_change",
        "jump_rate_tau_0.3",
        "test_train_gap",
        "mae",
        "wape",
        "bias",
    ]
    lines.append(md_table(merged[cols]))
    lines.append("")
    lines.append("## Best By Metric")
    lines.append(md_table(best_by_metric[["metric"] + cols]))
    lines.append("")
    lines.append("## Interpretation")
    lines.append("- K=3 has better clustering geometry than K=5 if silhouette/Davies-Bouldin are prioritized.")
    lines.append("- The final choice should prioritize WRMSSE/stability and robustness, not clustering geometry alone.")
    (reports / "k_sensitivity_report.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
