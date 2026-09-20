"""MineIntel AI — FastAPI application entrypoint."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import init_db
from app.routes import api_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    try:
        init_db()
        print(f"[MineIntel] Database ready ({'sqlite' if settings.use_sqlite else 'postgresql'})")
    except Exception as exc:  # noqa: BLE001
        print(f"[MineIntel] DB init skipped/failed (demo still works): {exc}")
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        description=(
            "AI-Powered Mining Document Intelligence & Reporting Platform "
            "(Smart India Hackathon SIH26023)"
        ),
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router)
    return app


app = create_app()
