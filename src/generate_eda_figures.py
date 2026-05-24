from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd


EDA_DIR = Path("outputs_full_k3_seed42_tweedie_a0_b1_c/eda")
OUTPUT_DIR = Path("outputs_eda_figures")


def save(fig: plt.Figure, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def annotate_bars(ax: plt.Axes, values, suffix: str = "") -> None:
    ymax = max(values) if len(values) else 0
    offset = ymax * 0.015 if ymax else 0.01
    for idx, value in enumerate(values):
        ax.text(idx, value + offset, f"{value:,.0f}{suffix}", ha="center", va="bottom", fontsize=9)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    series = pd.read_parquet(EDA_DIR / "series_summary.parquet")
    demand_counts = pd.read_csv(EDA_DIR / "demand_class_counts.csv")
    hierarchy = pd.read_csv(EDA_DIR / "hierarchy_summary.csv")
    prices = pd.read_csv(EDA_DIR / "price_summary_by_store.csv")

    manifest: list[dict[str, str | int]] = []

    # Figure EDA 1: demand regime distribution.
    order = ["intermittent", "lumpy", "smooth", "erratic"]
    demand_counts["demand_class"] = pd.Categorical(demand_counts["demand_class"], order, ordered=True)
    demand_counts = demand_counts.sort_values("demand_class")
    total_series = demand_counts["n_series"].sum()
    demand_counts["share"] = demand_counts["n_series"] / total_series * 100

    fig, ax = plt.subplots(figsize=(7.2, 4.5))
    colors = ["#4C78A8", "#F58518", "#54A24B", "#B279A2"]
    ax.bar(demand_counts["demand_class"].astype(str), demand_counts["n_series"], color=colors)
    annotate_bars(ax, demand_counts["n_series"].tolist())
    for idx, row in demand_counts.reset_index(drop=True).iterrows():
        ax.text(idx, row["n_series"] * 0.55, f"{row['share']:.1f}%", ha="center", va="center", color="white", fontsize=10, fontweight="bold")
    ax.set_title("Phân bố chuỗi theo nhóm nhu cầu")
    ax.set_ylabel("Số chuỗi item-store")
    ax.set_xlabel("Nhóm nhu cầu")
    path = OUTPUT_DIR / "eda_fig01_demand_class_counts.png"
    save(fig, path)
    manifest.append(
        {
            "figure": 1,
            "title": "Phân bố chuỗi theo nhóm nhu cầu",
            "path": str(path),
            "caption": "Intermittent demand chiếm tỷ trọng lớn nhất trong dữ liệu M5, cho thấy bài toán có nhiều chuỗi bán thưa và nhiều ngày bằng 0.",
        }
    )

    # Figure EDA 2: zero-sales ratio distribution.
    median_zero = series["zero_sales_ratio"].median()
    fig, ax = plt.subplots(figsize=(7.2, 4.5))
    ax.hist(series["zero_sales_ratio"], bins=40, color="#4C78A8", edgecolor="white")
    ax.axvline(median_zero, color="#E45756", linewidth=2, label=f"Median = {median_zero:.4f}")
    ax.set_title("Phân phối tỷ lệ ngày không bán được")
    ax.set_xlabel("Zero-sales ratio")
    ax.set_ylabel("Số chuỗi")
    ax.legend()
    path = OUTPUT_DIR / "eda_fig02_zero_sales_ratio_distribution.png"
    save(fig, path)
    manifest.append(
        {
            "figure": 2,
            "title": "Phân phối zero-sales ratio",
            "path": str(path),
            "caption": "Median zero-sales ratio bằng 0.6337, nghĩa là chuỗi điển hình có hơn 63% số ngày không phát sinh doanh số.",
        }
    )

    # Figure EDA 3: ADI-CV2 demand classification map.
    plot_series = series.copy()
    if len(plot_series) > 30490:
        plot_series = plot_series.sample(30490, random_state=42)
    class_colors = {
        "smooth": "#54A24B",
        "intermittent": "#4C78A8",
        "erratic": "#B279A2",
        "lumpy": "#F58518",
    }
    fig, ax = plt.subplots(figsize=(7.2, 5.0))
    for cls in order:
        subset = plot_series[plot_series["demand_class"] == cls]
        ax.scatter(
            subset["adi"].clip(upper=15),
            subset["cv2"].clip(upper=3),
            s=8,
            alpha=0.35,
            color=class_colors.get(cls, "#999999"),
            label=cls,
            linewidths=0,
        )
    ax.axvline(1.32, color="#333333", linestyle="--", linewidth=1)
    ax.axhline(0.49, color="#333333", linestyle="--", linewidth=1)
    ax.set_title("Bản đồ ADI-CV2 của các chuỗi nhu cầu")
    ax.set_xlabel("ADI, giới hạn hiển thị tại 15")
    ax.set_ylabel("CV2, giới hạn hiển thị tại 3")
    ax.legend(title="Nhóm nhu cầu", markerscale=2)
    path = OUTPUT_DIR / "eda_fig03_adi_cv2_by_demand_class.png"
    save(fig, path)
    manifest.append(
        {
            "figure": 3,
            "title": "Bản đồ ADI-CV2 theo nhóm nhu cầu",
            "path": str(path),
            "caption": "ADI và CV2 tách rõ các demand regimes; đây là cơ sở để đưa intermittency và volatility vào clustering features.",
        }
    )

    # Figure EDA 4: category-level sales and sparsity.
    cats = hierarchy[hierarchy["level"] == "cat_id"].sort_values("total_sales", ascending=False)
    fig, axes = plt.subplots(1, 2, figsize=(9.2, 4.2))
    axes[0].bar(cats["group"], cats["total_sales"] / 1_000_000, color="#4C78A8")
    axes[0].set_title("Tổng doanh số theo ngành hàng")
    axes[0].set_ylabel("Triệu đơn vị bán")
    axes[0].set_xlabel("Ngành hàng")
    axes[1].bar(cats["group"], cats["median_zero_sales_ratio"], color="#F58518")
    axes[1].set_title("Median zero-sales ratio theo ngành hàng")
    axes[1].set_ylabel("Median zero-sales ratio")
    axes[1].set_ylim(0, 1)
    axes[1].set_xlabel("Ngành hàng")
    path = OUTPUT_DIR / "eda_fig04_category_sales_zero_ratio.png"
    save(fig, path)
    manifest.append(
        {
            "figure": 4,
            "title": "Khác biệt nhu cầu theo ngành hàng",
            "path": str(path),
            "caption": "FOODS chiếm phần lớn doanh số và có zero-sales ratio thấp hơn, trong khi HOBBIES và HOUSEHOLD thưa hơn; điều này ủng hộ việc dùng hierarchy features.",
        }
    )

    # Figure EDA 5: store-level heterogeneity.
    stores = hierarchy[hierarchy["level"] == "store_id"].copy()
    stores["state"] = stores["group"].str.split("_").str[0]
    stores = stores.sort_values("total_sales", ascending=False)
    state_colors = {"CA": "#4C78A8", "TX": "#F58518", "WI": "#54A24B"}
    fig, axes = plt.subplots(2, 1, figsize=(9.0, 6.2), sharex=True)
    axes[0].bar(stores["group"], stores["total_sales"] / 1_000_000, color=[state_colors[s] for s in stores["state"]])
    axes[0].set_title("Tổng doanh số theo cửa hàng")
    axes[0].set_ylabel("Triệu đơn vị bán")
    axes[1].bar(stores["group"], stores["median_zero_sales_ratio"], color=[state_colors[s] for s in stores["state"]])
    axes[1].set_title("Median zero-sales ratio theo cửa hàng")
    axes[1].set_ylabel("Median zero-sales ratio")
    axes[1].set_xlabel("Cửa hàng")
    axes[1].set_ylim(0, 1)
    path = OUTPUT_DIR / "eda_fig05_store_sales_zero_ratio.png"
    save(fig, path)
    manifest.append(
        {
            "figure": 5,
            "title": "Khác biệt nhu cầu theo cửa hàng",
            "path": str(path),
            "caption": "CA_3 có doanh số cao và tỷ lệ ngày không bán thấp, trong khi một số cửa hàng có nhu cầu thưa hơn; khác biệt này cần được mô hình hóa ở cấp store/state.",
        }
    )

    # Figure EDA 6: price distribution summary by store.
    prices = prices.sort_values("median_price", ascending=False)
    fig, axes = plt.subplots(2, 1, figsize=(9.0, 6.0), sharex=True)
    axes[0].bar(prices["store_id"], prices["median_price"], color="#4C78A8")
    axes[0].set_title("Median giá bán theo cửa hàng")
    axes[0].set_ylabel("Median sell price")
    axes[1].bar(prices["store_id"], prices["max_price"], color="#E45756")
    axes[1].set_title("Giá bán tối đa theo cửa hàng")
    axes[1].set_ylabel("Max sell price")
    axes[1].set_xlabel("Cửa hàng")
    path = OUTPUT_DIR / "eda_fig06_price_summary_by_store.png"
    save(fig, path)
    manifest.append(
        {
            "figure": 6,
            "title": "Đặc điểm giá bán theo cửa hàng",
            "path": str(path),
            "caption": "Median price giữa các cửa hàng khá gần nhau nhưng tồn tại các giá trị tối đa rất cao, vì vậy price features cần được kiểm tra bằng ablation để tránh diễn giải quá mức.",
        }
    )

    # Figure EDA 7: mean-sales skewness.
    fig, ax = plt.subplots(figsize=(7.2, 4.5))
    ax.hist(series["mean_sales"].clip(upper=10), bins=50, color="#72B7B2", edgecolor="white")
    ax.set_title("Phân phối mean sales của chuỗi item-store")
    ax.set_xlabel("Mean sales, giới hạn hiển thị tại 10")
    ax.set_ylabel("Số chuỗi")
    path = OUTPUT_DIR / "eda_fig07_mean_sales_distribution.png"
    save(fig, path)
    manifest.append(
        {
            "figure": 7,
            "title": "Phân phối mean sales của chuỗi",
            "path": str(path),
            "caption": "Phân phối mean sales lệch phải mạnh: phần lớn chuỗi có nhu cầu thấp, còn một số ít chuỗi có doanh số cao hơn đáng kể.",
        }
    )

    manifest_df = pd.DataFrame(manifest)
    manifest_df.to_csv(OUTPUT_DIR / "eda_figure_manifest.csv", index=False)
    print(OUTPUT_DIR / "eda_figure_manifest.csv")


if __name__ == "__main__":
    main()
