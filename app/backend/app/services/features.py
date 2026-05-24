from __future__ import annotations

import numpy as np
import pandas as pd

from app.schemas.forecast import SalesRecord


def records_to_frame(records: list[SalesRecord]) -> pd.DataFrame:
    data = [r.model_dump() for r in records]
    df = pd.DataFrame(data)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    return df


def demand_features(records: list[SalesRecord]) -> dict[str, float]:
    df = records_to_frame(records)
    sales = df["sales"].astype(float)
    positive = sales[sales > 0]
    nonzero_days = int((sales > 0).sum())
    total_days = int(len(sales))
    adi = float(total_days / nonzero_days) if nonzero_days else float(total_days)
    cv2 = float((positive.std(ddof=0) / positive.mean()) ** 2) if len(positive) > 1 and positive.mean() else 0.0
    gaps = []
    last = None
    for idx, value in enumerate(sales):
        if value > 0:
            if last is not None:
                gaps.append(idx - last)
            last = idx
    max_gap = float(max(gaps)) if gaps else float(total_days)
    return {
        "mean_sales": float(sales.mean()),
        "median_sales": float(sales.median()),
        "std_sales": float(sales.std(ddof=0)),
        "zero_sales_ratio": float((sales == 0).mean()),
        "nonzero_days": float(nonzero_days),
        "adi": adi,
        "cv2": cv2,
        "max_gap": max_gap,
        "last_7_mean": float(sales.tail(7).mean()),
        "last_28_mean": float(sales.tail(28).mean()),
    }


def next_forecast_dates(records: list[SalesRecord], horizon: int) -> list[pd.Timestamp]:
    df = records_to_frame(records)
    last_date = df["date"].max()
    return list(pd.date_range(last_date + pd.Timedelta(days=1), periods=horizon, freq="D"))


def stable_non_negative(value: float) -> float:
    if not np.isfinite(value):
        return 0.0
    return max(0.0, float(value))

