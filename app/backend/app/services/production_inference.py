from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from app.schemas.forecast import ForecastPoint, SalesRecord
from app.services.artifacts import registry
from app.services.features import demand_features, next_forecast_dates, records_to_frame, stable_non_negative


LOG_COLS = [
    "total_sales",
    "mean_sales",
    "median_sales",
    "std_sales",
    "positive_mean",
    "avg_price",
    "price_std",
    "max_price",
]


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


class ProductionInferenceAdapter:
    def __init__(self) -> None:
        self.origin_dir = registry.model_origin_dir
        self.models: dict[str, Any] = {}
        self.schemas: dict[str, dict[str, Any]] = {}
        self.cluster_artifacts = registry.load_cluster_artifacts()
        self._load_models()

    @property
    def available(self) -> bool:
        required = {"A0", "B1", "C_0", "C_1", "C_2"}
        return required.issubset(self.models.keys()) and self.cluster_artifacts is not None

    def _load_model_pair(self, key: str, stem: str) -> None:
        os.environ.setdefault("MPLCONFIGDIR", "/private/tmp/mpl_m5_app")
        os.environ.setdefault("XDG_CACHE_HOME", "/private/tmp/xdg_m5_app")
        import lightgbm as lgb

        model_path = self.origin_dir / f"{stem}.txt"
        schema_path = self.origin_dir / f"{stem}_schema.json"
        if model_path.exists() and schema_path.exists():
            self.models[key] = lgb.Booster(model_file=str(model_path))
            self.schemas[key] = _read_json(schema_path)

    def _load_models(self) -> None:
        self._load_model_pair("A0", "A0_global_baseline")
        self._load_model_pair("B1", "B1_cluster_label")
        for cluster_id in [0, 1, 2]:
            self._load_model_pair(f"C_{cluster_id}", f"C_cluster_specific_cluster_{cluster_id}")

    def cluster_features(self, records: list[SalesRecord]) -> pd.DataFrame:
        base = demand_features(records)
        df = records_to_frame(records)
        sales = df["sales"].astype(float)
        positive = sales[sales > 0]
        prices = df["sell_price"].dropna().astype(float) if "sell_price" in df else pd.Series(dtype=float)
        feature_values = {
            **base,
            "total_sales": float(sales.sum()),
            "positive_mean": float(positive.mean()) if len(positive) else 0.0,
            "spike_freq": float((sales > max(sales.mean() + 2 * sales.std(ddof=0), 1.0)).mean()),
            "event_lift": 0.0,
            "weekend_ratio": float((df["date"].dt.weekday >= 5).mean()),
            "avg_price": float(prices.mean()) if len(prices) else 0.0,
            "price_std": float(prices.std(ddof=0)) if len(prices) else 0.0,
            "min_price": float(prices.min()) if len(prices) else 0.0,
            "max_price": float(prices.max()) if len(prices) else 0.0,
            "price_obs": float(len(prices)),
            "price_change_freq": float(prices.diff().fillna(0).ne(0).mean()) if len(prices) else 0.0,
            "relative_to_store": 1.0,
            "relative_to_cat": 1.0,
            "relative_to_dept": 1.0,
        }
        schema_cols = self.cluster_artifacts["schema"]["feature_cols"] if self.cluster_artifacts else list(feature_values)
        row = {col: feature_values.get(col, 0.0) for col in schema_cols}
        x = pd.DataFrame([row])
        for col in LOG_COLS:
            if col in x.columns:
                x[col] = np.log1p(np.maximum(x[col].astype(float), 0))
        return x

    def predict_cluster(self, records: list[SalesRecord]) -> int:
        if self.cluster_artifacts is None:
            raise RuntimeError("Clustering artifacts are missing.")
        x = self.cluster_features(records)
        scaled = self.cluster_artifacts["scaler"].transform(x)
        scaled_df = pd.DataFrame(scaled, columns=x.columns)
        return int(self.cluster_artifacts["model"].predict(scaled_df)[0])

    def _metadata(self, records: list[SalesRecord]) -> dict[str, str]:
        last = sorted(records, key=lambda r: r.date)[-1]
        return {
            "item_id": last.item_id,
            "dept_id": last.department_id,
            "cat_id": last.category_id,
            "store_id": last.store_id,
            "state_id": last.state_id,
        }

    def _feature_row(
        self,
        records: list[SalesRecord],
        history: list[float],
        forecast_date: pd.Timestamp,
        horizon_index: int,
        cluster_id: int,
        schema: dict[str, Any],
    ) -> pd.DataFrame:
        meta = self._metadata(records)
        prices = [float(r.sell_price) for r in records if r.sell_price is not None]
        sell_price = prices[-1] if prices else 0.0
        avg_price = float(np.mean(prices)) if prices else sell_price
        relative_price = sell_price / (avg_price + 1e-9) if avg_price else 0.0

        def lag(lag_days: int) -> float:
            idx = len(history) - lag_days
            return float(history[idx]) if idx >= 0 else 0.0

        def rolling(width: int) -> float:
            vals = history[-width:]
            return float(np.mean(vals)) if vals else 0.0

        row = {
            **meta,
            "wday": int(forecast_date.dayofweek + 1),
            "month": int(forecast_date.month),
            "year": int(forecast_date.year),
            "event_flag": 0,
            "event_type_flag": 0,
            "snap": int(records[-1].snap or 0),
            "is_available": 1,
            "days_since_release": len(history) + horizon_index,
            "lag_7": lag(7),
            "lag_14": lag(14),
            "lag_28": lag(28),
            "lag_56": lag(56),
            "rolling_mean_7": rolling(7),
            "rolling_mean_28": rolling(28),
            "rolling_mean_56": rolling(56),
            "sell_price": sell_price,
            "relative_price": relative_price,
            "cluster_label": int(cluster_id),
        }
        feature_cols = schema["feature_cols"]
        frame = pd.DataFrame([{col: row.get(col, 0.0) for col in feature_cols}])
        pandas_cats = getattr(self.models["A0"], "pandas_categorical", None)
        categorical_cols = schema.get("categorical_cols", [])
        if pandas_cats:
            for col, categories in zip(["item_id", "dept_id", "cat_id", "store_id", "state_id"], pandas_cats[:5]):
                if col in frame.columns:
                    frame[col] = pd.Categorical(frame[col], categories=categories)
            if "cluster_label" in frame.columns:
                frame["cluster_label"] = pd.Categorical(frame["cluster_label"])
        else:
            for col in categorical_cols:
                if col in frame.columns:
                    frame[col] = frame[col].astype("category")
        return frame

    def forecast(self, records: list[SalesRecord], model_name: str, horizon: int) -> tuple[list[ForecastPoint], int]:
        cluster_id = self.predict_cluster(records)
        if model_name == "A0":
            model_key = "A0"
        elif model_name == "B1":
            model_key = "B1"
        else:
            model_key = f"C_{cluster_id}"
        if model_key not in self.models:
            raise RuntimeError(f"Missing model artifact for {model_key}.")
        model = self.models[model_key]
        schema = self.schemas[model_key]
        history = [float(r.sales) for r in sorted(records, key=lambda r: r.date)]
        dates = next_forecast_dates(records, horizon)
        points: list[ForecastPoint] = []
        for idx, date_value in enumerate(dates, start=1):
            frame = self._feature_row(records, history, date_value, idx, cluster_id, schema)
            yhat = stable_non_negative(float(model.predict(frame[schema["feature_cols"]])[0]))
            history.append(yhat)
            points.append(ForecastPoint(date=date_value.date(), horizon=idx, forecast=round(yhat, 4)))
        return points, cluster_id


@lru_cache(maxsize=1)
def get_production_adapter() -> ProductionInferenceAdapter:
    return ProductionInferenceAdapter()
