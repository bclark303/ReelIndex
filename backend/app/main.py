from __future__ import annotations

import logging
from datetime import datetime, timezone
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select

from app.api.inventory_records import router as inventory_records_router
from app.api.movies import router as movies_router
from app.api.probes import router as probes_router
from app.api.scans import router as scans_router
from app.api.sources import router as sources_router
from app.api.system import router as system_router
from app.core.config import settings
from app.core.database import SessionLocal, init_db
from app.models import ScanRun
from app.services.demo import seed_demo
from app.services.scheduler import scan_scheduler
from app.version import __version__

logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO), format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def recover_interrupted_scans() -> None:
    """Close scan rows left active by an application restart.

    Ordinary scan worker state is in memory. Deep-analysis manifests are stored
    separately and remain resumable from the Sources page after this row is
    marked interrupted.
    """
    with SessionLocal() as db:
        runs = db.scalars(
            select(ScanRun).where(ScanRun.status.in_(("queued", "running", "cancelling")))
        ).all()
        if not runs:
            return
        now = datetime.now(timezone.utc)
        for run in runs:
            run.status = "interrupted"
            run.current_item = "Interrupted by application restart"
            run.completed_at = now
        db.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    recover_interrupted_scans()
    seed_demo()
    scan_scheduler.start()
    yield
    scan_scheduler.shutdown()


app = FastAPI(title=settings.app_name, version=__version__, lifespan=lifespan)


@app.middleware("http")
async def prevent_stale_ui_assets(request: Request, call_next):
    response = await call_next(request)
    if request.url.path in {"/", "/index.html", "/app.js", "/record-delete.js", "/styles.css", "/windows.css", "/manifest.webmanifest"}:
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(system_router, prefix=settings.api_prefix)
app.include_router(sources_router, prefix=settings.api_prefix)
app.include_router(scans_router, prefix=settings.api_prefix)
app.include_router(movies_router, prefix=settings.api_prefix)
app.include_router(inventory_records_router, prefix=settings.api_prefix)
app.include_router(probes_router, prefix=settings.api_prefix)


if settings.static_dir and settings.static_dir.exists():
    # Mounted last so /api and FastAPI's documentation routes retain priority.
    app.mount("/", StaticFiles(directory=str(settings.static_dir), html=True), name="frontend")
else:
    @app.get("/")
    def root():
        return {"name": settings.app_name, "api": settings.api_prefix, "docs": "/docs"}
