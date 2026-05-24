from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats


BASE = Path("outputs_full_k3_seed42_tweedie_a0_b1_c")
OUT_DIR = BASE / "metrics"


def hac_variance(x: np.ndarray, max_lag: int) -> float:
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n <= 1:
        return np.nan
    centered = x - x.mean()
    gamma0 = float(np.dot(centered, centered) / n)
    var = gamma0
    lag = min(max_lag, n - 1)
    for ell in range(1, lag + 1):
        cov = float(np.dot(centered[ell:], centered[:-ell]) / n)
        weight = 1.0 - ell / (lag + 1.0)
        var += 2.0 * weight * cov
    return max(var, 0.0)


def dm_test(loss_a: np.ndarray, loss_c: np.ndarray, hac_lag: int) -> dict[str, float]:
    diff = np.asarray(loss_a, dtype=float) - np.asarray(loss_c, dtype=float)
    diff = diff[np.isfinite(diff)]
    n = len(diff)
    if n <= 2:
        return {
            "n": n,
            "mean_loss_diff_a0_minus_c": np.nan,
            "dm_stat": np.nan,
            "p_value_two_sided": np.nan,
            "p_value_c_better": np.nan,
        }
    mean_diff = float(diff.mean())
    long_run_var = hac_variance(diff, hac_lag)
    if not np.isfinite(long_run_var) or long_run_var <= 0:
        return {
            "n": n,
            "mean_loss_diff_a0_minus_c": mean_diff,
            "dm_stat": np.nan,
            "p_value_two_sided": np.nan,
            "p_value_c_better": np.nan,
        }
    se = np.sqrt(long_run_var / n)
    dm = mean_diff / se
    df = n - 1
    p_two = float(2 * (1 - stats.t.cdf(abs(dm), df=df)))
    # H1: A0 loss - C loss > 0, i.e. C has lower expected loss.
    p_c_better = float(1 - stats.t.cdf(dm, df=df))
    return {
        "n": n,
        "mean_loss_diff_a0_minus_c": mean_diff,
        "dm_stat": float(dm),
        "p_value_two_sided": p_two,
        "p_value_c_better": p_c_better,
    }


def bh_fdr(pvalues: pd.Series) -> pd.Series:
    p = pvalues.astype(float)
    valid = p.notna()
    adjusted = pd.Series(np.nan, index=p.index, dtype=float)
    if valid.sum() == 0:
        return adjusted
    pv = p[valid].to_numpy()
    order = np.argsort(pv)
    ranked = pv[order]
    m = len(ranked)
    q = ranked * m / np.arange(1, m + 1)
    q = np.minimum.accumulate(q[::-1])[::-1]
    q = np.clip(q, 0, 1)
    out = np.empty_like(q)
    out[order] = q
    adjusted.loc[valid] = out
    return adjusted


def main() -> None:
    forecasts = pd.read_parquet(OUT_DIR / "test_forecasts.parquet")
    forecasts = forecasts[forecasts["model"].isin(["A0_global_baseline", "C_cluster_specific"])].copy()
    forecasts["sq_error"] = (forecasts["y"] - forecasts["yhat"]) ** 2
    forecasts["abs_error"] = (forecasts["y"] - forecasts["yhat"]).abs()

    keys = ["id", "origin", "d", "cat_id", "store_id", "cluster_label"]
    a0 = forecasts[forecasts["model"].eq("A0_global_baseline")][keys + ["sq_error", "abs_error"]].copy()
    c = forecasts[forecasts["model"].eq("C_cluster_specific")][keys + ["sq_error", "abs_error"]].copy()
    wide = a0.merge(c, on=keys, suffixes=("_a0", "_c"), how="inner")
    wide = wide.sort_values(["id", "origin", "d"])

    rows = []
    for item_id, grp in wide.groupby("id", sort=False):
        meta = grp.iloc[0]
        for loss_name in ["sq_error", "abs_error"]:
            res = dm_test(
                grp[f"{loss_name}_a0"].to_numpy(),
                grp[f"{loss_name}_c"].to_numpy(),
                hac_lag=27,
            )
            rows.append(
                {
                    "id": item_id,
                    "loss": loss_name,
                    "cat_id": meta["cat_id"],
                    "store_id": meta["store_id"],
                    "state_id": str(meta["store_id"]).split("_")[0],
                    "cluster_label": int(meta["cluster_label"]),
                    **res,
                }
            )
    by_series = pd.DataFrame(rows)
    by_series["fdr_p_value_c_better"] = by_series.groupby("loss", group_keys=False)["p_value_c_better"].apply(bh_fdr)
    by_series["c_better_mean_loss"] = by_series["mean_loss_diff_a0_minus_c"] > 0
    by_series["c_better_p05"] = (by_series["p_value_c_better"] < 0.05) & by_series["c_better_mean_loss"]
    by_series["c_better_fdr05"] = (by_series["fdr_p_value_c_better"] < 0.05) & by_series["c_better_mean_loss"]
    by_series.to_csv(OUT_DIR / "dm_test_a0_vs_c_by_series.csv", index=False)

    summary_rows = []
    for loss, grp in by_series.groupby("loss"):
        summary_rows.append(
            {
                "loss": loss,
                "n_series": int(grp["id"].nunique()),
                "mean_loss_diff_a0_minus_c": float(grp["mean_loss_diff_a0_minus_c"].mean()),
                "median_loss_diff_a0_minus_c": float(grp["mean_loss_diff_a0_minus_c"].median()),
                "mean_dm_stat": float(grp["dm_stat"].mean()),
                "median_dm_stat": float(grp["dm_stat"].median()),
                "share_c_better_mean_loss": float(grp["c_better_mean_loss"].mean()),
                "share_c_better_p05": float(grp["c_better_p05"].mean()),
                "share_c_better_fdr05": float(grp["c_better_fdr05"].mean()),
                "share_a0_better_mean_loss": float((grp["mean_loss_diff_a0_minus_c"] < 0).mean()),
            }
        )
    summary = pd.DataFrame(summary_rows)
    summary.to_csv(OUT_DIR / "dm_test_a0_vs_c_summary.csv", index=False)

    group_rows = []
    for loss, loss_df in by_series.groupby("loss"):
        for group_col in ["cat_id", "store_id", "state_id", "cluster_label"]:
            for group, grp in loss_df.groupby(group_col, observed=True):
                group_rows.append(
                    {
                        "loss": loss,
                        "group_type": group_col,
                        "group": group,
                        "n_series": int(grp["id"].nunique()),
                        "mean_loss_diff_a0_minus_c": float(grp["mean_loss_diff_a0_minus_c"].mean()),
                        "median_dm_stat": float(grp["dm_stat"].median()),
                        "share_c_better_mean_loss": float(grp["c_better_mean_loss"].mean()),
                        "share_c_better_p05": float(grp["c_better_p05"].mean()),
                        "share_c_better_fdr05": float(grp["c_better_fdr05"].mean()),
                    }
                )
    by_group = pd.DataFrame(group_rows)
    by_group.to_csv(OUT_DIR / "dm_test_a0_vs_c_by_group.csv", index=False)

    print(summary.to_string(index=False))
    print(OUT_DIR / "dm_test_a0_vs_c_by_series.csv")
    print(OUT_DIR / "dm_test_a0_vs_c_by_group.csv")


if __name__ == "__main__":
    main()
