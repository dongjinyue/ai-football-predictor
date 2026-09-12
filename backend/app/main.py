from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI

from app.config import load_settings
from app.imports.downloader import FootballDataDownloader
from app.imports.parser import parse_football_data_csv
from app.imports.repository import ImportRepository
from app.imports.router import create_import_router
from app.imports.service import ImportService
from app.storage import get_database_status, initialize_database


def resolve_database_path(database_path: Path | None = None) -> Path:
    if database_path is not None:
        return database_path

    return load_settings().database_path


def create_app(
    database_path: Path | None = None,
    import_service: ImportService | None = None,
    import_repository: ImportRepository | None = None,
) -> FastAPI:
    resolved_database_path = resolve_database_path(database_path)
    settings = load_settings()
    repository = import_repository or ImportRepository(resolved_database_path)
    http_client: httpx.Client | None = None

    if import_service is None:
        # 客户端属于应用生命周期：启动后复用，关闭时释放连接池。
        http_client = httpx.Client()
        downloader = FootballDataDownloader(http_client, settings.football_data_raw_path)
        service = ImportService(downloader, parse_football_data_csv, repository)
    else:
        service = import_service

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        initialize_database(resolved_database_path)
        try:
            yield
        finally:
            if http_client is not None:
                http_client.close()

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

    application.include_router(create_import_router(service, repository), prefix="/api/data")

    return application


app = create_app()
