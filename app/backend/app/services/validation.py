from __future__ import annotations

from collections import Counter

import pandas as pd

from app.core.config import MIN_HISTORY_DAYS
from app.schemas.forecast import SalesRecord, ValidationResponse


def validate_records(records: list[SalesRecord]) -> ValidationResponse:
    if not records:
        return ValidationResponse(valid=False, errors=["Dữ liệu rỗng."])

    errors: list[str] = []
    warnings: list[str] = []
    dates = [r.date for r in records]
    date_counts = Counter(dates)
    duplicated = sorted([str(d) for d, c in date_counts.items() if c > 1])
    if duplicated:
        errors.append(f"Ngày bị trùng: {', '.join(duplicated[:5])}.")

    sorted_records = sorted(records, key=lambda r: r.date)
    start_date = sorted_records[0].date
    end_date = sorted_records[-1].date
    expected_days = (end_date - start_date).days + 1
    if expected_days != len(set(dates)):
        warnings.append("Chuỗi ngày không liên tục; hệ thống sẽ xử lý như dữ liệu thiếu ngày.")

    if len(records) < MIN_HISTORY_DAYS:
        errors.append(f"Chuỗi lịch sử cần tối thiểu {MIN_HISTORY_DAYS} ngày để tạo lag/rolling features.")

    identity_fields = ["item_id", "store_id", "state_id", "category_id", "department_id"]
    for field in identity_fields:
        values = {getattr(r, field) for r in records}
        if "" in values:
            errors.append(f"Trường {field} không được để trống.")
        if len(values) > 1:
            warnings.append(f"Trường {field} có nhiều giá trị; MVP giả định một chuỗi item-store cho mỗi request.")

    sales = pd.Series([r.sales for r in records], dtype="float64")
    mean_sales = float(sales.mean())
    zero_ratio = float((sales == 0).mean())
    if zero_ratio > 0.7:
        warnings.append("Chuỗi có tỷ lệ ngày không bán cao, dự báo có thể kém ổn định.")

    return ValidationResponse(
        valid=not errors,
        errors=errors,
        warnings=warnings,
        n_records=len(records),
        n_days=len(set(dates)),
        start_date=start_date,
        end_date=end_date,
        mean_sales=mean_sales,
        zero_sales_ratio=zero_ratio,
    )

