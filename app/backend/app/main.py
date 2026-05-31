from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, Response
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
    def serve_index() -> HTMLResponse:
        return HTMLResponse((frontend_static_dir / "index.html").read_text(encoding="utf-8"))

    @app.get("/index.html", include_in_schema=False)
    def serve_index_html() -> HTMLResponse:
        return HTMLResponse((frontend_static_dir / "index.html").read_text(encoding="utf-8"))

    @app.get("/app.js", include_in_schema=False)
    def serve_app_js() -> Response:
        return Response(
            (frontend_static_dir / "app.js").read_text(encoding="utf-8"),
            media_type="text/javascript",
        )

    @app.get("/styles.css", include_in_schema=False)
    def serve_styles_css() -> Response:
        return Response(
            (frontend_static_dir / "styles.css").read_text(encoding="utf-8"),
            media_type="text/css",
        )

    app.mount("/", StaticFiles(directory=str(frontend_static_dir), html=True), name="frontend")
