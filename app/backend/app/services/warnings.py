from __future__ import annotations

from app.schemas.forecast import ForecastPoint, SalesRecord
from app.services.features import demand_features


def build_warnings(records: list[SalesRecord], forecast: list[ForecastPoint]) -> list[str]:
    features = demand_features(records)
    warnings: list[str] = []
    values = [p.forecast for p in forecast]
    avg_forecast = sum(values) / len(values) if values else 0.0
    recent_mean = features["last_28_mean"]

    if features["zero_sales_ratio"] >= 0.6:
        warnings.append("Nhu cầu đứt quãng: tỷ lệ ngày không bán cao, forecast có thể nhạy với spike.")
    if recent_mean <= 0.1:
        warnings.append("Nhu cầu gần 0: các chỉ số phần trăm có thể bị phóng đại.")
    if avg_forecast > recent_mean * 1.5 and avg_forecast - recent_mean > 1:
        warnings.append("Nguy cơ tồn kho: forecast trung bình cao hơn đáng kể so với lịch sử gần đây.")
    if avg_forecast < recent_mean * 0.6 and recent_mean > 1:
        warnings.append("Nguy cơ thiếu hàng: forecast thấp hơn đáng kể so với lịch sử gần đây.")

    for prev, cur in zip(values, values[1:]):
        base = max(prev, 0.5)
        if abs(cur - prev) / base >= 0.5 and abs(cur - prev) >= 2:
            warnings.append("Forecast jump: dự báo có bước nhảy lớn giữa các ngày liền kề.")
            break

    if not warnings:
        warnings.append("Không phát hiện cảnh báo vận hành lớn theo ngưỡng MVP.")
    return warnings

