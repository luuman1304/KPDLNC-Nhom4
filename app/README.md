# MVP Demand Forecasting Website

## Scope

The app implements the SRS in `Document/SRS_MVP_Demand_Forecasting_Website.md`.

It supports:

- Manual or CSV input of daily sales history.
- Model selection: A0, B1, C.
- 28-day forecast.
- Batch forecasting for multiple `item_id` + `store_id` series in one CSV upload.
- Per-series cluster assignment and cluster behavior summary.
- Operational warnings.

## Important

The web app is an inference system. It must not retrain LightGBM models, refit scalers, or refit clustering models during user requests.

If trained artifacts are missing, the backend starts in `demo` mode and returns explicit artifact warnings. Demo mode is only for UI/API development and must not be reported as research-model inference.

The current artifact run exports LightGBM and clustering artifacts for origin `1913`. When `/api/health` returns `artifact_available`, the backend uses those artifacts through the production inference adapter.

## Run Backend

```bash
cd "<repo-root>"
python -m venv .venv
source .venv/bin/activate
pip install -r app/backend/requirements.txt
PYTHONPATH=app/backend python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## Run Frontend

The no-build static MVP is served by the backend:

```text
http://127.0.0.1:8000
```

React/Vite version:

```bash
cd app/frontend
npm install
npm run dev
```

## Data Template

Use `/api/input-template` from the running backend to download the Excel input template. The template includes:

- `Huong_dan_nhap`: field-by-field input instructions.
- `Nhap_du_lieu`: upload sheet format.
- `Gia_tri_goi_y`: M5-like values for more stable inference.

Use `/api/sample-series` to download a multi-series sample CSV.
