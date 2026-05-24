from __future__ import annotations

from io import BytesIO

from fastapi import APIRouter, HTTPException, Response
import xlsxwriter

from app.core.config import FORECAST_HORIZON, SAMPLE_DATA_DIR, SUPPORTED_MODELS
from app.schemas.forecast import BatchForecastResponse, ForecastRequest, ForecastResponse, ValidationResponse
from app.services.artifacts import registry
from app.services.cluster import cluster_info_for_id, predict_cluster
from app.services.production_inference import get_production_adapter
from app.services.forecast import run_batch_forecast, run_forecast
from app.services.validation import validate_records

router = APIRouter()


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "artifact_mode": registry.mode}


@router.get("/overview")
def overview() -> dict:
    profiles = registry.cluster_profiles.to_dict(orient="records")
    if registry.mode == "artifact_available":
        warnings = ["Đã có artifact đã train; forecast dùng LightGBM artifacts từ origin 1913."]
    elif registry.mode == "production":
        warnings = []
    else:
        warnings = ["Chưa có artifact production; app đang ở demo mode."]
    return {
        "artifact_mode": registry.mode,
        "forecast_horizon": FORECAST_HORIZON,
        "supported_models": SUPPORTED_MODELS,
        "recommended_model": "C",
        "cluster_profiles": profiles,
        "metric_summary": registry.metric_summary(),
        "warnings": warnings,
    }


@router.get("/input-template")
def input_template() -> Response:
    output = BytesIO()
    workbook = xlsxwriter.Workbook(output, {"in_memory": True})

    header_fmt = workbook.add_format({"bold": True, "bg_color": "#163450", "font_color": "#FFFFFF", "border": 1})
    text_fmt = workbook.add_format({"text_wrap": True, "valign": "top", "border": 1})
    note_fmt = workbook.add_format({"text_wrap": True, "valign": "top", "font_color": "#475467"})
    date_fmt = workbook.add_format({"num_format": "yyyy-mm-dd", "border": 1})
    number_fmt = workbook.add_format({"num_format": "0.00", "border": 1})
    int_fmt = workbook.add_format({"num_format": "0", "border": 1})

    guide = workbook.add_worksheet("Huong_dan_nhap")
    guide.set_column("A:A", 24)
    guide.set_column("B:B", 36)
    guide.set_column("C:C", 58)
    guide.write_row("A1", ["Cot", "Cach nhap de on dinh hon", "Ghi chu"], header_fmt)
    guide_rows = [
        ("item_id", "Nen dung ma hang gan voi M5, vi du FOODS_1_001", "Model da train tren item/category cua M5. ID la chuoi ky tu, khong de trong."),
        ("store_id", "Dung mot trong 10 store M5: CA_1, CA_2, CA_3, CA_4, TX_1, TX_2, TX_3, WI_1, WI_2, WI_3", "Neu dung store ngoai M5, app van chay nhung do tin cay giam."),
        ("state_id", "CA, TX hoac WI", "Nen khop voi store_id, vi du CA_1 thuoc CA."),
        ("category_id", "FOODS, HOBBIES hoac HOUSEHOLD", "Nen khop voi department_id."),
        ("department_id", "FOODS_1, FOODS_2, FOODS_3, HOBBIES_1, HOBBIES_2, HOUSEHOLD_1, HOUSEHOLD_2", "Day la cap phan cap duoc dung trong training."),
        ("date", "YYYY-MM-DD va lien tuc theo ngay", "Can toi thieu 28 ngay lich su; 56-90 ngay giup lag/rolling on dinh hon."),
        ("sales", "So luong ban moi ngay, >= 0", "Nhap 0 khi khong ban duoc hang. Khong nhap gia tri am."),
        ("sell_price", "Gia ban duong, vi du 2.99", "Nen giu cung thang do voi M5. Neu khong co gia, co the de trong nhung ket qua kem on dinh hon."),
        ("event_name", "Ten su kien neu co, hoac de trong", "Vi du SuperBowl, ValentinesDay, Easter. Neu khong chac, de trong."),
        ("event_type", "Loai su kien neu co, hoac de trong", "Vi du Sporting, Cultural, National, Religious."),
        ("snap", "0 hoac 1", "SNAP la bien tro cap thuc pham. Neu khong biet, nhap 0."),
    ]
    for row_idx, row in enumerate(guide_rows, start=1):
        guide.write_row(row_idx, 0, row, text_fmt)
    guide.write("A14", "Khuyen nghi", header_fmt)
    guide.write(
        "B14",
        "Dung ID/category/store gan M5, chuoi ngay lien tuc, toi thieu 28 ngay lich su, sales khong am, snap chi 0/1. "
        "Ket qua on dinh hon khi du lieu nguoi dung co hanh vi gan voi nhung chuoi da train.",
        note_fmt,
    )

    data = workbook.add_worksheet("Nhap_du_lieu")
    columns = ["item_id", "store_id", "state_id", "category_id", "department_id", "date", "sales", "sell_price", "event_name", "event_type", "snap"]
    data.write_row(0, 0, columns, header_fmt)
    sample_rows = [
        ["FOODS_1_001", "CA_1", "CA", "FOODS", "FOODS_1", "2026-01-01", 0, 2.99, "", "", 0],
        ["FOODS_1_001", "CA_1", "CA", "FOODS", "FOODS_1", "2026-01-02", 1, 2.99, "", "", 0],
        ["FOODS_1_001", "CA_1", "CA", "FOODS", "FOODS_1", "2026-01-03", 0, 2.99, "", "", 0],
    ]
    for i, row in enumerate(sample_rows, start=1):
        for j, value in enumerate(row):
            if columns[j] == "date":
                data.write(i, j, value, date_fmt)
            elif columns[j] in {"sales", "snap"}:
                data.write(i, j, value, int_fmt)
            elif columns[j] == "sell_price":
                data.write(i, j, value, number_fmt)
            else:
                data.write(i, j, value, text_fmt)
    data.set_column("A:E", 16)
    data.set_column("F:F", 14)
    data.set_column("G:H", 12)
    data.set_column("I:J", 18)
    data.set_column("K:K", 10)
    data.freeze_panes(1, 0)

    values = workbook.add_worksheet("Gia_tri_goi_y")
    values.set_column("A:C", 34)
    values.write_row("A1", ["Nhom", "Gia tri goi y", "Ghi chu"], header_fmt)
    suggested = [
        ("store_id", "CA_1, CA_2, CA_3, CA_4", "California stores"),
        ("store_id", "TX_1, TX_2, TX_3", "Texas stores"),
        ("store_id", "WI_1, WI_2, WI_3", "Wisconsin stores"),
        ("state_id", "CA, TX, WI", "Nen khop voi store_id"),
        ("category_id", "FOODS, HOBBIES, HOUSEHOLD", "Category M5"),
        ("department_id", "FOODS_1, FOODS_2, FOODS_3", "FOODS departments"),
        ("department_id", "HOBBIES_1, HOBBIES_2", "HOBBIES departments"),
        ("department_id", "HOUSEHOLD_1, HOUSEHOLD_2", "HOUSEHOLD departments"),
        ("event_type", "Sporting, Cultural, National, Religious", "Co the de trong neu khong co su kien"),
        ("snap", "0, 1", "Chi nhap 0 hoac 1"),
    ]
    for i, row in enumerate(suggested, start=1):
        values.write_row(i, 0, row, text_fmt)

    workbook.close()
    content = output.getvalue()
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=input_template_m5_forecast.xlsx"},
    )


@router.get("/sample-series")
def sample_series() -> Response:
    path = SAMPLE_DATA_DIR / "sample_series.csv"
    return Response(
        content=path.read_text(encoding="utf-8"),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=sample_series_m5_forecast.csv"},
    )


@router.post("/validate-input", response_model=ValidationResponse)
def validate_input(request: ForecastRequest) -> ValidationResponse:
    return validate_records(request.records)


@router.post("/cluster/predict")
def cluster_predict(request: ForecastRequest) -> dict:
    validation = validate_records(request.records)
    if not validation.valid:
        raise HTTPException(status_code=422, detail=validation.errors)
    if registry.mode == "artifact_available":
        try:
            adapter = get_production_adapter()
            if adapter.available:
                cluster_id = adapter.predict_cluster(request.records)
                return cluster_info_for_id(cluster_id, request.records).model_dump()
        except Exception:
            pass
    return predict_cluster(request.records).model_dump()


@router.post("/forecast", response_model=ForecastResponse)
def forecast(request: ForecastRequest) -> ForecastResponse:
    try:
        return run_forecast(request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/forecast-batch", response_model=BatchForecastResponse)
def forecast_batch(request: ForecastRequest) -> BatchForecastResponse:
    try:
        return run_batch_forecast(request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
