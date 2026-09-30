# Creates the FastAPI application, mounts static assets, and registers routers.
from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.core.config import settings
from app.core.db import engine
from app.routers import __path__ as router_path

app = FastAPI(
    title="Spolužáci",
    docs_url=None if settings.is_prod else "/docs",
    redoc_url=None if settings.is_prod else "/redoc",
    openapi_url=None if settings.is_prod else "/openapi.json",
)
static_dir = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.middleware("http")
async def prevent_private_page_caching(request: Request, call_next):
    response = await call_next(request)
    user = getattr(request.state, "user", None)
    if user is not None and response.headers.get("content-type", "").startswith("text/html"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/healthz", include_in_schema=False)
def healthz() -> Response:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        return PlainTextResponse("unhealthy", status_code=503)
    return PlainTextResponse("ok")


for module_info in sorted(pkgutil.iter_modules(router_path), key=lambda item: item.name):
    module = importlib.import_module(f"app.routers.{module_info.name}")
    app.include_router(module.router)
    setup = getattr(module, "setup", None)
    if setup is not None:
        setup(app)


@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    if request.headers.get("HX-Request") == "true" or "text/html" not in request.headers.get("accept", "text/html"):
        return PlainTextResponse("Nenalezeno", status_code=404)
    from app.core.templates import render

    return render(request, "errors/404.html", status_code=404)


@app.exception_handler(500)
async def internal_error_handler(request: Request, exc):
    if request.headers.get("HX-Request") == "true" or "text/html" not in request.headers.get("accept", "text/html"):
        return PlainTextResponse("Interní chyba serveru", status_code=500)
    from app.core.templates import render

    return render(request, "errors/500.html", status_code=500)