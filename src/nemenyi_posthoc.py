from __future__ import annotations

import argparse
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd


Q_ALPHA_05 = {
    2: 1.960,
    3: 2.343,
    4: 2.569,
    5: 2.728,
    6: 2.850,
    7: 2.949,
    8: 3.031,
    9: 3.102,
    10: 3.164,
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


def nemenyi(metrics: pd.DataFrame, metric: str, lower_is_better: bool = True) -> tuple[pd.DataFrame, pd.DataFrame]:
    pivot = metrics.pivot_table(index="origin", columns="model", values=metric).dropna(axis=1)
    ranks = pivot.rank(axis=1, ascending=lower_is_better, method="average")
    avg_ranks = ranks.mean(axis=0).sort_values().reset_index()
    avg_ranks.columns = ["model", "average_rank"]
    n_blocks = ranks.shape[0]
    n_models = ranks.shape[1]
    q_alpha = Q_ALPHA_05.get(n_models, 3.164)
    critical_difference = q_alpha * np.sqrt(n_models * (n_models + 1) / (6.0 * n_blocks))
    rows = []
    for left, right in combinations(avg_ranks["model"], 2):
        left_rank = float(avg_ranks.loc[avg_ranks["model"] == left, "average_rank"].iloc[0])
        right_rank = float(avg_ranks.loc[avg_ranks["model"] == right, "average_rank"].iloc[0])
        diff = abs(left_rank - right_rank)
        rows.append(
            {
                "metric": metric,
                "model_a": left,
                "model_b": right,
                "rank_diff": diff,
                "critical_difference": critical_difference,
                "significant_alpha_0.05": diff > critical_difference,
            }
        )
    pairs = pd.DataFrame(rows)
    avg_ranks["metric"] = metric
    avg_ranks["n_blocks"] = n_blocks
    avg_ranks["n_models"] = n_models
    avg_ranks["critical_difference"] = critical_difference
    return avg_ranks, pairs


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metrics", default="outputs_full_k3_seed42_a0_b1_c/metrics/model_test_metrics.csv")
    parser.add_argument("--out-dir", default="outputs_posthoc_stats")
    parser.add_argument("--report", default="Document/Nemenyi_Posthoc_Assessment.md")
    args = parser.parse_args()

    metrics = pd.read_csv(args.metrics)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    all_ranks = []
    all_pairs = []
    for metric in ["rmsse_item_store", "mae", "wape"]:
        ranks, pairs = nemenyi(metrics, metric, lower_is_better=True)
        all_ranks.append(ranks)
        all_pairs.append(pairs)
    rank_df = pd.concat(all_ranks, ignore_index=True)
    pair_df = pd.concat(all_pairs, ignore_index=True)
    rank_df.to_csv(out_dir / "nemenyi_average_ranks.csv", index=False)
    pair_df.to_csv(out_dir / "nemenyi_pairwise.csv", index=False)

    lines = [
        "# Nemenyi Post-Hoc Assessment",
        "",
        "## Scope",
        "",
        f"Input metrics: `{args.metrics}`.",
        "The test uses rolling origins as blocks and compares model average ranks after the Friedman test.",
        "",
        "## Average Ranks",
        "",
        md_table(rank_df),
        "",
        "## Pairwise Critical Difference Check",
        "",
        md_table(pair_df),
        "",
        "## Interpretation",
        "",
        "- With only five rolling-origin blocks, Nemenyi is conservative.",
        "- A non-significant Nemenyi pair does not invalidate bootstrap CI; it means the rank gap is not large enough under this conservative post-hoc test.",
    ]
    Path(args.report).write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
