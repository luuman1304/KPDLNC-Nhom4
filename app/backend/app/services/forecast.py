from __future__ import annotations

import math
import uuid
from collections import defaultdict

from app.core.config import SUPPORTED_MODELS
from app.schemas.forecast import (
    BatchForecastResponse,
    ForecastPoint,
    ForecastRequest,
    ForecastResponse,
    SalesRecord,
    SeriesForecastResult,
)
from app.services.artifacts import registry
from app.services.cluster import cluster_info_for_id, predict_cluster
from app.services.production_inference import get_production_adapter
from app.services.features import demand_features, next_forecast_dates, stable_non_negative
from app.services.validation import validate_records
from app.services.warnings import build_warnings


def series_key_for_record(record: SalesRecord) -> str:
    return "|".join(
        [
            record.item_id,
            record.store_id,
            record.state_id,
            record.category_id,
            record.department_id,
        ]
    )


def group_records_by_series(records: list[SalesRecord]) -> dict[str, list[SalesRecord]]:
    grouped: dict[str, list[SalesRecord]] = defaultdict(list)
    for record in records:
        grouped[series_key_for_record(record)].append(record)
    return dict(grouped)


def _series_summary(series_key: str, records: list[SalesRecord]) -> dict:
    sorted_records = sorted(records, key=lambda r: r.date)
    first = sorted_records[0]
    sales = [float(r.sales) for r in sorted_records]
    total_sales = float(sum(sales))
    mean_sales = total_sales / len(sales) if sales else 0.0
    zero_sales_ratio = sum(1 for value in sales if value == 0) / len(sales) if sales else 0.0
    return {
        "series_key": series_key,
        "item_id": first.item_id,
        "store_id": first.store_id,
        "state_id": first.state_id,
        "category_id": first.category_id,
        "department_id": first.department_id,
        "n_records": len(sorted_records),
        "total_sales": round(total_sales, 6),
        "mean_sales_input": round(mean_sales, 6),
        "zero_sales_ratio_input": round(zero_sales_ratio, 6),
    }


def _demo_recursive_forecast(request: ForecastRequest, cluster_id: int) -> list[ForecastPoint]:
    features = demand_features(request.records)
    history = [float(r.sales) for r in sorted(request.records, key=lambda r: r.date)]
    dates = next_forecast_dates(request.records, request.forecast_horizon)
    model_factor = {"A0": 1.0, "B1": 1.02, "C": 0.98}.get(request.model_name, 1.0)
    cluster_factor = {0: 0.85, 1: 1.0, 2: 1.08}.get(cluster_id, 1.0)
    points: list[ForecastPoint] = []
    for idx, date_value in enumerate(dates, start=1):
        last_7 = sum(history[-7:]) / min(7, len(history))
        last_28 = sum(history[-28:]) / min(28, len(history))
        seasonal = 1.0 + 0.08 * math.sin(idx / 7 * 2 * math.pi)
        raw = (0.65 * last_7 + 0.35 * last_28) * model_factor * cluster_factor * seasonal
        if features["zero_sales_ratio"] > 0.7:
            raw *= 0.8
        value = stable_non_negative(raw)
        history.append(value)
        points.append(ForecastPoint(date=date_value.date(), horizon=idx, forecast=round(value, 4)))
    return points


def run_forecast(request: ForecastRequest) -> ForecastResponse:
    validation = validate_records(request.records)
    if not validation.valid:
        raise ValueError("; ".join(validation.errors))

    adapter_warning = None
    if registry.mode == "artifact_available":
        try:
            adapter = get_production_adapter()
            if not adapter.available:
                raise RuntimeError("Production adapter did not find all required artifacts.")
            forecast, cluster_id = adapter.forecast(request.records, request.model_name, request.forecast_horizon)
            cluster = cluster_info_for_id(cluster_id, request.records)
        except Exception as exc:
            cluster = predict_cluster(request.records)
            forecast = _demo_recursive_forecast(request, cluster.cluster_id)
            adapter_warning = f"Không thể chạy LightGBM artifact inference, fallback demo forecaster: {exc}"
    else:
        cluster = predict_cluster(request.records)
        forecast = _demo_recursive_forecast(request, cluster.cluster_id)
    warnings = build_warnings(request.records, forecast)
    if adapter_warning:
        warnings.insert(0, adapter_warning)
    elif registry.mode == "artifact_available":
        warnings.insert(0, "Forecast được tạo bằng LightGBM artifacts đã train từ origin 1913.")
    elif registry.mode != "production":
        warnings.insert(
            0,
            "Backend đang chạy demo mode vì chưa có pretrained LightGBM/scaler/clustering artifacts thật.",
        )

    return ForecastResponse(
        request_id=str(uuid.uuid4()),
        artifact_mode=registry.mode,
        model_name=request.model_name,
        model_label=SUPPORTED_MODELS[request.model_name],
        forecast_horizon=request.forecast_horizon,
        forecast=forecast,
        cluster=cluster,
        warnings=warnings,
        history=sorted(request.records, key=lambda r: r.date),
    )


def run_batch_forecast(request: ForecastRequest) -> BatchForecastResponse:
    grouped = group_records_by_series(request.records)
    if not grouped:
        raise ValueError("Dữ liệu rỗng.")

    series_results: list[SeriesForecastResult] = []
    for series_key, records in sorted(grouped.items()):
        summary = _series_summary(series_key, records)
        child_request = ForecastRequest(
            model_name=request.model_name,
            forecast_horizon=request.forecast_horizon,
            records=sorted(records, key=lambda r: r.date),
        )
        validation = validate_records(child_request.records)
        if not validation.valid:
            series_results.append(
                SeriesForecastResult(
                    **summary,
                    status="failed",
                    errors=validation.errors,
                    warnings=validation.warnings,
                    result=None,
                )
            )
            continue
        try:
            result = run_forecast(child_request)
            combined_warnings = [*validation.warnings, *result.warnings]
            series_results.append(
                SeriesForecastResult(
                    **summary,
                    status="success",
                    errors=[],
                    warnings=combined_warnings,
                    result=result,
                )
            )
        except Exception as exc:
            series_results.append(
                SeriesForecastResult(
                    **summary,
                    status="failed",
                    errors=[str(exc)],
                    warnings=validation.warnings,
                    result=None,
                )
            )

    n_success = sum(1 for item in series_results if item.status == "success")
    return BatchForecastResponse(
        request_id=str(uuid.uuid4()),
        artifact_mode=registry.mode,
        model_name=request.model_name,
        model_label=SUPPORTED_MODELS[request.model_name],
        forecast_horizon=request.forecast_horizon,
        n_series=len(series_results),
        n_success=n_success,
        n_failed=len(series_results) - n_success,
        series=series_results,
    )
