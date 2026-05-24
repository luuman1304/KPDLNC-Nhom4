from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch


OUTPUT = Path("outputs_method_figures/method_workflow.png")


def box(ax, x, y, w, h, text, color):
    patch = FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle="round,pad=0.018,rounding_size=0.025",
        linewidth=1.2,
        edgecolor="#263238",
        facecolor=color,
    )
    ax.add_patch(patch)
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=9.2, color="#111111", wrap=True)
    return patch


def arrow(ax, start, end):
    ax.add_patch(
        FancyArrowPatch(
            start,
            end,
            arrowstyle="-|>",
            mutation_scale=14,
            linewidth=1.25,
            color="#455A64",
            shrinkA=4,
            shrinkB=4,
        )
    )


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(13.5, 7.6))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    ax.text(
        0.5,
        0.965,
        "Quy trình phương pháp thực hiện nghiên cứu Cluster-aware Global Forecasting trên dữ liệu M5",
        ha="center",
        va="top",
        fontsize=14,
        fontweight="bold",
        color="#1B1B1B",
    )

    w, h = 0.18, 0.105
    positions = {
        "data": (0.04, 0.78),
        "check": (0.29, 0.78),
        "eda": (0.54, 0.78),
        "split": (0.79, 0.78),
        "features": (0.04, 0.56),
        "cluster_features": (0.29, 0.56),
        "cluster": (0.54, 0.56),
        "models": (0.79, 0.56),
        "forecast": (0.04, 0.34),
        "metrics": (0.29, 0.34),
        "diagnostics": (0.54, 0.34),
        "report": (0.79, 0.34),
        "safeguard": (0.29, 0.12),
        "compare": (0.54, 0.12),
    }

    box(ax, *positions["data"], w, h, "Dữ liệu M5\nsales, calendar,\nsell prices", "#E3F2FD")
    box(ax, *positions["check"], w, h, "Kiểm tra dữ liệu\nsố chuỗi, horizon,\nmissing/consistency", "#E8F5E9")
    box(ax, *positions["eda"], w, h, "EDA\nintermittency,\nzero-sales, ADI-CV2,\nhierarchy, price", "#FFF3E0")
    box(ax, *positions["split"], w, h, "Rolling origins\n1885, 1892, 1899,\n1906, 1913", "#F3E5F5")

    box(ax, *positions["features"], w, h, "Feature engineering\nlag, rolling,\ncalendar/SNAP/event,\nprice, hierarchy", "#E0F7FA")
    box(ax, *positions["cluster_features"], w, h, "Feature phân cụm\ndemand level,\nvolatility,\nADI, CV2,\nprice behavior", "#F1F8E9")
    box(ax, *positions["cluster"], w, h, "Mini-batch K-Means\nK=3 theo từng origin\nkhông dùng tương lai", "#FFFDE7")
    box(ax, *positions["models"], w, h, "Huấn luyện mô hình\nA0: global\nB1: global + cluster\nC: cluster-specific", "#FCE4EC")

    box(ax, *positions["forecast"], w, h, "Recursive forecast\n28 ngày\ncập nhật lag bằng\nprediction", "#E8EAF6")
    box(ax, *positions["metrics"], w, h, "Đánh giá\nWRMSSE close-to-official\nscale-aware stability", "#E0F2F1")
    box(ax, *positions["diagnostics"], w, h, "Kiểm tra bổ sung\noverfitting gap,\nablation,\nrobustness,\nstatistical test", "#FBE9E7")
    box(ax, *positions["report"], w, h, "Diễn giải kết quả\nso sánh A0/B1/C\nso sánh M5 reference\nkết luận nghiên cứu", "#ECEFF1")

    box(ax, *positions["safeguard"], w, h, "Nguyên tắc anti-leakage\nfeature và clustering\nchỉ dùng dữ liệu\nđến origin T", "#FFEBEE")
    box(ax, *positions["compare"], w, h, "Kiểm tra mục tiêu proposal\naccuracy + stability\ncluster-aware benefit", "#EDE7F6")

    def center_right(key):
        x, y = positions[key]
        return (x + w, y + h / 2)

    def center_left(key):
        x, y = positions[key]
        return (x, y + h / 2)

    def center_bottom(key):
        x, y = positions[key]
        return (x + w / 2, y)

    def center_top(key):
        x, y = positions[key]
        return (x + w / 2, y + h)

    for a, b in [("data", "check"), ("check", "eda"), ("eda", "split")]:
        arrow(ax, center_right(a), center_left(b))
    arrow(ax, center_bottom("split"), center_top("models"))
    for a, b in [("features", "cluster_features"), ("cluster_features", "cluster"), ("cluster", "models")]:
        arrow(ax, center_right(a), center_left(b))
    arrow(ax, center_bottom("eda"), center_top("cluster_features"))
    arrow(ax, center_bottom("split"), center_top("features"))
    arrow(ax, center_bottom("models"), center_top("report"))
    for a, b in [("forecast", "metrics"), ("metrics", "diagnostics"), ("diagnostics", "report")]:
        arrow(ax, center_right(a), center_left(b))
    arrow(ax, center_bottom("models"), center_top("forecast"))
    arrow(ax, center_bottom("features"), center_top("safeguard"))
    arrow(ax, center_bottom("cluster"), center_top("compare"))
    arrow(ax, center_right("safeguard"), center_left("compare"))

    ax.text(
        0.5,
        0.035,
        "Luồng chính bảo đảm: dữ liệu quá khứ -> feature không leakage -> phân cụm theo origin -> huấn luyện A0/B1/C -> dự báo 28 ngày -> đánh giá accuracy, stability và độ tin cậy.",
        ha="center",
        va="center",
        fontsize=10,
        color="#37474F",
    )

    fig.savefig(OUTPUT, dpi=180, bbox_inches="tight")
    plt.close(fig)
    print(OUTPUT)


if __name__ == "__main__":
    main()
