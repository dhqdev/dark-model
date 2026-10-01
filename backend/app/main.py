"""Aplicação FastAPI: API em /api e o frontend compilado servido na raiz."""

from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .api import assets, auth, channels, dashboard, jobs, projects, scenes, settings, system, thumbnails, usage
from .config import BACKEND_DIR, get_settings
from .db import init_engine

log = logging.getLogger("dark_model")

MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
CSP = (
    "default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; style-src 'self' 'unsafe-inline'; "
    "font-src 'self' data:; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'"
)


def _frontend_dir() -> Path | None:
    s = get_settings()
    candidates = [s.frontend_dist] if s.frontend_dist else []
    candidates.append(BACKEND_DIR.parent / "frontend" / "dist")
    for c in candidates:
        if c and (c / "index.html").exists():
            return c
    return None


def _start_background() -> None:
    s = get_settings()
    if s.embedded_worker:
        from .jobs.worker import Worker

        worker = Worker()
        worker.start_background()
    if s.openrouter_configured:
        def warm() -> None:
            from . import catalog

            try:
                for key in catalog.KINDS.values():
                    catalog.get(key)
            except Exception as exc:  # noqa: BLE001
                log.warning("não foi possível carregar o catálogo da OpenRouter: %s", exc)

        threading.Thread(target=warm, name="catalog-warmup", daemon=True).start()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_engine()
    if not get_settings().credentials_configured:
        log.error("APP_USERNAME/APP_PASSWORD não definidos: o login ficará desativado.")
    if app.state.background:
        _start_background()
    yield


def create_app(*, background: bool = True) -> FastAPI:
    s = get_settings()
    logging.basicConfig(level=s.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    app = FastAPI(
        title="Dark Model API", version=__version__, lifespan=lifespan,
        docs_url=None if s.is_production else "/api/docs",
        redoc_url=None, openapi_url=None if s.is_production else "/api/openapi.json",
    )
    app.state.background = background

    @app.middleware("http")
    async def guard(request: Request, call_next):
        path = request.url.path
        if path.startswith("/api/") and request.method in MUTATING and request.headers.get("x-requested-with") != "dark-model":
            return JSONResponse({"detail": "Requisição bloqueada (proteção CSRF)."}, status_code=403)
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("X-Frame-Options", "DENY")
        if not path.startswith("/api/"):
            response.headers.setdefault("Content-Security-Policy", CSP)
        return response

    for r in (system, auth, dashboard, channels, projects, scenes, thumbnails, assets, jobs, usage, settings):
        app.include_router(r.router, prefix="/api")

    @app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
    def api_not_found(rest: str) -> JSONResponse:
        return JSONResponse({"detail": "Rota não encontrada"}, status_code=404)

    dist = _frontend_dir()
    if dist is not None:
        if (dist / "assets").exists():
            app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
        def spa(path: str):
            target = (dist / path).resolve()
            if path and target.is_file() and dist.resolve() in target.parents:
                return FileResponse(target)
            return FileResponse(dist / "index.html", headers={"Cache-Control": "no-cache"})

    return app


app = create_app()
