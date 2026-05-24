from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.metrics import adjusted_rand_score, pairwise_distances

import sys

sys.path.insert(0, "src")
import m5_research_pipeline as p


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


def stability_floor_sensitivity(forecasts: pd.DataFrame, summary: pd.DataFrame, floors: List[float], out_dir: Path) -> pd.DataFrame:
    mean_sales = summary.set_index("id")["mean_sales"]
    demand_class = summary.set_index("id")["demand_class"]
    rows = []
    for floor in floors:
        scale = mean_sales.replace(0, np.nan).fillna(mean_sales.median()).clip(lower=floor)
        for model in forecasts["model"].unique():
            model_df = forecasts.loc[forecasts["model"] == model]
            origins = sorted(model_df["origin"].unique())
            for prev, cur in zip(origins[:-1], origins[1:]):
                left = model_df.loc[model_df["origin"] == prev, ["id", "d", "yhat"]]
                right = model_df.loc[model_df["origin"] == cur, ["id", "d", "yhat"]]
                merged = left.merge(right, on=["id", "d"], suffixes=("_prev", "_cur"))
                merged["abs_change"] = (merged["yhat_cur"] - merged["yhat_prev"]).abs()
                merged["scale"] = merged["id"].map(scale) + 1e-9
                merged["scale_change"] = merged["abs_change"] / merged["scale"]
                merged["demand_class"] = merged["id"].map(demand_class)
                row = {
                    "floor": floor,
                    "model": model,
                    "origin_prev": prev,
                    "origin_cur": cur,
                    "group_type": "overall",
                    "group": "overall",
                    "n": len(merged),
                    "scale_loss": float(merged["scale_change"].mean()),
                    "jump03": float((merged["scale_change"] > 0.3).mean()),
                    "jump05": float((merged["scale_change"] > 0.5).mean()),
                    "wac": float(merged["abs_change"].mean()),
                    "rank_stability": float(spearmanr(merged["yhat_prev"], merged["yhat_cur"]).correlation),
                }
                rows.append(row)
                for demand, grp in merged.groupby("demand_class", observed=True):
                    rows.append(
                        {
                            "floor": floor,
                            "model": model,
                            "origin_prev": prev,
                            "origin_cur": cur,
                            "group_type": "demand_class",
                            "group": demand,
                            "n": len(grp),
                            "scale_loss": float(grp["scale_change"].mean()),
                            "jump03": float((grp["scale_change"] > 0.3).mean()),
                            "jump05": float((grp["scale_change"] > 0.5).mean()),
                            "wac": float(grp["abs_change"].mean()),
                            "rank_stability": float(spearmanr(grp["yhat_prev"], grp["yhat_cur"]).correlation),
                        }
                    )
    out = pd.DataFrame(rows)
    out.to_csv(out_dir / "stability_floor_sensitivity.csv", index=False)
    return out


def stratified_ids(summary: pd.DataFrame, n: int, seed: int) -> List[str]:
    rng = np.random.default_rng(seed)
    picked = []
    groups = summary.groupby(["cat_id", "store_id", "demand_class"], sort=False)
    for _, grp in groups:
        take = max(1, int(round(n * len(grp) / len(summary))))
        picked.extend(rng.choice(grp["id"].to_numpy(), size=min(take, len(grp)), replace=False).tolist())
    if len(picked) > n:
        picked = rng.choice(np.array(picked), size=n, replace=False).tolist()
    return picked


def simple_kmedoids(distance: np.ndarray, k: int, seed: int, max_iter: int = 30) -> Tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    n = distance.shape[0]
    medoids = rng.choice(n, size=k, replace=False)
    labels = np.argmin(distance[:, medoids], axis=1)
    for _ in range(max_iter):
        old_medoids = medoids.copy()
        for cluster in range(k):
            members = np.where(labels == cluster)[0]
            if len(members) == 0:
                medoids[cluster] = rng.integers(0, n)
                continue
            intra = distance[np.ix_(members, members)]
            medoids[cluster] = members[np.argmin(intra.sum(axis=1))]
        labels = np.argmin(distance[:, medoids], axis=1)
        if np.array_equal(old_medoids, medoids):
            break
    return medoids, labels


def kmedoids_robustness(summary: pd.DataFrame, config: dict, out_dir: Path, sample_n_override: int | None = None) -> pd.DataFrame:
    origin = max(config["rolling_origins"])
    k = int(config["selected_k"])
    sample_n = min(sample_n_override or 2000, len(summary))
    sample_ids = stratified_ids(summary, sample_n, int(config["random_seed"]))
    feats = pd.read_parquet(Path(config["outputs_dir"]) / "processed" / f"clustering_features_origin_{origin}.parquet")
    labels = pd.read_csv(Path(config["outputs_dir"]) / "processed" / f"cluster_labels_origin_{origin}.csv")
    sample_feats = feats.loc[feats["id"].isin(sample_ids)].reset_index(drop=True)
    sample_labels = labels.loc[labels["id"].isin(sample_ids), ["id", "cluster_label"]]
    sample_feats = sample_feats.merge(sample_labels, on="id", how="inner")
    x, _ = p.transform_clustering_matrix(sample_feats.drop(columns=["cluster_label"]))
    distance = pairwise_distances(x, metric="euclidean")
    medoids, kmed_labels = simple_kmedoids(distance, k, int(config["random_seed"]))
    ari = adjusted_rand_score(sample_feats["cluster_label"], kmed_labels)
    out = pd.DataFrame(
        [
            {
                "origin": origin,
                "k": k,
                "sample_n": len(sample_feats),
                "ari_kmeans_vs_kmedoids": ari,
                "kmedoids_min_cluster_size": int(pd.Series(kmed_labels).value_counts().min()),
                "kmedoids_max_cluster_size": int(pd.Series(kmed_labels).value_counts().max()),
            }
        ]
    )
    sample_assignments = sample_feats[["id", "cluster_label"]].copy()
    sample_assignments["kmedoids_label"] = kmed_labels
    sample_assignments.to_csv(out_dir / "kmedoids_sample_assignments.csv", index=False)
    out.to_csv(out_dir / "kmedoids_robustness.csv", index=False)
    return out


def block_bootstrap_by_group(forecasts: pd.DataFrame, baseline: str, group_col: str, seed: int, out_dir: Path) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    grouped_metrics = []
    for (model, origin, group), grp in forecasts.groupby(["model", "origin", group_col], observed=True):
        abs_err = (grp["y"] - grp["yhat"]).abs()
        grouped_metrics.append(
            {
                "model": model,
                "origin": origin,
                "group": group,
                "mae": float(abs_err.mean()),
                "wape_num": float(abs_err.sum()),
                "wape_den": float(grp["y"].abs().sum() + 1e-9),
            }
        )
    gm = pd.DataFrame(grouped_metrics)
    for metric in ["mae", "wape"]:
        for model in sorted(set(gm["model"]) - {baseline}):
            diffs = []
            for origin in sorted(gm["origin"].unique()):
                cur = gm.loc[gm["origin"] == origin]
                groups = sorted(cur["group"].unique())
                boot = []
                for _ in range(2000):
                    sampled_groups = rng.choice(groups, size=len(groups), replace=True)
                    b = cur.loc[(cur["model"] == baseline) & (cur["group"].isin(sampled_groups))]
                    m = cur.loc[(cur["model"] == model) & (cur["group"].isin(sampled_groups))]
                    if metric == "mae":
                        diff = m["mae"].mean() - b["mae"].mean()
                    else:
                        diff = (m["wape_num"].sum() / m["wape_den"].sum()) - (b["wape_num"].sum() / b["wape_den"].sum())
                    boot.append(diff)
                diffs.extend(boot)
            rows.append(
                {
                    "group_col": group_col,
                    "metric": metric,
                    "model": model,
                    "mean_diff": float(np.mean(diffs)),
                    "ci_2.5": float(np.quantile(diffs, 0.025)),
                    "ci_97.5": float(np.quantile(diffs, 0.975)),
                    "n_boot": len(diffs),
                }
            )
    out = pd.DataFrame(rows)
    out.to_csv(out_dir / f"block_bootstrap_{group_col}.csv", index=False)
    return out


def residual_bias_diagnostics(forecasts: pd.DataFrame, summary: pd.DataFrame, out_dir: Path) -> pd.DataFrame:
    demand = summary.set_index("id")["demand_class"]
    mean_sales = summary.set_index("id")["mean_sales"]
    df = forecasts.copy()
    df["error"] = df["yhat"] - df["y"]
    df["abs_error"] = df["error"].abs()
    df["demand_class"] = df["id"].map(demand)
    df["low_demand_group"] = pd.cut(df["id"].map(mean_sales), bins=[-1, 0.25, 0.5, 1.0, 1e9], labels=["<=0.25", "0.25-0.5", "0.5-1.0", ">1.0"])
    rows = []
    for group_type, col in [("cluster", "cluster_label"), ("store", "store_id"), ("category", "cat_id"), ("demand_class", "demand_class"), ("low_demand", "low_demand_group")]:
        for (model, group), grp in df.groupby(["model", col], observed=True):
            rows.append(
                {
                    "group_type": group_type,
                    "group": group,
                    "model": model,
                    "n": len(grp),
                    "mae": float(grp["abs_error"].mean()),
                    "bias": float(grp["error"].sum() / (grp["y"].sum() + 1e-9)),
                    "mean_error": float(grp["error"].mean()),
                    "p90_abs_error": float(grp["abs_error"].quantile(0.9)),
                }
            )
    out = pd.DataFrame(rows)
    out.to_csv(out_dir / "residual_bias_diagnostics.csv", index=False)
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/research_config.json")
    parser.add_argument("--kmedoids-sample-n", type=int, default=2000)
    args = parser.parse_args()

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    out_dir = Path(config["outputs_dir"]) / "metrics"
    reports_dir = Path(config["reports_dir"])
    summary = pd.read_parquet(Path(config["outputs_dir"]) / "eda" / "series_summary.parquet")
    forecasts = pd.read_parquet(out_dir / "test_forecasts.parquet")

    floor = stability_floor_sensitivity(forecasts, summary, [0.05, 0.1, 0.25], out_dir)
    kmedoids = kmedoids_robustness(summary, config, out_dir, args.kmedoids_sample_n)
    boot_store = block_bootstrap_by_group(forecasts, "A0_global_baseline", "store_id", int(config["random_seed"]), out_dir)
    boot_cat = block_bootstrap_by_group(forecasts, "A0_global_baseline", "cat_id", int(config["random_seed"]), out_dir)
    residual = residual_bias_diagnostics(forecasts, summary, out_dir)

    lines = ["# Advanced Diagnostics Report", ""]
    lines.append("## Stability Floor Sensitivity")
    overall = floor.loc[floor["group_type"] == "overall"].groupby(["floor", "model"])[["scale_loss", "jump03", "jump05", "wac"]].mean().reset_index()
    lines.append(md_table(overall))
    lines.append("")
    lines.append("## K-Medoids Robustness")
    lines.append(md_table(kmedoids))
    lines.append("")
    lines.append("## Block Bootstrap By Store")
    lines.append(md_table(boot_store))
    lines.append("")
    lines.append("## Block Bootstrap By Category")
    lines.append(md_table(boot_cat))
    lines.append("")
    lines.append("## Residual/Bias Highlights")
    highlights = residual.sort_values("mae", ascending=False).head(20)
    lines.append(md_table(highlights))
    lines.append("")
    lines.append("## Notes")
    lines.append("- K-Medoids is implemented as a simple PAM-style check on a stratified sample, not a production clustering replacement.")
    lines.append("- Bootstrap CIs are block-style by group and use MAE/WAPE on recursive sampled forecasts.")
    (reports_dir / "advanced_diagnostics_report.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
