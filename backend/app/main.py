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

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        """只在应用启动后创建默认依赖，并在任意启动异常时释放连接池。"""
        http_client: httpx.Client | None = None
        try:
            # fake（替身）服务不触发真实数据库或网络依赖的构造。
            if import_service is None:
                http_client = httpx.Client()
            # service 与 repository 均已注入时，该应用可完全离线运行，不触碰默认数据库。
            if import_service is None or import_repository is None:
                initialize_database(resolved_database_path)
            repository = import_repository or ImportRepository(resolved_database_path)
            service = import_service
            if service is None:
                settings = load_settings()
                downloader = FootballDataDownloader(http_client, settings.football_data_raw_path)
                service = ImportService(downloader, parse_football_data_csv, repository)
            application.state.import_repository = repository
            application.state.import_service = service
            yield
        finally:
            if http_client is not None:
                http_client.close()

    application = FastAPI(
        title="AI Football Predictor API",
        lifespan=lifespan,
    )
    # 注入的离线依赖可在不进入 lifespan 的 API 测试中直接使用；默认依赖保持空值。
    application.state.import_repository = import_repository
    application.state.import_service = import_service

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

    application.include_router(create_import_router(), prefix="/api/data")

    return application


app = create_app()
