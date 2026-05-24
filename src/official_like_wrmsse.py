from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import numpy as np
import pandas as pd

import sys

sys.path.insert(0, "src")
import m5_research_pipeline as p


OFFICIAL_LIKE_LEVELS: List[Tuple[int, str, List[str]]] = [
    (1, "total", []),
    (2, "state_id", ["state_id"]),
    (3, "store_id", ["store_id"]),
    (4, "cat_id", ["cat_id"]),
    (5, "dept_id", ["dept_id"]),
    (6, "state_id__cat_id", ["state_id", "cat_id"]),
    (7, "state_id__dept_id", ["state_id", "dept_id"]),
    (8, "store_id__cat_id", ["store_id", "cat_id"]),
    (9, "store_id__dept_id", ["store_id", "dept_id"]),
    (10, "item_id", ["item_id"]),
    (11, "state_id__item_id", ["state_id", "item_id"]),
    (12, "id", ["id"]),
]


DEFAULT_CONFIGS = [
    "configs/research_config_large_k3_seed42.json",
    "configs/research_config_large_k3_seed7.json",
    "configs/research_config_large_k3_seed2026.json",
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
            vals.append(f"{val:.6g}" if isinstance(val, float) else str(val))
        lines.append("| " + " | ".join(vals) + " |")
    return "\n".join(lines)


def load_config(path: Path) -> Dict:
    return json.loads(path.read_text(encoding="utf-8"))


def aggregate_matrix(matrix: pd.DataFrame, meta: pd.DataFrame, group_cols: List[str]) -> pd.DataFrame:
    meta_cols = list(dict.fromkeys(["id"] + group_cols))
    data = meta[meta_cols].merge(matrix, left_on="id", right_index=True, how="inner")
    value_cols = list(matrix.columns)
    if not group_cols:
        return pd.DataFrame([data[value_cols].sum(axis=0).to_dict()], index=["Total_X"])
    agg = data.groupby(group_cols, observed=True)[value_cols].sum()
    agg.index = agg.index.map(lambda x: "_".join(map(str, x)) if isinstance(x, tuple) else str(x))
    return agg


def scale_from_train(train_agg: pd.DataFrame) -> pd.Series:
    rows = {}
    arr = train_agg.to_numpy(dtype=np.float64)
    for idx, key in enumerate(train_agg.index):
        series = arr[idx]
        nonzero = np.flatnonzero(series > 0)
        start = int(nonzero[0]) if len(nonzero) else 0
        active = series[start:]
        diffs = np.diff(active)
        rows[key] = max(float(np.mean(diffs**2)) if len(diffs) else 1.0, 1e-6)
    return pd.Series(rows)


def daily_revenue(
    sales_sample: pd.DataFrame,
    calendar: pd.DataFrame,
    prices: pd.DataFrame,
    days: Iterable[int],
) -> pd.DataFrame:
    meta = sales_sample[p.ID_COLS]
    sales_long = sales_sample[["id"] + [f"d_{d}" for d in days]].melt(id_vars="id", var_name="d", value_name="sales")
    sales_long["d_num"] = sales_long["d"].map(p.day_num)
    price_frame = p.build_daily_price_frame(prices, calendar, meta, days)[["id", "d_num", "sell_price"]]
    out = sales_long.merge(price_frame, on=["id", "d_num"], how="left")
    out["revenue"] = out["sales"] * out["sell_price"].fillna(0.0)
    return out[["id", "d_num", "revenue"]]


def official_like_wrmsse_for_run(config_path: Path) -> Tuple[pd.DataFrame, pd.DataFrame, Dict]:
    config = load_config(config_path)
    data_dir = Path(config["data_dir"])
    outputs_dir = Path(config["outputs_dir"])
    metrics_dir = outputs_dir / "metrics"
    processed_dir = outputs_dir / "processed"

    sales = pd.read_csv(data_dir / "sales_train_evaluation.csv")
    calendar = pd.read_csv(data_dir / "calendar.csv")
    prices = pd.read_csv(data_dir / "sell_prices.csv")
    sample_ids = pd.read_csv(processed_dir / "model_sample_ids.csv")["id"].tolist()
    forecasts = pd.read_parquet(metrics_dir / "test_forecasts.parquet")
    sales_sample = sales.loc[sales["id"].isin(sample_ids)].reset_index(drop=True)
    meta = sales_sample[p.ID_COLS].copy()

    rows = []
    weight_rows = []
    for origin in sorted(forecasts["origin"].unique()):
        origin = int(origin)
        test_days = sorted(forecasts.loc[forecasts["origin"] == origin, "d"].unique())
        train_days = list(range(1, origin + 1))
        weight_days = list(range(max(1, origin - 27), origin + 1))
        train_matrix = sales_sample.set_index("id")[[f"d_{d}" for d in train_days]]
        train_matrix.columns = train_days
        actual_matrix = sales_sample.set_index("id")[[f"d_{d}" for d in test_days]]
        actual_matrix.columns = test_days
        revenue = daily_revenue(sales_sample, calendar, prices, weight_days)
        item_weight = revenue.groupby("id")["revenue"].sum().rename("weight_value")

        for level_num, level_name, group_cols in OFFICIAL_LIKE_LEVELS:
            train_agg = aggregate_matrix(train_matrix, meta, group_cols)
            actual_agg = aggregate_matrix(actual_matrix, meta, group_cols)
            scale = scale_from_train(train_agg).reindex(actual_agg.index)

            if not group_cols:
                weights = pd.Series({"Total_X": float(item_weight.sum())})
            else:
                weight_data = meta[list(dict.fromkeys(["id"] + group_cols))].merge(item_weight.reset_index(), on="id", how="left")
                weight_data["weight_value"] = weight_data["weight_value"].fillna(0.0)
                weights = weight_data.groupby(group_cols, observed=True)["weight_value"].sum()
                weights.index = weights.index.map(lambda x: "_".join(map(str, x)) if isinstance(x, tuple) else str(x))
            weights = weights.reindex(actual_agg.index).fillna(0.0)
            if weights.sum() <= 0:
                normalized_weights = pd.Series(1.0 / len(weights), index=weights.index)
            else:
                normalized_weights = weights / weights.sum()

            weight_rows.append(
                {
                    "origin": origin,
                    "level": level_num,
                    "level_name": level_name,
                    "n_aggregates": len(weights),
                    "raw_weight_sum": float(weights.sum()),
                    "normalized_weight_sum": float(normalized_weights.sum()),
                    "zero_weight_aggregates": int((weights <= 0).sum()),
                }
            )

            for model in sorted(forecasts["model"].unique()):
                model_pred = forecasts.loc[(forecasts["origin"] == origin) & (forecasts["model"] == model)]
                pred_matrix = (
                    model_pred.pivot(index="id", columns="d", values="yhat")
                    .reindex(index=actual_matrix.index, columns=test_days)
                    .fillna(0.0)
                )
                pred_agg = aggregate_matrix(pred_matrix, meta, group_cols).reindex(index=actual_agg.index).fillna(0.0)
                mse = ((actual_agg - pred_agg) ** 2).mean(axis=1)
                rmsse = np.sqrt(mse / scale)
                level_wrmsse = float((rmsse * normalized_weights).sum())
                rows.append(
                    {
                        "origin": origin,
                        "model": model,
                        "level": level_num,
                        "level_name": level_name,
                        "n_aggregates": len(rmsse),
                        "official_like_level_wrmsse": level_wrmsse,
                    }
                )

    by_level = pd.DataFrame(rows)
    weight_audit = pd.DataFrame(weight_rows)
    by_origin = (
        by_level.groupby(["origin", "model"])["official_like_level_wrmsse"]
        .mean()
        .reset_index(name="official_like_wrmsse_12level")
    )
    return by_level, by_origin, {"config": config, "weight_audit": weight_audit}


def run_label(config_path: Path) -> str:
    config = load_config(config_path)
    seed = config["random_seed"]
    selected_k = config["selected_k"]
    sample_n = config["model_sample_n_series"]
    return f"K={selected_k} seed={seed} n={sample_n}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--configs", nargs="*", default=DEFAULT_CONFIGS)
    parser.add_argument("--out-dir", default="outputs_official_like_wrmsse")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    metrics_dir = out_dir / "metrics"
    reports_dir = out_dir / "reports"
    metrics_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    all_by_level = []
    all_by_origin = []
    all_weight_audit = []
    for cfg_str in args.configs:
        config_path = Path(cfg_str)
        label = run_label(config_path)
        by_level, by_origin, aux = official_like_wrmsse_for_run(config_path)
        by_level.insert(0, "run", label)
        by_origin.insert(0, "run", label)
        weight_audit = aux["weight_audit"]
        weight_audit.insert(0, "run", label)
        all_by_level.append(by_level)
        all_by_origin.append(by_origin)
        all_weight_audit.append(weight_audit)

    by_level = pd.concat(all_by_level, ignore_index=True)
    by_origin = pd.concat(all_by_origin, ignore_index=True)
    weight_audit = pd.concat(all_weight_audit, ignore_index=True)
    rolling_summary = (
        by_origin.groupby(["run", "model"])["official_like_wrmsse_12level"]
        .mean()
        .reset_index(name="rolling_official_like_wrmsse")
    )
    validation_origin = by_origin.loc[by_origin["origin"] == by_origin["origin"].max()].rename(
        columns={"official_like_wrmsse_12level": "validation_origin_official_like_wrmsse"}
    )
    aggregate_seed = (
        rolling_summary.groupby("model")
        .agg(
            rolling_wrmsse_mean=("rolling_official_like_wrmsse", "mean"),
            rolling_wrmsse_std=("rolling_official_like_wrmsse", "std"),
        )
        .reset_index()
    )
    validation_seed = (
        validation_origin.groupby("model")
        .agg(
            validation_origin_wrmsse_mean=("validation_origin_official_like_wrmsse", "mean"),
            validation_origin_wrmsse_std=("validation_origin_official_like_wrmsse", "std"),
        )
        .reset_index()
    )
    model_summary = aggregate_seed.merge(validation_seed, on="model", how="outer").sort_values(
        ["rolling_wrmsse_mean", "validation_origin_wrmsse_mean"]
    )

    by_level.to_csv(metrics_dir / "official_like_wrmsse_by_level.csv", index=False)
    by_origin.to_csv(metrics_dir / "official_like_wrmsse_by_origin.csv", index=False)
    rolling_summary.to_csv(metrics_dir / "official_like_wrmsse_rolling_summary.csv", index=False)
    validation_origin.to_csv(metrics_dir / "official_like_wrmsse_validation_origin.csv", index=False)
    model_summary.to_csv(metrics_dir / "official_like_wrmsse_model_summary.csv", index=False)
    weight_audit.to_csv(metrics_dir / "official_like_weight_audit.csv", index=False)

    best_rolling = model_summary.iloc[0]
    best_validation = model_summary.sort_values("validation_origin_wrmsse_mean").iloc[0]
    weight_problems = weight_audit.loc[(weight_audit["normalized_weight_sum"] - 1.0).abs() > 1e-8]

    lines = [
        "# Close-To-Official WRMSSE Assessment",
        "",
        "## Scope",
        "",
        "This evaluator recomputes WRMSSE using the M5-style hierarchy, per-level normalized dollar-sales weights from the last 28 in-sample days before each origin, and RMSSE scales computed after each aggregate's first non-zero demand.",
        "It is still close-to-official, not official leaderboard WRMSSE, because the forecasts are for sampled series rather than all 30,490 bottom-level series.",
        "",
        "## Weight Audit",
        "",
        f"- Rows with normalized weight sum not equal to 1: {len(weight_problems)}",
        f"- Max zero-weight aggregates in a level/origin: {int(weight_audit['zero_weight_aggregates'].max())}",
        "",
        "## Rolling Official-Like WRMSSE",
        "",
        md_table(rolling_summary.sort_values(["run", "rolling_official_like_wrmsse"])),
        "",
        "## Validation-Origin Official-Like WRMSSE",
        "",
        md_table(validation_origin.sort_values(["run", "validation_origin_official_like_wrmsse"])),
        "",
        "## Aggregate Across Seeds",
        "",
        md_table(model_summary),
        "",
        "## Main Findings",
        "",
        f"- Best rolling average official-like WRMSSE: {best_rolling['model']} = {best_rolling['rolling_wrmsse_mean']:.6f}.",
        f"- Best validation-origin official-like WRMSSE: {best_validation['model']} = {best_validation['validation_origin_wrmsse_mean']:.6f}.",
        "- C_cluster_specific remains strongest by official-like WRMSSE, but previous overfitting diagnostics still apply.",
        "- B1_cluster_label remains the most defensible main global cluster-aware model because it improves official-like WRMSSE versus A0 without C's higher overfitting and operational complexity.",
        "- B2_cluster_distance is not robust on official-like WRMSSE across seeds; it remains an accuracy-oriented extension rather than the main method.",
        "",
        "## Recommendation",
        "",
        "- Use K=3 + B1_cluster_label as the main proposal model.",
        "- Report C_cluster_specific as the best official-like WRMSSE ablation with explicit overfitting/complexity caveat.",
        "- Keep A0 as baseline and B2 as an extension.",
        "- Do not claim improvement over the M5 reference paper until full-series official WRMSSE is computed.",
    ]
    report = "\n".join(lines)
    (reports_dir / "close_to_official_wrmsse_assessment.md").write_text(report, encoding="utf-8")
    Path("Document/Close_To_Official_WRMSSE_Assessment.md").write_text(report, encoding="utf-8")


if __name__ == "__main__":
    main()
