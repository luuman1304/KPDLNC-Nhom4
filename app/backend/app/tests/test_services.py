from __future__ import annotations

from datetime import date, timedelta

from app.schemas.forecast import ForecastRequest, SalesRecord
from app.services.forecast import run_forecast
from app.services.validation import validate_records


def make_records(n: int = 30) -> list[SalesRecord]:
    start = date(2026, 1, 1)
    return [
        SalesRecord(
            item_id="ITEM",
            store_id="STORE",
            state_id="CA",
            category_id="FOODS",
            department_id="FOODS_1",
            date=start + timedelta(days=i),
            sales=float(i % 3),
            sell_price=2.99,
            snap=0,
        )
        for i in range(n)
    ]


def test_validate_records_ok() -> None:
    response = validate_records(make_records())
    assert response.valid
    assert response.n_records == 30


def test_validate_records_too_short() -> None:
    response = validate_records(make_records(7))
    assert not response.valid


def test_run_forecast_returns_28_points() -> None:
    response = run_forecast(ForecastRequest(model_name="C", records=make_records()))
    assert len(response.forecast) == 28
    assert response.cluster.cluster_id in {0, 1, 2}
    assert response.forecast[0].forecast >= 0
