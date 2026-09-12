"""历史数据导入 API：校验公开请求范围并只返回可安全展示的摘要。"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Literal, Protocol

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.imports.catalog import (
    CALENDAR_YEAR,
    COMPETITIONS,
    FOOTBALL_DATA_URL_TEMPLATE,
    SPLIT_YEAR,
    build_default_requests,
)
from app.imports.models import ImportRequestScope, ImportRunAudit, ImportRunResult, SourceFile


logger = logging.getLogger(__name__)
_COMPETITION_BY_CODE = {item[0]: item for item in COMPETITIONS}


class _ImportService(Protocol):
    def run(self, requests: tuple[SourceFile, ...]) -> ImportRunResult: ...


class _ImportRepository(Protocol):
    def latest_run(self) -> ImportRunAudit | None: ...

    def data_summary(self) -> dict[str, object]: ...


class ImportRequest(BaseModel):
    """客户端可选的精确导入范围；空对象代表默认全量范围。"""

    competition_codes: list[str] = Field(default_factory=list, max_length=len(COMPETITIONS))
    seasons: list[str] = Field(default_factory=list, max_length=5)


class ImportRunResponse(BaseModel):
    run_id: str
    status: Literal["running", "completed", "completed_with_errors", "failed"]
    requested_files: int
    completed_files: int
    failed_files: int
    imported_matches: int
    skipped_rows: int
    errors: list[str]


class RequestedScopeResponse(BaseModel):
    """不可变的公开请求范围，不泄露下载 URL（地址）或本机路径。"""

    model_config = ConfigDict(frozen=True)

    competition_code: str
    season: str


class LatestImportRunResponse(ImportRunResponse):
    source: str
    started_at: datetime
    finished_at: datetime | None
    requested_scope: tuple[RequestedScopeResponse, ...]


class LatestRunResponse(BaseModel):
    latest_run: LatestImportRunResponse | None


class DataSummaryResponse(BaseModel):
    competitions: int
    teams: int
    matches: int
    market_snapshots: int
    market_outcomes: int
    latest_kickoff_at: str | None
    latest_successful_import_at: str | None


def create_import_router() -> APIRouter:
    """创建无全局状态的路由，依赖由应用工厂或测试显式提供。"""
    router = APIRouter()

    @router.post("/import", response_model=ImportRunResponse)
    def import_data(payload: ImportRequest, request: Request) -> ImportRunResponse:
        requests = _requests_for_payload(payload)
        try:
            service: _ImportService = request.app.state.import_service
            result = service.run(requests)
        except HTTPException:
            raise
        except Exception:
            # 日志保留给服务端诊断；HTTP 响应不能包含路径、原始 CSV 或堆栈。
            logger.exception("历史导入 API 出现未预期异常")
            raise HTTPException(status_code=500, detail="internal_error") from None
        return _run_response(result)

    @router.get("/imports/latest", response_model=LatestRunResponse)
    def latest_import(request: Request) -> LatestRunResponse:
        try:
            repository: _ImportRepository = request.app.state.import_repository
            result = repository.latest_run()
        except Exception:
            logger.exception("读取最近历史导入记录失败")
            raise HTTPException(status_code=500, detail="internal_error") from None
        return LatestRunResponse(latest_run=_latest_run_response(result) if result else None)

    @router.get("/summary", response_model=DataSummaryResponse)
    def data_summary(request: Request) -> DataSummaryResponse:
        try:
            repository: _ImportRepository = request.app.state.import_repository
            return DataSummaryResponse.model_validate(repository.data_summary())
        except Exception:
            logger.exception("读取历史数据摘要失败")
            raise HTTPException(status_code=500, detail="internal_error") from None

    return router


def _run_response(result: ImportRunResult) -> ImportRunResponse:
    return ImportRunResponse(
        run_id=result.run_id,
        status=result.status,
        requested_files=result.requested_files,
        completed_files=result.completed_files,
        failed_files=result.failed_files,
        imported_matches=result.imported_matches,
        skipped_rows=result.skipped_rows,
        errors=list(result.errors),
    )


def _latest_run_response(audit: ImportRunAudit) -> LatestImportRunResponse:
    """从不可变审计对象创建明确的最新导入 API 响应。"""
    return LatestImportRunResponse(
        **_run_response(audit.result).model_dump(),
        source=audit.source,
        started_at=audit.started_at,
        finished_at=audit.finished_at,
        requested_scope=tuple(
            RequestedScopeResponse(competition_code=item.competition_code, season=item.season)
            for item in audit.requested_scope
        ),
    )


def _requests_for_payload(payload: ImportRequest) -> tuple[SourceFile, ...]:
    """将已验证范围映射为目录项，绝不接受任意 URL 或未知联赛。"""
    if not payload.competition_codes and not payload.seasons:
        return build_default_requests(date.today())
    if len(set(payload.competition_codes)) != len(payload.competition_codes):
        _invalid_scope("duplicate_competition_code")
    if len(set(payload.seasons)) != len(payload.seasons):
        _invalid_scope("duplicate_season")

    codes = tuple(payload.competition_codes) or tuple(_COMPETITION_BY_CODE)
    for code in codes:
        if code not in _COMPETITION_BY_CODE:
            _invalid_scope("unknown_competition_code")

    default_by_code: dict[str, set[str]] = {}
    for source_file in build_default_requests(date.today()):
        default_by_code.setdefault(source_file.competition_code, set()).add(source_file.season)

    requests: list[SourceFile] = []
    for code in codes:
        _, name, country_code, _season_style = _COMPETITION_BY_CODE[code]
        seasons = tuple(payload.seasons) or default_by_code[code]
        for season in seasons:
            # 必须与目录实际生成的“已完成且受支持”赛季精确一致，不能只校验 YYZZ 外观。
            if season not in default_by_code[code]:
                _invalid_scope("unknown_season")
            requests.append(
                SourceFile(
                    source="football_data",
                    competition_code=code,
                    competition_name=name,
                    country_code=country_code,
                    season=season,
                    url=FOOTBALL_DATA_URL_TEMPLATE.format(season=season, code=code),
                )
            )
    return tuple(requests)


def _invalid_scope(code: str) -> None:
    raise HTTPException(status_code=422, detail=code)
