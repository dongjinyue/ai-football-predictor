from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from app.config import load_settings
from app.storage import get_database_status, initialize_database


def resolve_database_path(database_path: Path | None = None) -> Path:
    if database_path is not None:
        return database_path

    return load_settings().database_path


def create_app(database_path: Path | None = None) -> FastAPI:
    resolved_database_path = resolve_database_path(database_path)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        initialize_database(resolved_database_path)
        yield

    application = FastAPI(
        title="AI Football Predictor API",
        lifespan=lifespan,
    )

    @application.get("/api/health")
    def health_check() -> dict[str, str]:
        return {
            "status": "ok",
            "service": "ai-football-predictor-api",
        }

    @application.get("/api/database/status")
    def database_status() -> dict[str, str | int]:
        status = get_database_status(resolved_database_path)
        return {
            "status": "ready" if status.ready else "not_ready",
            "engine": status.engine,
            "schema_version": status.schema_version,
            "table_count": status.table_count,
        }

    return application


app = create_app()
