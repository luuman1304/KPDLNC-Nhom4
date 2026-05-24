from __future__ import annotations

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field


class SalesRecord(BaseModel):
    item_id: str
    store_id: str
    state_id: str
    category_id: str
    department_id: str
    date: date
    sales: float = Field(ge=0)
    sell_price: Optional[float] = Field(default=None, ge=0)
    event_name: Optional[str] = None
    event_type: Optional[str] = None
    snap: Optional[int] = Field(default=None, ge=0, le=1)


class ForecastRequest(BaseModel):
    model_name: Literal["A0", "B1", "C"] = "C"
    forecast_horizon: int = Field(default=28, ge=1, le=56)
    records: list[SalesRecord]


class ValidationResponse(BaseModel):
    valid: bool
    errors: list[str] = []
    warnings: list[str] = []
    n_records: int = 0
    n_days: int = 0
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    mean_sales: Optional[float] = None
    zero_sales_ratio: Optional[float] = None


class ForecastPoint(BaseModel):
    date: date
    horizon: int
    forecast: float


class ClusterInfo(BaseModel):
    cluster_id: int
    cluster_name: str
    mean_sales: float
    zero_sales_ratio: float
    adi: float
    cv2: float
    interpretation: str


class ForecastResponse(BaseModel):
    request_id: str
    artifact_mode: str
    model_name: str
    model_label: str
    forecast_horizon: int
    forecast: list[ForecastPoint]
    cluster: ClusterInfo
    warnings: list[str]
    history: list[SalesRecord]


class SeriesForecastResult(BaseModel):
    series_key: str
    item_id: str
    store_id: str
    state_id: str
    category_id: str
    department_id: str
    n_records: int
    total_sales: float
    mean_sales_input: float
    zero_sales_ratio_input: float
    status: str
    errors: list[str] = []
    warnings: list[str] = []
    result: Optional[ForecastResponse] = None


class BatchForecastResponse(BaseModel):
    request_id: str
    artifact_mode: str
    model_name: str
    model_label: str
    forecast_horizon: int
    n_series: int
    n_success: int
    n_failed: int
    series: list[SeriesForecastResult]
