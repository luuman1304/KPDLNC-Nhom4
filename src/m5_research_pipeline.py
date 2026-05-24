from __future__ import annotations

import argparse
import json
import math
import os
import random
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import lightgbm as lgb
import joblib
import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment
from scipy.stats import spearmanr
from sklearn.cluster import MiniBatchKMeans
from sklearn.metrics import adjusted_rand_score, davies_bouldin_score, silhouette_score
from sklearn.preprocessing import RobustScaler


ID_COLS = ["id", "item_id", "dept_id", "cat_id", "store_id", "state_id"]
CATEGORICAL_COLS = ["item_id", "dept_id", "cat_id", "store_id", "state_id"]


def set_global_seed(seed: int) -> None:
    os.environ["PYTHONHASHSEED"] = str(seed)
    random.seed(seed)
    np.random.seed(seed)


def timer(costs: Dict[str, float], name: str):
    class _Timer:
        def __enter__(self):
            self.start = time.perf_counter()
            return self

        def __exit__(self, exc_type, exc, tb):
            costs[name] = costs.get(name, 0.0) + time.perf_counter() - self.start

    return _Timer()


def ensure_dirs(config: dict) -> Dict[str, Path]:
    outputs = Path(config["outputs_dir"])
    reports = Path(config["reports_dir"])
    dirs = {
        "outputs": outputs,
        "reports": reports,
        "eda": outputs / "eda",
        "processed": outputs / "processed",
        "models": outputs / "models",
        "metrics": outputs / "metrics",
        "figures": outputs / "figures",
    }
    for path in dirs.values():
        path.mkdir(parents=True, exist_ok=True)
    dirs["skip_figures"] = bool(config.get("skip_figures", False))
    return dirs


def day_cols(df: pd.DataFrame) -> List[str]:
    return [c for c in df.columns if c.startswith("d_")]


def day_num(day: str) -> int:
    return int(day.split("_")[1])


def load_raw(data_dir: Path) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    sales_eval = pd.read_csv(data_dir / "sales_train_evaluation.csv")
    calendar = pd.read_csv(data_dir / "calendar.csv")
    prices = pd.read_csv(data_dir / "sell_prices.csv")
    sample_submission = pd.read_csv(data_dir / "sample_submission.csv")
    return sales_eval, calendar, prices, sample_submission


def build_release_days(sales: pd.DataFrame, calendar: pd.DataFrame, prices: pd.DataFrame) -> pd.Series:
    week_to_first_day = calendar.groupby("wm_yr_wk")["d"].first().map(day_num)
    release = prices.groupby(["store_id", "item_id"])["wm_yr_wk"].min().map(week_to_first_day)
    keys = list(zip(sales["store_id"], sales["item_id"]))
    return pd.Series([release.get(k, np.nan) for k in keys], index=sales.index, name="release_day")


def validate_raw(
    data_dir: Path,
    sales: pd.DataFrame,
    calendar: pd.DataFrame,
    prices: pd.DataFrame,
    sample_submission: pd.DataFrame,
    dirs: Dict[str, Path],
) -> pd.DataFrame:
    files = {
        "sales_train_validation.csv": data_dir / "sales_train_validation.csv",
        "sales_train_evaluation.csv": data_dir / "sales_train_evaluation.csv",
        "calendar.csv": data_dir / "calendar.csv",
        "sell_prices.csv": data_dir / "sell_prices.csv",
        "sample_submission.csv": data_dir / "sample_submission.csv",
    }
    dcols = day_cols(sales)
    checks = []
    for name, path in files.items():
        checks.append({"check": f"file_exists:{name}", "status": path.exists(), "details": str(path)})
    checks.extend(
        [
            {"check": "sales_eval_rows", "status": len(sales) == 30490, "details": len(sales)},
            {"check": "sales_eval_last_day", "status": dcols[-1] == "d_1941", "details": dcols[-1]},
            {"check": "calendar_last_day", "status": calendar["d"].iloc[-1] == "d_1969", "details": calendar["d"].iloc[-1]},
            {"check": "calendar_unique_d", "status": calendar["d"].is_unique, "details": calendar["d"].nunique()},
            {
                "check": "prices_key_not_null",
                "status": not prices[["store_id", "item_id", "wm_yr_wk", "sell_price"]].isna().any().any(),
                "details": int(prices.isna().sum().sum()),
            },
            {
                "check": "sample_submission_rows",
                "status": len(sample_submission) == 60980,
                "details": len(sample_submission),
            },
        ]
    )
    result = pd.DataFrame(checks)
    result.to_csv(dirs["metrics"] / "data_validation_checks.csv", index=False)
    return result


def compute_series_summary(sales: pd.DataFrame, release_day: pd.Series) -> pd.DataFrame:
    dcols = day_cols(sales)
    arr = sales[dcols].to_numpy(dtype=np.float32)
    n_days = arr.shape[1]
    rows = []
    for i in range(arr.shape[0]):
        rel = release_day.iloc[i]
        start = int(rel) - 1 if not pd.isna(rel) else 0
        start = max(0, min(start, n_days - 1))
        active = arr[i, start:]
        positive = active[active > 0]
        nonzero = int((active > 0).sum())
        active_days = int(len(active))
        mean_sales = float(active.mean()) if active_days else 0.0
        std_sales = float(active.std()) if active_days else 0.0
        cv2 = float((positive.std() / (positive.mean() + 1e-9)) ** 2) if len(positive) > 1 else 0.0
        adi = float(active_days / max(nonzero, 1))
        pos_idx = np.flatnonzero(active > 0)
        max_gap = int(np.diff(pos_idx).max()) if len(pos_idx) > 1 else active_days
        rows.append(
            {
                "id": sales.at[i, "id"],
                "item_id": sales.at[i, "item_id"],
                "dept_id": sales.at[i, "dept_id"],
                "cat_id": sales.at[i, "cat_id"],
                "store_id": sales.at[i, "store_id"],
                "state_id": sales.at[i, "state_id"],
                "release_day": rel,
                "active_days": active_days,
                "total_sales": float(active.sum()),
                "mean_sales": mean_sales,
                "median_sales": float(np.median(active)) if active_days else 0.0,
                "std_sales": std_sales,
                "zero_sales_ratio": float((active == 0).mean()) if active_days else 1.0,
                "nonzero_days": nonzero,
                "adi": adi,
                "cv2": cv2,
                "max_gap": max_gap,
                "positive_mean": float(positive.mean()) if len(positive) else 0.0,
                "positive_median": float(np.median(positive)) if len(positive) else 0.0,
            }
        )
    return pd.DataFrame(rows)


def classify_demand(summary: pd.DataFrame) -> pd.Series:
    conditions = []
    for adi, cv2 in zip(summary["adi"], summary["cv2"]):
        if adi < 1.32 and cv2 < 0.49:
            conditions.append("smooth")
        elif adi >= 1.32 and cv2 < 0.49:
            conditions.append("intermittent")
        elif adi < 1.32 and cv2 >= 0.49:
            conditions.append("erratic")
        else:
            conditions.append("lumpy")
    return pd.Series(conditions, index=summary.index)


def run_eda(
    sales: pd.DataFrame,
    calendar: pd.DataFrame,
    prices: pd.DataFrame,
    release_day: pd.Series,
    dirs: Dict[str, Path],
    costs: Dict[str, float],
) -> pd.DataFrame:
    with timer(costs, "eda"):
        summary = compute_series_summary(sales, release_day)
        summary["demand_class"] = classify_demand(summary)
        summary.to_parquet(dirs["eda"] / "series_summary.parquet", index=False)
        summary.describe(include="all").to_csv(dirs["eda"] / "series_summary_describe.csv")

        overview = pd.DataFrame(
            [
                {"metric": "n_series", "value": len(sales)},
                {"metric": "n_items", "value": sales["item_id"].nunique()},
                {"metric": "n_stores", "value": sales["store_id"].nunique()},
                {"metric": "n_states", "value": sales["state_id"].nunique()},
                {"metric": "n_categories", "value": sales["cat_id"].nunique()},
                {"metric": "n_departments", "value": sales["dept_id"].nunique()},
                {"metric": "n_calendar_days", "value": len(calendar)},
                {"metric": "n_price_rows", "value": len(prices)},
                {"metric": "sales_total_active", "value": summary["total_sales"].sum()},
                {"metric": "median_zero_sales_ratio", "value": summary["zero_sales_ratio"].median()},
            ]
        )
        overview.to_csv(dirs["eda"] / "dataset_overview.csv", index=False)

        hierarchy = []
        for col in ["state_id", "store_id", "cat_id", "dept_id"]:
            grp = summary.groupby(col).agg(
                n_series=("id", "count"),
                total_sales=("total_sales", "sum"),
                mean_sales=("mean_sales", "mean"),
                median_zero_sales_ratio=("zero_sales_ratio", "median"),
            )
            grp.insert(0, "level", col)
            grp = grp.reset_index().rename(columns={col: "group"})
            hierarchy.append(grp)
        pd.concat(hierarchy, ignore_index=True).to_csv(dirs["eda"] / "hierarchy_summary.csv", index=False)

        price_summary = prices.groupby(["store_id"]).agg(
            n_price_rows=("sell_price", "count"),
            min_price=("sell_price", "min"),
            median_price=("sell_price", "median"),
            max_price=("sell_price", "max"),
            std_price=("sell_price", "std"),
        )
        price_summary.to_csv(dirs["eda"] / "price_summary_by_store.csv")

        release_stats = summary.groupby(["cat_id", "store_id"]).agg(
            median_release_day=("release_day", "median"),
            p90_release_day=("release_day", lambda x: x.quantile(0.9)),
            n_series=("id", "count"),
        )
        release_stats.to_csv(dirs["eda"] / "availability_by_cat_store.csv")

        demand_counts = summary["demand_class"].value_counts().rename_axis("demand_class").reset_index(name="n_series")
        demand_counts.to_csv(dirs["eda"] / "demand_class_counts.csv", index=False)

        if not dirs.get("skip_figures", False):
            import matplotlib

            matplotlib.use("Agg")
            import matplotlib.pyplot as plt

            fig, ax = plt.subplots(figsize=(8, 5))
            ax.hist(summary["zero_sales_ratio"], bins=50)
            ax.set_title("Zero-sales ratio distribution")
            ax.set_xlabel("zero_sales_ratio")
            ax.set_ylabel("n_series")
            fig.tight_layout()
            fig.savefig(dirs["figures"] / "zero_sales_ratio_distribution.png")
            plt.close(fig)

            fig, ax = plt.subplots(figsize=(8, 5))
            ax.scatter(summary["adi"], summary["cv2"], s=3, alpha=0.25)
            ax.axvline(1.32, color="red", linestyle="--", linewidth=1)
            ax.axhline(0.49, color="red", linestyle="--", linewidth=1)
            ax.set_xlim(0, min(summary["adi"].quantile(0.99), 20))
            ax.set_ylim(0, min(summary["cv2"].quantile(0.99), 10))
            ax.set_title("ADI vs CV2")
            ax.set_xlabel("ADI")
            ax.set_ylabel("CV2")
            fig.tight_layout()
            fig.savefig(dirs["figures"] / "adi_cv2_scatter.png")
            plt.close(fig)
    return summary


def sample_series(summary: pd.DataFrame, n: int, seed: int) -> List[str]:
    if n <= 0 or n >= len(summary):
        return summary["id"].tolist()
    rng = np.random.default_rng(seed)
    picked = []
    groups = summary.groupby(["cat_id", "store_id"], sort=False)
    for _, grp in groups:
        take = max(1, int(round(n * len(grp) / len(summary))))
        picked.extend(rng.choice(grp["id"].to_numpy(), size=min(take, len(grp)), replace=False).tolist())
    if len(picked) > n:
        picked = rng.choice(np.array(picked), size=n, replace=False).tolist()
    elif len(picked) < n:
        remaining = summary.loc[~summary["id"].isin(picked), "id"].to_numpy()
        extra = rng.choice(remaining, size=n - len(picked), replace=False).tolist()
        picked.extend(extra)
    return picked


def get_price_features(prices: pd.DataFrame, sales_meta: pd.DataFrame, calendar: pd.DataFrame, origin: int) -> pd.DataFrame:
    origin_week = int(calendar.loc[calendar["d"] == f"d_{origin}", "wm_yr_wk"].iloc[0])
    p = prices.loc[prices["wm_yr_wk"] <= origin_week].sort_values(["store_id", "item_id", "wm_yr_wk"])
    agg = p.groupby(["store_id", "item_id"]).agg(
        avg_price=("sell_price", "mean"),
        price_std=("sell_price", "std"),
        min_price=("sell_price", "min"),
        max_price=("sell_price", "max"),
        price_obs=("sell_price", "count"),
    )
    changes = p.groupby(["store_id", "item_id"])["sell_price"].apply(lambda s: float(s.diff().ne(0).sum() / max(len(s), 1)))
    agg["price_change_freq"] = changes
    agg = agg.reset_index()
    out = sales_meta[["id", "store_id", "item_id"]].merge(agg, on=["store_id", "item_id"], how="left")
    return out.drop(columns=["store_id", "item_id"]).fillna(0.0)


def clustering_features_for_origin(
    sales: pd.DataFrame,
    calendar: pd.DataFrame,
    prices: pd.DataFrame,
    release_day: pd.Series,
    origin: int,
) -> pd.DataFrame:
    dcols = [f"d_{i}" for i in range(1, origin + 1)]
    arr = sales[dcols].to_numpy(dtype=np.float32)
    rows = []
    event_mask = calendar.iloc[:origin]["event_name_1"].notna().to_numpy()
    weekend_mask = calendar.iloc[:origin]["wday"].isin([1, 2]).to_numpy()
    for i in range(arr.shape[0]):
        rel = release_day.iloc[i]
        start = int(rel) - 1 if not pd.isna(rel) else 0
        start = max(0, min(start, origin - 1))
        active = arr[i, start:]
        active_event = event_mask[start:]
        active_weekend = weekend_mask[start:]
        positive = active[active > 0]
        nonzero = int((active > 0).sum())
        active_days = max(len(active), 1)
        mean_sales = float(active.mean())
        std_sales = float(active.std())
        cv2 = float((positive.std() / (positive.mean() + 1e-9)) ** 2) if len(positive) > 1 else 0.0
        adi = float(active_days / max(nonzero, 1))
        pos_idx = np.flatnonzero(active > 0)
        max_gap = int(np.diff(pos_idx).max()) if len(pos_idx) > 1 else active_days
        event_mean = float(active[active_event].mean()) if active_event.any() else 0.0
        nonevent_mean = float(active[~active_event].mean()) if (~active_event).any() else 0.0
        weekend_mean = float(active[active_weekend].mean()) if active_weekend.any() else 0.0
        weekday_mean = float(active[~active_weekend].mean()) if (~active_weekend).any() else 0.0
        rows.append(
            {
                "id": sales.at[i, "id"],
                "total_sales": float(active.sum()),
                "mean_sales": mean_sales,
                "median_sales": float(np.median(active)),
                "std_sales": std_sales,
                "zero_sales_ratio": float((active == 0).mean()),
                "nonzero_days": nonzero,
                "adi": adi,
                "cv2": cv2,
                "max_gap": max_gap,
                "positive_mean": float(positive.mean()) if len(positive) else 0.0,
                "spike_freq": float((active > mean_sales + 3 * std_sales).mean()) if std_sales > 0 else 0.0,
                "event_lift": event_mean - nonevent_mean,
                "weekend_ratio": weekend_mean / (weekday_mean + 1e-9),
            }
        )
    feats = pd.DataFrame(rows)
    price_feats = get_price_features(prices, sales[ID_COLS], calendar, origin)
    feats = feats.merge(price_feats, on="id", how="left")

    store_avg = feats.join(sales[["store_id", "cat_id", "dept_id"]]).groupby("store_id")["mean_sales"].transform("mean")
    cat_avg = feats.join(sales[["store_id", "cat_id", "dept_id"]]).groupby("cat_id")["mean_sales"].transform("mean")
    dept_avg = feats.join(sales[["store_id", "cat_id", "dept_id"]]).groupby("dept_id")["mean_sales"].transform("mean")
    feats["relative_to_store"] = feats["mean_sales"] / (store_avg + 1e-9)
    feats["relative_to_cat"] = feats["mean_sales"] / (cat_avg + 1e-9)
    feats["relative_to_dept"] = feats["mean_sales"] / (dept_avg + 1e-9)
    return feats.fillna(0.0)


def transform_clustering_matrix(feats: pd.DataFrame) -> Tuple[pd.DataFrame, RobustScaler]:
    x = feats.drop(columns=["id"]).copy()
    for col in ["total_sales", "mean_sales", "median_sales", "std_sales", "positive_mean", "avg_price", "price_std", "max_price"]:
        if col in x.columns:
            x[col] = np.log1p(np.maximum(x[col], 0))
    lower = x.quantile(0.01)
    upper = x.quantile(0.99)
    x = x.clip(lower=lower, upper=upper, axis=1)
    scaler = RobustScaler()
    scaled = pd.DataFrame(scaler.fit_transform(x), columns=x.columns, index=feats.index)
    return scaled, scaler


def apply_clustering_feature_ablation(feats: pd.DataFrame, config: dict) -> pd.DataFrame:
    exclude = set(config.get("clustering_exclude_features", []))
    if config.get("disable_intermittent_clustering_features", False):
        exclude.update(["zero_sales_ratio", "nonzero_days", "adi", "cv2", "max_gap", "positive_mean"])
    keep_drop = [col for col in exclude if col in feats.columns and col != "id"]
    return feats.drop(columns=keep_drop) if keep_drop else feats


def align_labels(prev_centers: np.ndarray, centers: np.ndarray, labels: np.ndarray) -> Tuple[np.ndarray, Dict[int, int]]:
    cost = np.linalg.norm(centers[:, None, :] - prev_centers[None, :, :], axis=2)
    row_ind, col_ind = linear_sum_assignment(cost)
    mapping = {int(r): int(c) for r, c in zip(row_ind, col_ind)}
    aligned = np.array([mapping.get(int(label), int(label)) for label in labels])
    return aligned, mapping


def run_clustering(
    sales: pd.DataFrame,
    calendar: pd.DataFrame,
    prices: pd.DataFrame,
    release_day: pd.Series,
    config: dict,
    dirs: Dict[str, Path],
    costs: Dict[str, float],
) -> Tuple[pd.DataFrame, Dict[int, pd.DataFrame]]:
    with timer(costs, "clustering"):
        origins = config["rolling_origins"]
        selected_k = int(config["selected_k"])
        labels_by_origin: Dict[int, pd.DataFrame] = {}
        metrics_rows = []
        selected_prev_centers = None
        selected_prev_labels = None
        selected_history = defaultdict(list)
        feature_cache: Dict[int, pd.DataFrame] = {}

        for origin in origins:
            feats = clustering_features_for_origin(sales, calendar, prices, release_day, origin)
            feature_cache[origin] = feats
            clustering_feats = apply_clustering_feature_ablation(feats, config)
            x, scaler = transform_clustering_matrix(clustering_feats)
            feats.to_parquet(dirs["processed"] / f"clustering_features_origin_{origin}.parquet", index=False)

            for k in config["clustering_k_values"]:
                model = MiniBatchKMeans(n_clusters=int(k), random_state=config["random_seed"], batch_size=4096, n_init=5)
                raw_labels = model.fit_predict(x)
                sil = np.nan
                if len(x) > 5000:
                    sample_idx = np.random.default_rng(config["random_seed"]).choice(len(x), size=5000, replace=False)
                    sil = silhouette_score(x.iloc[sample_idx], raw_labels[sample_idx])
                    db = davies_bouldin_score(x.iloc[sample_idx], raw_labels[sample_idx])
                else:
                    sil = silhouette_score(x, raw_labels)
                    db = davies_bouldin_score(x, raw_labels)
                metrics_rows.append(
                    {
                        "origin": origin,
                        "k": k,
                        "inertia": model.inertia_,
                        "silhouette": sil,
                        "davies_bouldin": db,
                        "min_cluster_size": int(pd.Series(raw_labels).value_counts().min()),
                    }
                )

                if int(k) == selected_k:
                    if config.get("save_model_artifacts", False):
                        artifact_dir = dirs["models"] / f"origin_{origin}" / "cluster"
                        artifact_dir.mkdir(parents=True, exist_ok=True)
                        joblib.dump(model, artifact_dir / f"minibatch_kmeans_k{selected_k}.joblib")
                        joblib.dump(scaler, artifact_dir / "robust_scaler.joblib")
                        feature_schema = {
                            "origin": int(origin),
                            "selected_k": selected_k,
                            "feature_cols": [c for c in clustering_feats.columns if c != "id"],
                            "transformed_cols": list(x.columns),
                            "label_alignment": "cluster_label_raw_aligned is aligned across origins; single-origin app inference uses raw model labels.",
                        }
                        (artifact_dir / "clustering_feature_schema.json").write_text(
                            json.dumps(feature_schema, indent=2),
                            encoding="utf-8",
                        )
                    labels = raw_labels
                    centers = model.cluster_centers_
                    mapping = {}
                    if selected_prev_centers is not None:
                        labels, mapping = align_labels(selected_prev_centers, centers, labels)
                        ari = adjusted_rand_score(selected_prev_labels, labels)
                    else:
                        ari = np.nan
                    selected_prev_centers = centers
                    selected_prev_labels = labels
                    out = pd.DataFrame({"id": feats["id"], "cluster_label_raw_aligned": labels})
                    distances = model.transform(x)
                    out["centroid_distance"] = distances[np.arange(len(labels)), raw_labels]
                    out["origin"] = origin
                    out["label_mapping_from_raw"] = str(mapping)
                    out["ari_vs_previous_origin"] = ari
                    labels_by_origin[origin] = out
                    for sid, label in zip(out["id"], out["cluster_label_raw_aligned"]):
                        selected_history[sid].append(int(label))

        # Majority smoothing after aligned labels.
        for origin in origins:
            out = labels_by_origin[origin].copy()
            if config.get("enable_cluster_smoothing", True):
                smoothed = []
                for sid, raw in zip(out["id"], out["cluster_label_raw_aligned"]):
                    history = selected_history[sid]
                    window = history[max(0, origins.index(origin) - 2) : origins.index(origin) + 1]
                    smoothed.append(Counter(window).most_common(1)[0][0] if window else int(raw))
                out["cluster_label"] = smoothed
            else:
                out["cluster_label"] = out["cluster_label_raw_aligned"].astype(int)
            labels_by_origin[origin] = out
            out.to_csv(dirs["processed"] / f"cluster_labels_origin_{origin}.csv", index=False)

        metrics = pd.DataFrame(metrics_rows)
        metrics.to_csv(dirs["metrics"] / "clustering_quality_metrics.csv", index=False)

        profiles = []
        for origin, labels in labels_by_origin.items():
            feats = feature_cache[origin].merge(labels[["id", "cluster_label"]], on="id", how="left")
            prof = feats.groupby("cluster_label").agg(
                n_series=("id", "count"),
                mean_sales=("mean_sales", "mean"),
                zero_sales_ratio=("zero_sales_ratio", "mean"),
                adi=("adi", "mean"),
                cv2=("cv2", "mean"),
                avg_price=("avg_price", "mean"),
                event_lift=("event_lift", "mean"),
            )
            prof.insert(0, "origin", origin)
            profiles.append(prof.reset_index())
        pd.concat(profiles, ignore_index=True).to_csv(dirs["metrics"] / "cluster_profiles.csv", index=False)
    return metrics, labels_by_origin


def build_daily_price_frame(prices: pd.DataFrame, calendar: pd.DataFrame, meta: pd.DataFrame, days: Iterable[int]) -> pd.DataFrame:
    cal = calendar.loc[calendar["d"].isin([f"d_{d}" for d in days]), ["d", "wm_yr_wk"]].copy()
    cal["d_num"] = cal["d"].map(day_num)
    keys = meta[["id", "store_id", "item_id", "cat_id"]]
    base = keys.assign(_key=1).merge(cal.assign(_key=1), on="_key").drop(columns="_key")
    base = base.merge(prices, on=["store_id", "item_id", "wm_yr_wk"], how="left")
    cat_week_avg = prices.merge(keys[["store_id", "item_id", "cat_id"]], on=["store_id", "item_id"], how="inner")
    cat_week_avg = cat_week_avg.groupby(["store_id", "cat_id", "wm_yr_wk"])["sell_price"].mean().rename("cat_week_price")
    base = base.merge(cat_week_avg.reset_index(), on=["store_id", "cat_id", "wm_yr_wk"], how="left")
    base["relative_price"] = base["sell_price"] / (base["cat_week_price"] + 1e-9)
    return base[["id", "d_num", "sell_price", "relative_price"]]


def prefix_sum(arr: np.ndarray) -> np.ndarray:
    return np.concatenate([np.zeros((arr.shape[0], 1), dtype=np.float32), np.cumsum(arr, axis=1)], axis=1)


def window_mean(csum: np.ndarray, day: int, width: int) -> np.ndarray:
    end = day - 1
    start = max(1, day - width)
    count = max(end - start + 1, 1)
    return (csum[:, end] - csum[:, start - 1]) / count


def build_model_frame(
    sales_sample: pd.DataFrame,
    calendar: pd.DataFrame,
    prices: pd.DataFrame,
    release_day_sample: pd.Series,
    cluster_labels: pd.DataFrame,
    origin: int,
    start_day: int,
    end_day: int,
    include_target: bool,
) -> pd.DataFrame:
    dcols_all = day_cols(sales_sample)
    arr = sales_sample[dcols_all].to_numpy(dtype=np.float32)
    csum = prefix_sum(arr)
    rows = []
    days = list(range(start_day, end_day + 1))
    cal = calendar.loc[calendar["d"].isin([f"d_{d}" for d in days]), ["d", "wday", "month", "year", "event_name_1", "event_type_1", "snap_CA", "snap_TX", "snap_WI"]].copy()
    cal["d_num"] = cal["d"].map(day_num)
    cal["event_flag"] = cal["event_name_1"].notna().astype(np.int8)
    cal["event_type_flag"] = cal["event_type_1"].notna().astype(np.int8)
    cal_map = cal.set_index("d_num").to_dict("index")
    price_frame = build_daily_price_frame(prices, calendar, sales_sample[ID_COLS], days)
    price_map = price_frame.set_index(["id", "d_num"])[["sell_price", "relative_price"]].to_dict("index")
    cluster_map = cluster_labels.set_index("id")[["cluster_label", "centroid_distance"]].to_dict("index")

    ids = sales_sample["id"].to_numpy()
    states = sales_sample["state_id"].to_numpy()
    release = release_day_sample.to_numpy()
    meta = sales_sample[ID_COLS].reset_index(drop=True)
    for day in days:
        lag7 = arr[:, day - 7 - 1] if day > 7 else np.zeros(len(ids), dtype=np.float32)
        lag14 = arr[:, day - 14 - 1] if day > 14 else np.zeros(len(ids), dtype=np.float32)
        lag28 = arr[:, day - 28 - 1] if day > 28 else np.zeros(len(ids), dtype=np.float32)
        lag56 = arr[:, day - 56 - 1] if day > 56 else np.zeros(len(ids), dtype=np.float32)
        rmean7 = window_mean(csum, day, 7)
        rmean28 = window_mean(csum, day, 28)
        rmean56 = window_mean(csum, day, 56)
        info = cal_map[day]
        snap = np.where(states == "CA", info["snap_CA"], np.where(states == "TX", info["snap_TX"], info["snap_WI"]))
        target = arr[:, day - 1] if include_target and day <= arr.shape[1] else np.nan
        for idx, sid in enumerate(ids):
            price_info = price_map.get((sid, day), {"sell_price": np.nan, "relative_price": np.nan})
            cluster_info = cluster_map.get(sid, {"cluster_label": -1, "centroid_distance": np.nan})
            rel = release[idx]
            rows.append(
                {
                    "id": sid,
                    "d": day,
                    "item_id": meta.at[idx, "item_id"],
                    "dept_id": meta.at[idx, "dept_id"],
                    "cat_id": meta.at[idx, "cat_id"],
                    "store_id": meta.at[idx, "store_id"],
                    "state_id": meta.at[idx, "state_id"],
                    "wday": info["wday"],
                    "month": info["month"],
                    "year": info["year"],
                    "event_flag": info["event_flag"],
                    "event_type_flag": info["event_type_flag"],
                    "snap": snap[idx],
                    "is_available": int(not pd.isna(rel) and day >= rel),
                    "days_since_release": max(0, day - rel) if not pd.isna(rel) else 0,
                    "lag_7": lag7[idx],
                    "lag_14": lag14[idx],
                    "lag_28": lag28[idx],
                    "lag_56": lag56[idx],
                    "rolling_mean_7": rmean7[idx],
                    "rolling_mean_28": rmean28[idx],
                    "rolling_mean_56": rmean56[idx],
                    "sell_price": price_info["sell_price"],
                    "relative_price": price_info["relative_price"],
                    "cluster_label": int(cluster_info["cluster_label"]),
                    "centroid_distance": cluster_info["centroid_distance"],
                    "y": target[idx],
                }
            )
    frame = pd.DataFrame(rows)
    frame["sell_price"] = frame["sell_price"].fillna(0.0)
    frame["relative_price"] = frame["relative_price"].fillna(0.0)
    frame["centroid_distance"] = frame["centroid_distance"].fillna(frame["centroid_distance"].median())
    for col in CATEGORICAL_COLS:
        frame[col] = frame[col].astype("category")
    frame["cluster_label"] = frame["cluster_label"].astype("category")
    return frame


def build_daily_price_maps(prices: pd.DataFrame, calendar: pd.DataFrame, meta: pd.DataFrame, days: Iterable[int]) -> Dict[Tuple[str, int], Dict[str, float]]:
    price_frame = build_daily_price_frame(prices, calendar, meta, days)
    return price_frame.set_index(["id", "d_num"])[["sell_price", "relative_price"]].to_dict("index")


def build_recursive_day_frame(
    history: np.ndarray,
    actual_arr: np.ndarray,
    sales_sample: pd.DataFrame,
    calendar: pd.DataFrame,
    release_day_sample: pd.Series,
    cluster_labels: pd.DataFrame,
    price_map: Dict[Tuple[str, int], Dict[str, float]],
    day: int,
) -> pd.DataFrame:
    ids = sales_sample["id"].to_numpy()
    states = sales_sample["state_id"].to_numpy()
    release = release_day_sample.to_numpy()
    meta = sales_sample[ID_COLS].reset_index(drop=True)
    cal_row = calendar.loc[calendar["d"] == f"d_{day}"].iloc[0]
    event_flag = int(pd.notna(cal_row["event_name_1"]))
    event_type_flag = int(pd.notna(cal_row["event_type_1"]))
    snap = np.where(states == "CA", cal_row["snap_CA"], np.where(states == "TX", cal_row["snap_TX"], cal_row["snap_WI"]))
    cluster_map = cluster_labels.set_index("id")[["cluster_label", "centroid_distance"]].to_dict("index")

    def lag_values(lag: int) -> np.ndarray:
        source_day = day - lag
        if source_day < 1:
            return np.zeros(len(ids), dtype=np.float32)
        vals = history[:, source_day - 1]
        return np.nan_to_num(vals, nan=0.0)

    def rolling_mean(width: int) -> np.ndarray:
        end = day - 1
        start = max(1, day - width)
        vals = history[:, start - 1 : end]
        vals = np.nan_to_num(vals, nan=0.0)
        return vals.mean(axis=1) if vals.shape[1] else np.zeros(len(ids), dtype=np.float32)

    lag7, lag14, lag28, lag56 = lag_values(7), lag_values(14), lag_values(28), lag_values(56)
    rmean7, rmean28, rmean56 = rolling_mean(7), rolling_mean(28), rolling_mean(56)
    rows = []
    for idx, sid in enumerate(ids):
        price_info = price_map.get((sid, day), {"sell_price": np.nan, "relative_price": np.nan})
        cluster_info = cluster_map.get(sid, {"cluster_label": -1, "centroid_distance": np.nan})
        rel = release[idx]
        rows.append(
            {
                "id": sid,
                "d": day,
                "item_id": meta.at[idx, "item_id"],
                "dept_id": meta.at[idx, "dept_id"],
                "cat_id": meta.at[idx, "cat_id"],
                "store_id": meta.at[idx, "store_id"],
                "state_id": meta.at[idx, "state_id"],
                "wday": cal_row["wday"],
                "month": cal_row["month"],
                "year": cal_row["year"],
                "event_flag": event_flag,
                "event_type_flag": event_type_flag,
                "snap": snap[idx],
                "is_available": int(not pd.isna(rel) and day >= rel),
                "days_since_release": max(0, day - rel) if not pd.isna(rel) else 0,
                "lag_7": lag7[idx],
                "lag_14": lag14[idx],
                "lag_28": lag28[idx],
                "lag_56": lag56[idx],
                "rolling_mean_7": rmean7[idx],
                "rolling_mean_28": rmean28[idx],
                "rolling_mean_56": rmean56[idx],
                "sell_price": price_info["sell_price"],
                "relative_price": price_info["relative_price"],
                "cluster_label": int(cluster_info["cluster_label"]),
                "centroid_distance": cluster_info["centroid_distance"],
                "y": actual_arr[idx, day - 1],
            }
        )
    frame = pd.DataFrame(rows)
    frame["sell_price"] = frame["sell_price"].fillna(0.0)
    frame["relative_price"] = frame["relative_price"].fillna(0.0)
    frame["centroid_distance"] = frame["centroid_distance"].fillna(frame["centroid_distance"].median())
    for col in CATEGORICAL_COLS:
        frame[col] = frame[col].astype("category")
    frame["cluster_label"] = frame["cluster_label"].astype("category")
    return frame


def recursive_forecast(
    model,
    feature_cols: List[str],
    sales_sample: pd.DataFrame,
    calendar: pd.DataFrame,
    prices: pd.DataFrame,
    release_day_sample: pd.Series,
    cluster_labels: pd.DataFrame,
    origin: int,
    horizon: int,
    model_name: str,
    model_by_cluster: Dict[int, object] | None = None,
) -> pd.DataFrame:
    all_dcols = day_cols(sales_sample)
    actual_arr = sales_sample[all_dcols].to_numpy(dtype=np.float32)
    history = actual_arr.copy()
    if origin < history.shape[1]:
        history[:, origin:] = np.nan
    days = list(range(origin + 1, origin + horizon + 1))
    price_map = build_daily_price_maps(prices, calendar, sales_sample[ID_COLS], days)
    preds = []
    for day in days:
        frame = build_recursive_day_frame(history, actual_arr, sales_sample, calendar, release_day_sample, cluster_labels, price_map, day)
        if model_by_cluster is None:
            yhat = np.maximum(0, model.predict(frame[feature_cols]))
        else:
            yhat = np.zeros(len(frame), dtype=np.float64)
            for cluster, cluster_model in model_by_cluster.items():
                mask = frame["cluster_label"].astype(int).to_numpy() == int(cluster)
                if mask.any():
                    yhat[mask] = np.maximum(0, cluster_model.predict(frame.loc[mask, feature_cols]))
        history[:, day - 1] = yhat
        pred = frame[["id", "d", "y", "cluster_label", "cat_id", "store_id"]].copy()
        pred["origin"] = origin
        pred["model"] = model_name
        pred["split"] = "test"
        pred["yhat"] = yhat
        preds.append(pred)
    return pd.concat(preds, ignore_index=True)


def rmsse_denominators(sales_sample: pd.DataFrame, release_day_sample: pd.Series, origin: int) -> pd.Series:
    arr = sales_sample[[f"d_{i}" for i in range(1, origin + 1)]].to_numpy(dtype=np.float32)
    denoms = []
    for i in range(arr.shape[0]):
        rel = release_day_sample.iloc[i]
        start = int(rel) - 1 if not pd.isna(rel) else 0
        active = arr[i, start:]
        diffs = np.diff(active)
        denom = float(np.mean(diffs**2)) if len(diffs) else 1.0
        denoms.append(max(denom, 1e-6))
    return pd.Series(denoms, index=sales_sample["id"])


def evaluate_predictions(pred: pd.DataFrame, denom: pd.Series) -> Dict[str, float]:
    pred = pred.copy()
    pred["abs_err"] = (pred["y"] - pred["yhat"]).abs()
    pred["sq_err_scaled"] = ((pred["y"] - pred["yhat"]) ** 2) / pred["id"].map(denom)
    return {
        "mae": float(pred["abs_err"].mean()),
        "wape": float(pred["abs_err"].sum() / (pred["y"].abs().sum() + 1e-9)),
        "rmsse_item_store": float(math.sqrt(pred["sq_err_scaled"].mean())),
        "bias": float((pred["yhat"] - pred["y"]).sum() / (pred["y"].sum() + 1e-9)),
    }


def hierarchy_group_definitions() -> List[Tuple[str, List[str]]]:
    return [
        ("total", []),
        ("state", ["state_id"]),
        ("store", ["store_id"]),
        ("category", ["cat_id"]),
        ("department", ["dept_id"]),
        ("state_category", ["state_id", "cat_id"]),
        ("state_department", ["state_id", "dept_id"]),
        ("store_category", ["store_id", "cat_id"]),
        ("store_department", ["store_id", "dept_id"]),
        ("item", ["item_id"]),
        ("state_item", ["state_id", "item_id"]),
        ("item_store", ["id"]),
    ]


def daily_item_revenue(
    sales_sample: pd.DataFrame,
    calendar: pd.DataFrame,
    prices: pd.DataFrame,
    days: Iterable[int],
) -> pd.DataFrame:
    meta = sales_sample[ID_COLS]
    sales_long = sales_sample[["id"] + [f"d_{d}" for d in days]].melt(id_vars="id", var_name="d", value_name="sales")
    sales_long["d_num"] = sales_long["d"].map(day_num)
    price_frame = build_daily_price_frame(prices, calendar, meta, days)[["id", "d_num", "sell_price"]]
    out = sales_long.merge(price_frame, on=["id", "d_num"], how="left")
    out["revenue"] = out["sales"] * out["sell_price"].fillna(0.0)
    return out[["id", "d_num", "revenue"]]


def aggregate_matrix(matrix: pd.DataFrame, meta: pd.DataFrame, group_cols: List[str]) -> pd.DataFrame:
    meta_cols = list(dict.fromkeys(["id"] + group_cols))
    data = meta[meta_cols].merge(matrix, left_on="id", right_index=True, how="inner")
    value_cols = [c for c in matrix.columns]
    if not group_cols:
        agg = pd.DataFrame([data[value_cols].sum(axis=0).to_dict()], index=["total"])
        return agg
    agg = data.groupby(group_cols, observed=True)[value_cols].sum()
    agg.index = agg.index.map(lambda x: "|".join(map(str, x)) if isinstance(x, tuple) else str(x))
    return agg


def rmsse_scale_for_agg(train_agg: pd.DataFrame) -> pd.Series:
    scales = {}
    arr = train_agg.to_numpy(dtype=np.float64)
    for idx, key in enumerate(train_agg.index):
        series = arr[idx]
        nz = np.flatnonzero(series > 0)
        start = int(nz[0]) if len(nz) else 0
        active = series[start:]
        diffs = np.diff(active)
        scale = float(np.mean(diffs**2)) if len(diffs) else 1.0
        scales[key] = max(scale, 1e-6)
    return pd.Series(scales)


def compute_sampled_wrmsse(
    forecast_df: pd.DataFrame,
    sales_sample: pd.DataFrame,
    calendar: pd.DataFrame,
    prices: pd.DataFrame,
    dirs: Dict[str, Path],
) -> pd.DataFrame:
    meta = sales_sample[ID_COLS].copy()
    rows = []
    for origin in sorted(forecast_df["origin"].unique()):
        train_days = list(range(1, int(origin) + 1))
        test_days = sorted(forecast_df.loc[forecast_df["origin"] == origin, "d"].unique())
        train_matrix = sales_sample.set_index("id")[[f"d_{d}" for d in train_days]]
        train_matrix.columns = train_days
        actual_matrix = sales_sample.set_index("id")[[f"d_{d}" for d in test_days]]
        actual_matrix.columns = test_days
        revenue = daily_item_revenue(sales_sample, calendar, prices, range(max(1, int(origin) - 27), int(origin) + 1))
        item_revenue = revenue.groupby("id")["revenue"].sum().rename("weight_value")

        for level, group_cols in hierarchy_group_definitions():
            train_agg = aggregate_matrix(train_matrix, meta, group_cols)
            actual_agg = aggregate_matrix(actual_matrix, meta, group_cols)
            scale = rmsse_scale_for_agg(train_agg)
            if not group_cols:
                weights = pd.Series({"total": float(item_revenue.sum())})
            else:
                meta_cols = list(dict.fromkeys(["id"] + group_cols))
                weight_data = meta[meta_cols].merge(item_revenue.reset_index(), on="id", how="left").fillna({"weight_value": 0.0})
                weights = weight_data.groupby(group_cols, observed=True)["weight_value"].sum()
                weights.index = weights.index.map(lambda x: "|".join(map(str, x)) if isinstance(x, tuple) else str(x))
            for model in forecast_df["model"].unique():
                model_pred = forecast_df.loc[(forecast_df["origin"] == origin) & (forecast_df["model"] == model)]
                pred_matrix = model_pred.pivot(index="id", columns="d", values="yhat").reindex(index=actual_matrix.index, columns=test_days).fillna(0.0)
                pred_agg = aggregate_matrix(pred_matrix, meta, group_cols).reindex(index=actual_agg.index).fillna(0.0)
                sq_scaled = ((actual_agg - pred_agg) ** 2).mean(axis=1) / scale.reindex(actual_agg.index)
                rmsse = np.sqrt(sq_scaled)
                level_weights = weights.reindex(actual_agg.index).fillna(0.0)
                if level_weights.sum() <= 0:
                    level_weights = pd.Series(1.0, index=actual_agg.index)
                wrmsse_level = float((rmsse * level_weights / level_weights.sum()).sum())
                rows.append({"origin": origin, "model": model, "level": level, "sampled_wrmsse": wrmsse_level, "n_series_level": len(rmsse)})
    out = pd.DataFrame(rows)
    out.to_csv(dirs["metrics"] / "sampled_wrmsse_by_level.csv", index=False)
    overall = out.groupby(["origin", "model"])["sampled_wrmsse"].mean().reset_index(name="sampled_wrmsse_12level")
    overall.to_csv(dirs["metrics"] / "sampled_wrmsse_overall.csv", index=False)
    return out


def train_lgbm(
    train_df: pd.DataFrame,
    val_df: pd.DataFrame,
    feature_cols: List[str],
    categorical_cols: List[str],
    config: dict,
    sample_weight=None,
) -> lgb.Booster:
    params = dict(config["lightgbm_params"])
    lgb_train = lgb.Dataset(
        train_df[feature_cols],
        label=train_df["y"],
        categorical_feature=[c for c in categorical_cols if c in feature_cols],
        weight=sample_weight,
        free_raw_data=False,
    )
    lgb_val = lgb.Dataset(
        val_df[feature_cols],
        label=val_df["y"],
        categorical_feature=[c for c in categorical_cols if c in feature_cols],
        reference=lgb_train,
        free_raw_data=False,
    )
    return lgb.train(
        params,
        lgb_train,
        num_boost_round=config["num_boost_round"],
        valid_sets=[lgb_val],
        callbacks=[lgb.early_stopping(config["early_stopping_rounds"], verbose=False)],
    )


def feature_importance_rows(
    model: lgb.Booster,
    feature_cols: List[str],
    origin: int,
    model_name: str,
    cluster_label: int | str | None = None,
) -> List[dict]:
    gains = model.feature_importance(importance_type="gain")
    splits = model.feature_importance(importance_type="split")
    rows = []
    for feature, gain, split in zip(feature_cols, gains, splits):
        rows.append(
            {
                "origin": origin,
                "model": model_name,
                "cluster_label": "global" if cluster_label is None else cluster_label,
                "feature": feature,
                "importance_gain": float(gain),
                "importance_split": float(split),
            }
        )
    return rows


def save_lgbm_artifact(
    model: lgb.Booster,
    dirs: Dict[str, Path],
    origin: int,
    model_name: str,
    feature_cols: List[str],
    categorical_cols: List[str],
    cluster_label: int | str | None = None,
) -> None:
    artifact_dir = dirs["models"] / f"origin_{origin}"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    cluster_suffix = "" if cluster_label is None else f"_cluster_{cluster_label}"
    stem = f"{model_name}{cluster_suffix}"
    model.save_model(str(artifact_dir / f"{stem}.txt"))
    schema = {
        "origin": int(origin),
        "model": model_name,
        "cluster_label": None if cluster_label is None else int(cluster_label),
        "feature_cols": feature_cols,
        "categorical_cols": [c for c in categorical_cols if c in feature_cols],
        "best_iteration": model.best_iteration,
    }
    (artifact_dir / f"{stem}_schema.json").write_text(json.dumps(schema, indent=2), encoding="utf-8")


FORECASTING_FEATURE_GROUPS = {
    "price": ["sell_price", "relative_price"],
    "calendar": ["wday", "month", "year", "event_flag", "event_type_flag", "snap"],
    "hierarchy": ["item_id", "dept_id", "cat_id", "store_id", "state_id"],
}


def apply_forecasting_feature_ablation(feature_cols: List[str], config: dict) -> List[str]:
    exclude = set(config.get("forecasting_exclude_features", []))
    for group in config.get("forecasting_exclude_feature_groups", []):
        exclude.update(FORECASTING_FEATURE_GROUPS.get(group, []))
    return [col for col in feature_cols if col not in exclude]


def run_models(
    sales: pd.DataFrame,
    calendar: pd.DataFrame,
    prices: pd.DataFrame,
    release_day: pd.Series,
    summary: pd.DataFrame,
    labels_by_origin: Dict[int, pd.DataFrame],
    config: dict,
    dirs: Dict[str, Path],
    costs: Dict[str, float],
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    with timer(costs, "modeling_and_evaluation"):
        sample_ids = sample_series(summary, int(config["model_sample_n_series"]), int(config["random_seed"]))
        sales_sample = sales.loc[sales["id"].isin(sample_ids)].reset_index(drop=True)
        release_sample = release_day.loc[sales["id"].isin(sample_ids)].reset_index(drop=True)
        pd.DataFrame({"id": sample_ids}).to_csv(dirs["processed"] / "model_sample_ids.csv", index=False)

        base_features = [
            "item_id",
            "dept_id",
            "cat_id",
            "store_id",
            "state_id",
            "wday",
            "month",
            "year",
            "event_flag",
            "event_type_flag",
            "snap",
            "is_available",
            "days_since_release",
            "lag_7",
            "lag_14",
            "lag_28",
            "lag_56",
            "rolling_mean_7",
            "rolling_mean_28",
            "rolling_mean_56",
            "sell_price",
            "relative_price",
        ]
        model_specs = {
            "A0_global_baseline": apply_forecasting_feature_ablation(base_features, config),
            "B1_cluster_label": apply_forecasting_feature_ablation(base_features + ["cluster_label"], config),
            "B2_cluster_distance": apply_forecasting_feature_ablation(base_features + ["cluster_label", "centroid_distance"], config),
            "D_cluster_weighted": apply_forecasting_feature_ablation(base_features + ["cluster_label"], config),
        }
        cluster_specific_model = "C_cluster_specific"
        models_to_run = config.get("models_to_run", list(model_specs) + [cluster_specific_model])
        model_specs = {name: cols for name, cols in model_specs.items() if name in models_to_run}
        run_cluster_specific = cluster_specific_model in models_to_run
        categorical = [col for col in CATEGORICAL_COLS + ["cluster_label"] if col not in set(config.get("forecasting_exclude_features", []))]
        for group in config.get("forecasting_exclude_feature_groups", []):
            categorical = [col for col in categorical if col not in FORECASTING_FEATURE_GROUPS.get(group, [])]
        metrics_rows = []
        overfit_rows = []
        cluster_specific_status_rows = []
        feature_importance_all_rows = []
        forecasts = []
        train_lookback = int(config["train_lookback_days"])
        h = int(config["forecast_horizon"])
        inner = int(config["inner_validation_days"])
        save_model_artifacts = bool(config.get("save_model_artifacts", False))

        for origin in config["rolling_origins"]:
            cluster_labels = labels_by_origin[origin]
            train_start = max(57, origin - train_lookback + 1)
            train_end = origin - inner
            val_start = train_end + 1
            val_end = origin
            train_df = build_model_frame(sales_sample, calendar, prices, release_sample, cluster_labels, origin, train_start, train_end, True)
            val_df = build_model_frame(sales_sample, calendar, prices, release_sample, cluster_labels, origin, val_start, val_end, True)
            denom = rmsse_denominators(sales_sample, release_sample, origin)

            # Compute cluster weights from inner validation using B1 unweighted
            # only when the weighted ablation is requested.
            weight_by_cluster = None
            if "D_cluster_weighted" in model_specs:
                tmp_features = apply_forecasting_feature_ablation(base_features + ["cluster_label"], config)
                tmp_model = train_lgbm(train_df, val_df, tmp_features, categorical, config)
                val_tmp = val_df[["id", "d", "y", "cluster_label"]].copy()
                val_tmp["yhat"] = np.maximum(0, tmp_model.predict(val_df[tmp_features]))
                val_tmp["abs_err"] = (val_tmp["y"] - val_tmp["yhat"]).abs()
                err_by_cluster = val_tmp.groupby("cluster_label", observed=True)["abs_err"].mean()
                mean_err = float(err_by_cluster.mean()) if len(err_by_cluster) else 1.0
                lo, hi = config["cluster_weight_clip"]
                weight_by_cluster = (err_by_cluster / (mean_err + 1e-9)).clip(lo, hi).to_dict()
            fallback_model = None

            for model_name, feature_cols in model_specs.items():
                sample_weight = None
                if model_name == "D_cluster_weighted":
                    sample_weight = train_df["cluster_label"].map(weight_by_cluster).astype(float).to_numpy()
                model = train_lgbm(train_df, val_df, feature_cols, categorical, config, sample_weight=sample_weight)
                feature_importance_all_rows.extend(feature_importance_rows(model, feature_cols, origin, model_name))
                if save_model_artifacts:
                    save_lgbm_artifact(model, dirs, origin, model_name, feature_cols, categorical)
                if model_name == "A0_global_baseline":
                    fallback_model = model

                for split_name, df in [("train", train_df), ("inner_validation", val_df)]:
                    pred = df[["id", "d", "y", "cluster_label", "cat_id", "store_id"]].copy()
                    pred["origin"] = origin
                    pred["model"] = model_name
                    pred["split"] = split_name
                    pred["yhat"] = np.maximum(0, model.predict(df[feature_cols]))
                    eval_metrics = evaluate_predictions(pred, denom)
                    row = {"origin": origin, "model": model_name, "split": split_name}
                    row.update(eval_metrics)
                    overfit_rows.append(row)
                test_pred = recursive_forecast(
                    model,
                    feature_cols,
                    sales_sample,
                    calendar,
                    prices,
                    release_sample,
                    cluster_labels,
                    origin,
                    h,
                    model_name,
                )
                eval_metrics = evaluate_predictions(test_pred, denom)
                row = {"origin": origin, "model": model_name, "split": "test"}
                row.update(eval_metrics)
                metrics_rows.append(row)
                overfit_rows.append(row)
                forecasts.append(test_pred)

            if fallback_model is None:
                fallback_features = apply_forecasting_feature_ablation(base_features, config)
                fallback_model = train_lgbm(train_df, val_df, fallback_features, categorical, config)

            if not run_cluster_specific:
                continue

            # Model C in the proposal: train one LightGBM per cluster. This is a
            # comparison model, not the preferred deployment model, so small
            # clusters fall back to the global baseline and are recorded.
            cluster_feature_cols = apply_forecasting_feature_ablation(base_features, config)
            cluster_preds_by_split = {"train": [], "inner_validation": [], "test": []}
            cluster_model_map = {}
            min_train_rows = int(config.get("cluster_specific_min_train_rows", 1000))
            min_val_rows = int(config.get("cluster_specific_min_validation_rows", 100))
            for cluster in sorted(train_df["cluster_label"].dropna().unique()):
                cluster_train = train_df.loc[train_df["cluster_label"] == cluster]
                cluster_val = val_df.loc[val_df["cluster_label"] == cluster]
                train_rows = len(cluster_train)
                val_rows = len(cluster_val)
                use_fallback = train_rows < min_train_rows or val_rows < min_val_rows
                cluster_model = fallback_model
                status = "fallback_global_baseline" if use_fallback else "trained_cluster_model"
                if not use_fallback:
                    cluster_model = train_lgbm(cluster_train, cluster_val, cluster_feature_cols, categorical, config)
                if save_model_artifacts:
                    save_lgbm_artifact(
                        cluster_model,
                        dirs,
                        origin,
                        cluster_specific_model,
                        cluster_feature_cols,
                        categorical,
                        int(cluster),
                    )
                feature_importance_all_rows.extend(
                    feature_importance_rows(cluster_model, cluster_feature_cols, origin, cluster_specific_model, int(cluster))
                )
                cluster_model_map[int(cluster)] = cluster_model
                cluster_specific_status_rows.append(
                    {
                        "origin": origin,
                        "cluster_label": cluster,
                        "status": status,
                        "train_rows": train_rows,
                        "inner_validation_rows": val_rows,
                        "min_train_rows": min_train_rows,
                        "min_validation_rows": min_val_rows,
                    }
                )
                for split_name, df in [("train", train_df), ("inner_validation", val_df)]:
                    cluster_df = df.loc[df["cluster_label"] == cluster]
                    if cluster_df.empty:
                        continue
                    pred = cluster_df[["id", "d", "y", "cluster_label", "cat_id", "store_id"]].copy()
                    pred["origin"] = origin
                    pred["model"] = cluster_specific_model
                    pred["split"] = split_name
                    pred["yhat"] = np.maximum(0, cluster_model.predict(cluster_df[cluster_feature_cols]))
                    cluster_preds_by_split[split_name].append(pred)

            for split_name, pieces in cluster_preds_by_split.items():
                if not pieces:
                    continue
                pred = pd.concat(pieces, ignore_index=True)
                eval_metrics = evaluate_predictions(pred, denom)
                row = {"origin": origin, "model": cluster_specific_model, "split": split_name}
                row.update(eval_metrics)
                if split_name == "test":
                    metrics_rows.append(row)
                    forecasts.append(pred)
                overfit_rows.append(row)
            test_pred = recursive_forecast(
                None,
                cluster_feature_cols,
                sales_sample,
                calendar,
                prices,
                release_sample,
                cluster_labels,
                origin,
                h,
                cluster_specific_model,
                model_by_cluster=cluster_model_map,
            )
            eval_metrics = evaluate_predictions(test_pred, denom)
            row = {"origin": origin, "model": cluster_specific_model, "split": "test"}
            row.update(eval_metrics)
            metrics_rows.append(row)
            overfit_rows.append(row)
            forecasts.append(test_pred)

        metrics = pd.DataFrame(metrics_rows)
        overfit = pd.DataFrame(overfit_rows)
        forecast_df = pd.concat(forecasts, ignore_index=True)
        metrics.to_csv(dirs["metrics"] / "model_test_metrics.csv", index=False)
        overfit.to_csv(dirs["metrics"] / "model_train_val_test_metrics.csv", index=False)
        pd.DataFrame(cluster_specific_status_rows).to_csv(dirs["metrics"] / "cluster_specific_model_status.csv", index=False)
        pd.DataFrame(feature_importance_all_rows).to_csv(dirs["metrics"] / "feature_importance_by_origin.csv", index=False)
        forecast_df.to_parquet(dirs["metrics"] / "test_forecasts.parquet", index=False)
        compute_sampled_wrmsse(forecast_df, sales_sample, calendar, prices, dirs)

        cluster_metrics = []
        for (origin, model, cluster), grp in forecast_df.groupby(["origin", "model", "cluster_label"], observed=True):
            denom_sub = denom.loc[grp["id"].unique()]
            cluster_metrics.append({"origin": origin, "model": model, "cluster_label": cluster, **evaluate_predictions(grp, denom)})
        pd.DataFrame(cluster_metrics).to_csv(dirs["metrics"] / "model_metrics_by_cluster.csv", index=False)
    return metrics, overfit, forecast_df


def run_stability(forecast_df: pd.DataFrame, summary: pd.DataFrame, config: dict, dirs: Dict[str, Path], costs: Dict[str, float]) -> pd.DataFrame:
    with timer(costs, "stability"):
        rows = []
        origins = sorted(forecast_df["origin"].unique())
        scale_floor = float(config.get("stability_scale_floor", 0.1))
        scale = summary.set_index("id")["mean_sales"].replace(0, np.nan).fillna(summary["mean_sales"].median())
        scale = scale.clip(lower=scale_floor)
        for model in forecast_df["model"].unique():
            model_df = forecast_df.loc[forecast_df["model"] == model]
            for prev, cur in zip(origins[:-1], origins[1:]):
                left = model_df.loc[model_df["origin"] == prev, ["id", "d", "yhat", "cluster_label"]]
                right = model_df.loc[model_df["origin"] == cur, ["id", "d", "yhat"]]
                merged = left.merge(right, on=["id", "d"], suffixes=("_prev", "_cur"))
                if merged.empty:
                    continue
                merged["abs_change"] = (merged["yhat_cur"] - merged["yhat_prev"]).abs()
                merged["scale"] = merged["id"].map(scale).fillna(scale.median()) + 1e-9
                merged["scale_change"] = merged["abs_change"] / merged["scale"]
                rank_corr = spearmanr(merged["yhat_prev"], merged["yhat_cur"]).correlation
                row = {
                    "model": model,
                    "origin_prev": prev,
                    "origin_cur": cur,
                    "n_overlap_rows": len(merged),
                    "scale_floor": scale_floor,
                    "weighted_absolute_change": float(merged["abs_change"].mean()),
                    "scale_aware_stability_loss": float(merged["scale_change"].mean()),
                    "rank_stability_spearman": float(rank_corr) if not np.isnan(rank_corr) else np.nan,
                }
                for tau in config["jump_thresholds"]:
                    row[f"jump_rate_tau_{tau}"] = float((merged["scale_change"] > tau).mean())
                rows.append(row)
        out = pd.DataFrame(rows)
        out.to_csv(dirs["metrics"] / "forecast_stability_metrics.csv", index=False)
        return out


def run_statistical_summaries(metrics: pd.DataFrame, dirs: Dict[str, Path]) -> pd.DataFrame:
    rows = []
    baseline = "A0_global_baseline"
    for metric in ["rmsse_item_store", "mae", "wape", "bias"]:
        pivot = metrics.pivot_table(index="origin", columns="model", values=metric)
        for model in pivot.columns:
            if model == baseline or baseline not in pivot.columns:
                continue
            diff = pivot[model] - pivot[baseline]
            rows.append(
                {
                    "metric": metric,
                    "model": model,
                    "mean_diff_vs_baseline": float(diff.mean()),
                    "median_diff_vs_baseline": float(diff.median()),
                    "p10_diff": float(diff.quantile(0.1)),
                    "p90_diff": float(diff.quantile(0.9)),
                    "n_origins": int(diff.notna().sum()),
                }
            )
    out = pd.DataFrame(rows)
    out.to_csv(dirs["metrics"] / "effect_size_vs_baseline.csv", index=False)
    return out


def write_report(
    validation: pd.DataFrame,
    summary: pd.DataFrame,
    clustering_metrics: pd.DataFrame,
    model_metrics: pd.DataFrame,
    overfit: pd.DataFrame,
    stability: pd.DataFrame,
    effect_size: pd.DataFrame,
    costs: Dict[str, float],
    config: dict,
    dirs: Dict[str, Path],
) -> None:
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

    failed = validation.loc[~validation["status"].astype(bool)]
    demand_counts = summary["demand_class"].value_counts().to_dict()
    best_rows = (
        model_metrics.groupby("model")[["rmsse_item_store", "mae", "wape", "bias"]]
        .mean()
        .sort_values("rmsse_item_store")
        .reset_index()
    )
    wrmsse_path = dirs["metrics"] / "sampled_wrmsse_overall.csv"
    sampled_wrmsse = pd.read_csv(wrmsse_path) if wrmsse_path.exists() else pd.DataFrame()
    overfit_pivot = overfit.pivot_table(index=["origin", "model"], columns="split", values="rmsse_item_store").reset_index()
    if {"train", "inner_validation", "test"}.issubset(overfit_pivot.columns):
        overfit_pivot["test_train_gap"] = overfit_pivot["test"] - overfit_pivot["train"]
    overfit_pivot.to_csv(dirs["metrics"] / "overfitting_gap_summary.csv", index=False)

    lines = []
    lines.append("# M5 Cluster-aware Forecasting Research Run Report")
    lines.append("")
    lines.append("## Scope")
    lines.append(
        f"This run executes the checklist pipeline with a stratified modeling sample of {config['model_sample_n_series']} series, "
        f"lookback={config['train_lookback_days']} days, origins={config['rolling_origins']}, horizon={config['forecast_horizon']}."
    )
    lines.append("Full-data EDA and clustering features are computed for all 30,490 series; model training/evaluation uses the configured sample for feasibility.")
    lines.append("")
    lines.append("## Data Validation")
    lines.append(f"- Checks passed: {int(validation['status'].astype(bool).sum())}/{len(validation)}")
    if not failed.empty:
        lines.append("- Failed checks:")
        for _, row in failed.iterrows():
            lines.append(f"  - {row['check']}: {row['details']}")
    lines.append("")
    lines.append("## EDA Highlights")
    lines.append(f"- Demand class counts: {demand_counts}")
    lines.append(f"- Median zero-sales ratio: {summary['zero_sales_ratio'].median():.4f}")
    lines.append(f"- Median ADI: {summary['adi'].median():.4f}")
    lines.append(f"- Median CV2: {summary['cv2'].median():.4f}")
    lines.append("")
    lines.append("## Clustering")
    lines.append("- Clustering quality metrics are saved to `outputs/metrics/clustering_quality_metrics.csv`.")
    selected = clustering_metrics.loc[clustering_metrics["k"] == config["selected_k"]]
    if not selected.empty:
        lines.append(
            f"- Selected K={config['selected_k']}; mean silhouette={selected['silhouette'].mean():.4f}, "
            f"mean Davies-Bouldin={selected['davies_bouldin'].mean():.4f}."
        )
    lines.append("- Cluster labels are aligned across windows before smoothing.")
    lines.append("")
    lines.append("## Model Accuracy")
    lines.append(md_table(best_rows))
    if not sampled_wrmsse.empty:
        lines.append("")
        lines.append("## Sampled Rolling WRMSSE")
        wr_summary = sampled_wrmsse.groupby("model")["sampled_wrmsse_12level"].mean().sort_values().reset_index()
        lines.append(md_table(wr_summary))
    lines.append("")
    lines.append("## Stability")
    if not stability.empty:
        lines.append(md_table(stability.groupby("model").mean(numeric_only=True).reset_index()))
    else:
        lines.append("No overlapping forecast rows were available for stability calculation.")
    lines.append("")
    lines.append("## Overfitting Checks")
    if "test_train_gap" in overfit_pivot.columns:
        gap_summary = overfit_pivot.groupby("model")["test_train_gap"].agg(["mean", "median", "max"]).reset_index()
        lines.append(md_table(gap_summary))
    lines.append("- Detailed train/inner-validation/test metrics are saved to `outputs/metrics/model_train_val_test_metrics.csv`.")
    lines.append("")
    lines.append("## Effect Size vs Baseline")
    lines.append(md_table(effect_size) if not effect_size.empty else "No effect-size rows generated.")
    lines.append("")
    lines.append("## Runtime Cost")
    lines.append(md_table(pd.DataFrame([{"stage": k, "seconds": v} for k, v in costs.items()])))
    lines.append("")
    lines.append("## Important Caveat")
    lines.append(
        "This run is an executable research pass. Exact official M5 WRMSSE over all 12 hierarchy levels for all series is not computed in this sampled modeling run; "
        "item-store RMSSE/MAE/WAPE/bias and cluster/hierarchy summaries are reported. For final publication, rerun with full-series forecasting and official/rolling WRMSSE aggregation."
    )
    (dirs["reports"] / "research_run_report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/research_config.json")
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    set_global_seed(int(config["random_seed"]))
    dirs = ensure_dirs(config)
    costs: Dict[str, float] = {}
    data_dir = Path(config["data_dir"])

    with timer(costs, "load_raw"):
        sales, calendar, prices, sample_submission = load_raw(data_dir)
        release_day = build_release_days(sales, calendar, prices)
        release_day.to_frame().to_csv(dirs["processed"] / "release_days.csv", index=False)

    validation = validate_raw(data_dir, sales, calendar, prices, sample_submission, dirs)
    summary = run_eda(sales, calendar, prices, release_day, dirs, costs)
    clustering_metrics, labels_by_origin = run_clustering(sales, calendar, prices, release_day, config, dirs, costs)
    model_metrics, overfit, forecasts = run_models(sales, calendar, prices, release_day, summary, labels_by_origin, config, dirs, costs)
    stability = run_stability(forecasts, summary, config, dirs, costs)
    effect_size = run_statistical_summaries(model_metrics, dirs)
    pd.DataFrame([{"stage": k, "seconds": v} for k, v in costs.items()]).to_csv(dirs["metrics"] / "runtime_costs.csv", index=False)
    write_report(validation, summary, clustering_metrics, model_metrics, overfit, stability, effect_size, costs, config, dirs)


if __name__ == "__main__":
    main()
