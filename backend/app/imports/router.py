"""历史数据导入 API：校验公开请求范围并只返回可安全展示的摘要。"""

from __future__ import annotations

import logging
from datetime import date
from typing import Protocol

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.imports.catalog import (
    CALENDAR_YEAR,
    COMPETITIONS,
    FOOTBALL_DATA_URL_TEMPLATE,
    SPLIT_YEAR,
    build_default_requests,
)
from app.imports.models import ImportRunResult, SourceFile


logger = logging.getLogger(__name__)
_COMPETITION_BY_CODE = {item[0]: item for item in COMPETITIONS}


class _ImportService(Protocol):
    def run(self, requests: tuple[SourceFile, ...]) -> ImportRunResult: ...


class _ImportRepository(Protocol):
    def latest_run(self) -> ImportRunResult | None: ...

    def data_summary(self) -> dict[str, object]: ...


class ImportRequest(BaseModel):
    """客户端可选的精确导入范围；空对象代表默认全量范围。"""

    competition_codes: list[str] = Field(default_factory=list, max_length=len(COMPETITIONS))
    seasons: list[str] = Field(default_factory=list, max_length=5)


class ImportRunResponse(BaseModel):
    run_id: str
    status: str
    requested_files: int
    completed_files: int
    failed_files: int
    imported_matches: int
    skipped_rows: int
    errors: list[str]


class LatestRunResponse(BaseModel):
    latest_run: ImportRunResponse | None


class DataSummaryResponse(BaseModel):
    competitions: int
    teams: int
    matches: int
    market_snapshots: int
    market_outcomes: int
    latest_kickoff_at: str | None
    latest_successful_import_at: str | None


def create_import_router(service: _ImportService, repository: _ImportRepository) -> APIRouter:
    """创建无全局状态的路由，依赖由应用工厂或测试显式提供。"""
    router = APIRouter()

    @router.post("/import", response_model=ImportRunResponse)
    def import_data(payload: ImportRequest) -> ImportRunResponse:
        requests = _requests_for_payload(payload)
        try:
            result = service.run(requests)
        except HTTPException:
            raise
        except Exception:
            # 日志保留给服务端诊断；HTTP 响应不能包含路径、原始 CSV 或堆栈。
            logger.exception("历史导入 API 出现未预期异常")
            raise HTTPException(status_code=500, detail="internal_error") from None
        return _run_response(result)

    @router.get("/imports/latest", response_model=LatestRunResponse)
    def latest_import() -> LatestRunResponse:
        try:
            result = repository.latest_run()
        except Exception:
            logger.exception("读取最近历史导入记录失败")
            raise HTTPException(status_code=500, detail="internal_error") from None
        return LatestRunResponse(latest_run=_run_response(result) if result else None)

    @router.get("/summary", response_model=DataSummaryResponse)
    def data_summary() -> DataSummaryResponse:
        try:
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

    default_by_code: dict[str, tuple[str, ...]] = {}
    for source_file in build_default_requests(date.today()):
        default_by_code.setdefault(source_file.competition_code, ())
        default_by_code[source_file.competition_code] += (source_file.season,)

    requests: list[SourceFile] = []
    for code in codes:
        _, name, country_code, season_style = _COMPETITION_BY_CODE[code]
        seasons = tuple(payload.seasons) or default_by_code[code]
        for season in seasons:
            if not _is_supported_season(season, season_style):
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


def _is_supported_season(season: str, season_style: str) -> bool:
    """按目录定义的赛季格式校验，并拒绝未来或明显无效的年份。"""
    today = date.today()
    if season_style == SPLIT_YEAR:
        if len(season) != 4 or not season.isdigit():
            return False
        start_year, end_year = int(season[:2]), int(season[2:])
        return 0 <= start_year <= 99 and end_year == (start_year + 1) % 100 and 2000 <= 2000 + end_year <= today.year
    if season_style == CALENDAR_YEAR:
        return season.isdigit() and len(season) == 4 and 2000 <= int(season) < today.year
    return False


def _invalid_scope(code: str) -> None:
    raise HTTPException(status_code=422, detail=code)
