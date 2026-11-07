"""FastAPI application factory."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .db import init_db
from .ingest.pipeline import seed_reference_data
from .settings import get

WEB_DIR = Path(__file__).resolve().parent / "web"


@asynccontextmanager
async def lifespan(app: FastAPI):
    conn = init_db()
    seed_reference_data(conn)
    conn.close()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title=get("app.title", "MUN Research Station"), lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")

    from .web import routes

    app.include_router(routes.router)
    return app


app = create_app()
