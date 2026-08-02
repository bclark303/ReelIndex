from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.movies import router as movies_router
from app.api.scans import router as scans_router
from app.api.sources import router as sources_router
from app.api.system import router as system_router
from app.core.config import settings
from app.core.database import init_db
from app.services.demo import seed_demo
from app.services.scheduler import scan_scheduler

logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO), format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    seed_demo()
    scan_scheduler.start()
    yield
    scan_scheduler.shutdown()


app = FastAPI(title=settings.app_name, version="1.1.2", lifespan=lifespan)
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


if settings.static_dir and settings.static_dir.exists():
    # Mounted last so /api and FastAPI's documentation routes retain priority.
    app.mount("/", StaticFiles(directory=str(settings.static_dir), html=True), name="frontend")
else:
    @app.get("/")
    def root():
        return {"name": settings.app_name, "api": settings.api_prefix, "docs": "/docs"}
