from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.core.config import APP_DIR

app = FastAPI(title="Cluster-Aware Retail Demand Forecasting API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")

frontend_static_dir = APP_DIR / "frontend_static"
if frontend_static_dir.exists():
    @app.get("/", include_in_schema=False)
    def serve_index() -> FileResponse:
        return FileResponse(frontend_static_dir / "index.html")

    @app.get("/index.html", include_in_schema=False)
    def serve_index_html() -> FileResponse:
        return FileResponse(frontend_static_dir / "index.html")

    app.mount("/", StaticFiles(directory=str(frontend_static_dir), html=True), name="frontend")
