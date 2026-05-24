from __future__ import annotations

from pathlib import Path

import pandas as pd


RUNS = {
    "base_tweedie": {
        "metrics": Path("outputs_full_k3_seed42_tweedie_a0_b1_c/metrics"),
        "official_like": Path("outputs_full_tweedie_official_like_wrmsse/metrics/official_like_wrmsse_model_summary.csv"),
    },
    "no_price": {
        "metrics": Path("outputs_full_k3_seed42_tweedie_no_price_a0_b1_c/metrics"),
        "official_like": Path("outputs_full_no_price_official_like_wrmsse/metrics/official_like_wrmsse_model_summary.csv"),
    },
    "no_calendar": {
        "metrics": Path("outputs_full_k3_seed42_tweedie_no_calendar_a0_b1_c/metrics"),
        "official_like": Path("outputs_full_no_calendar_official_like_wrmsse/metrics/official_like_wrmsse_model_summary.csv"),
    },
    "no_hierarchy": {
        "metrics": Path("outputs_full_k3_seed42_tweedie_no_hierarchy_a0_b1_c/metrics"),
        "official_like": Path("outputs_full_no_hierarchy_official_like_wrmsse/metrics/official_like_wrmsse_model_summary.csv"),
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


def load_run(label: str, paths: dict[str, Path]) -> pd.DataFrame:
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
    out.insert(0, "run", label)
    return out


def diff_vs_base(all_runs: pd.DataFrame) -> pd.DataFrame:
    base = all_runs.loc[all_runs["run"] == "base_tweedie"].set_index("model")
    rows = []
    for run in ["no_price", "no_calendar", "no_hierarchy"]:
        cur = all_runs.loc[all_runs["run"] == run].set_index("model")
        for model in sorted(set(cur.index) & set(base.index)):
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


def cluster_regime_profile() -> pd.DataFrame:
    profiles = pd.read_csv("outputs_full_k3_seed42_tweedie_a0_b1_c/metrics/cluster_profiles.csv")
    early = profiles.loc[profiles["origin"].isin([1885, 1892, 1899])].copy()
    summary = early.groupby("cluster_label")[["n_series", "mean_sales", "zero_sales_ratio", "adi", "cv2", "avg_price", "event_lift"]].mean().reset_index()
    labels = {
        0: "Long-tail/intermittent demand",
        1: "Medium demand",
        2: "High-demand/core products",
    }
    summary["regime_interpretation"] = summary["cluster_label"].map(labels)
    return summary


def main() -> None:
    out_dir = Path("outputs_extended_fullscale_checks")
    metrics_dir = out_dir / "metrics"
    reports_dir = out_dir / "reports"
    metrics_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    all_runs = pd.concat([load_run(label, paths) for label, paths in RUNS.items()], ignore_index=True)
    diff = diff_vs_base(all_runs)
    cluster_profile = cluster_regime_profile()
    kmedoids = pd.read_csv("outputs_full_k3_seed42_tweedie_a0_b1_c/metrics/kmedoids_robustness.csv")
    nemenyi_ranks = pd.read_csv("outputs_full_nemenyi_tweedie_a0_b1_c/nemenyi_average_ranks.csv")
    nemenyi_pairs = pd.read_csv("outputs_full_nemenyi_tweedie_a0_b1_c/nemenyi_pairwise.csv")
    boot_store = pd.read_csv("outputs_full_k3_seed42_tweedie_a0_b1_c/metrics/block_bootstrap_store_id.csv")
    boot_cat = pd.read_csv("outputs_full_k3_seed42_tweedie_a0_b1_c/metrics/block_bootstrap_cat_id.csv")

    all_runs.to_csv(metrics_dir / "extended_fullscale_all_metrics.csv", index=False)
    diff.to_csv(metrics_dir / "extended_fullscale_ablation_diff_vs_base.csv", index=False)
    cluster_profile.to_csv(metrics_dir / "extended_fullscale_cluster_regime_profile.csv", index=False)

    c_diff = diff.loc[diff["model"] == "C_cluster_specific"].copy()
    lines = [
        "# Đánh giá bổ sung full-scale cho A0/B1/C",
        "",
        "## Phạm vi",
        "",
        "Báo cáo này tổng hợp các phần được bổ sung sau khi đã chốt phạm vi chỉ chạy A0, B1 và C:",
        "",
        "- Official-style/local close-to-official WRMSSE cho các run ablation.",
        "- Full-scale ablation: no price, no calendar, no hierarchy.",
        "- Cluster profiling từ full-scale K=3.",
        "- Statistical testing full-scale trên A0/B1/C.",
        "- K-Medoids robustness ở large-sample 2,000 chuỗi, không chạy full-scale vì không phù hợp chi phí.",
        "",
        "## Kết quả tất cả run",
        "",
        md_table(
            all_runs[
                [
                    "run",
                    "model",
                    "rmsse_item_store",
                    "rolling_wrmsse_mean",
                    "validation_origin_wrmsse_mean",
                    "scale_aware_stability_loss",
                    "mean_test_train_gap",
                    "mae",
                    "wape",
                    "bias",
                ]
            ].sort_values(["run", "validation_origin_wrmsse_mean", "rolling_wrmsse_mean"])
        ),
        "",
        "## Chênh lệch so với base Tweedie",
        "",
        "Giá trị âm tốt hơn base; giá trị dương xấu hơn base.",
        "",
        md_table(diff),
        "",
        "## Tập trung vào model C",
        "",
        md_table(c_diff),
        "",
        "Diễn giải model C:",
        "",
        "- `no_price` làm C xấu nhẹ so với base: rolling WRMSSE tăng khoảng 0.00190 và validation WRMSSE tăng khoảng 0.00140.",
        "- `no_calendar` làm C xấu rất mạnh: rolling WRMSSE tăng khoảng 0.39142 và validation WRMSSE tăng khoảng 0.37145. Calendar/SNAP/event là nhóm feature bắt buộc giữ.",
        "- `no_hierarchy` làm C xấu rõ: rolling WRMSSE tăng khoảng 0.05245 và validation WRMSSE tăng khoảng 0.04914. Các ID/hierarchy features rất quan trọng.",
        "",
        "## Cluster profiling",
        "",
        md_table(cluster_profile),
        "",
        "Diễn giải cụm:",
        "",
        "- Cụm long-tail/intermittent có mean sales thấp, zero-sales ratio cao và ADI cao. Đây là nhóm bán chậm, nhiều ngày không phát sinh nhu cầu.",
        "- Cụm medium demand có doanh số trung bình và tần suất bán đều hơn.",
        "- Cụm high-demand/core products có mean sales cao, zero-sales ratio thấp và ADI thấp. Đây là nhóm quan trọng với WRMSSE vì thường có trọng số doanh thu lớn hơn.",
        "",
        "## K-Medoids robustness large-sample",
        "",
        md_table(kmedoids),
        "",
        "K-Medoids được chạy trên sample 2,000 chuỗi tại origin 1913. ARI khoảng 0.499 cho thấy cấu trúc cụm có mức tương đồng trung bình với Mini-batch K-Means, không phải trùng hoàn toàn. Điều này chấp nhận được vì K-Medoids chỉ là robustness check; pipeline chính vẫn nên dùng Mini-batch K-Means theo proposal.",
        "",
        "## Nemenyi post-hoc full-scale",
        "",
        "Average ranks:",
        "",
        md_table(nemenyi_ranks),
        "",
        "Pairwise checks:",
        "",
        md_table(nemenyi_pairs),
        "",
        "Diễn giải: Với chỉ 5 rolling origins, Nemenyi khá bảo thủ. C khác biệt có ý nghĩa so với A0 trên RMSSE item-store, nhưng C-B1 và các metric MAE/WAPE chưa đạt ngưỡng Nemenyi.",
        "",
        "## Block bootstrap full-scale",
        "",
        "Theo store:",
        "",
        md_table(boot_store),
        "",
        "Theo category:",
        "",
        md_table(boot_cat),
        "",
        "Diễn giải: Bootstrap theo store/category cho thấy C có xu hướng giảm MAE/WAPE so với A0, nhưng khoảng tin cậy vẫn cắt qua 0. Vì vậy nên viết là kết quả ủng hộ hướng cải thiện nhưng bằng chứng thống kê theo nhóm còn thận trọng.",
        "",
        "## Kết luận cập nhật",
        "",
        "- Base `K=3 + C_cluster_specific + Tweedie` vẫn là cấu hình chính tốt nhất.",
        "- Feature calendar/SNAP/event là nhóm quan trọng nhất trong ba ablation mới; bỏ nhóm này làm WRMSSE xấu mạnh.",
        "- Hierarchy/ID features cũng rất quan trọng; bỏ nhóm này làm WRMSSE xấu rõ.",
        "- Price features có đóng góp nhỏ hơn calendar/hierarchy trong cấu hình hiện tại, nhưng bỏ price vẫn làm C xấu nhẹ và làm stability xấu hơn.",
        "- K-Medoids không cần full-scale; large-sample robustness là phù hợp với proposal.",
        "- Statistical testing bổ sung giúp bài chặt hơn, nhưng do chỉ có 5 rolling origins nên không nên overclaim.",
    ]
    report = "\n".join(lines)
    (reports_dir / "extended_fullscale_checks.md").write_text(report, encoding="utf-8")
    Path("Document/Extended_Fullscale_Checks_Assessment.md").write_text(report, encoding="utf-8")


if __name__ == "__main__":
    main()
