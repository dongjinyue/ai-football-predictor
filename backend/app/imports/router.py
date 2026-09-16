"""历史数据导入 API：校验公开请求范围并只返回可安全展示的摘要。"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Literal, Protocol

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from app.imports.catalog import (
    CALENDAR_YEAR,
    COMPETITIONS,
    FOOTBALL_DATA_URL_TEMPLATE,
    SPLIT_YEAR,
    build_default_requests,
)
from app.imports.models import (
    HistoricalMatchView,
    ImportRequestScope,
    ImportRunAudit,
    ImportRunResult,
    MatchPage,
    MatchQuery,
    SourceFile,
)
from app.imports.service import ImportServiceError


logger = logging.getLogger(__name__)
_COMPETITION_BY_CODE = {item[0]: item for item in COMPETITIONS}


class _ImportService(Protocol):
    def run(self, requests: tuple[SourceFile, ...]) -> ImportRunResult: ...


class _ImportRepository(Protocol):
    def latest_run(self) -> ImportRunAudit | None: ...

    def data_summary(self) -> dict[str, object]: ...

    def list_matches(self, query: MatchQuery) -> MatchPage: ...


class ImportRequest(BaseModel):
    """客户端可选的精确导入范围；空对象代表默认全量范围。"""

    model_config = ConfigDict(extra="forbid")

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


class MarketOutcomeResponse(BaseModel):
    """一个市场结果及其十进制赔率。"""

    outcome_code: str
    odds: float


class MatchMarketResponse(BaseModel):
    """比赛列表中可安全展示的 closing（收盘）赔率市场。"""

    market_type: str
    stage: str
    time_precision: str
    source: str
    provider: str
    captured_at: datetime
    available_at: datetime
    line: float | None
    outcomes: tuple[MarketOutcomeResponse, ...]


class HistoricalMatchResponse(BaseModel):
    """历史比赛浏览器所需的稳定比赛字段。"""

    id: str
    competition_code: str
    competition_name: str
    season: str
    kickoff_at: datetime
    home_team: str
    away_team: str
    half_time_home_score: int | None
    half_time_away_score: int | None
    home_score: int | None
    away_score: int | None
    markets: tuple[MatchMarketResponse, ...]


class FilterOptionResponse(BaseModel):
    """当前数据库可用的来源联赛代码和赛季筛选项。"""

    competitions: tuple[str, ...]
    seasons: tuple[str, ...]


class MatchPageResponse(BaseModel):
    """历史比赛的分页 HTTP（超文本传输协议）响应。"""

    page: int
    page_size: int
    total_items: int
    total_pages: int
    filters: FilterOptionResponse
    items: tuple[HistoricalMatchResponse, ...]


def create_import_router(
    service: _ImportService | None = None,
    repository: _ImportRepository | None = None,
) -> APIRouter:
    """创建路由；显式依赖优先，未传入时才在请求期读取应用状态。"""
    router = APIRouter()

    @router.post("/import", response_model=ImportRunResponse)
    def import_data(payload: ImportRequest, request: Request) -> ImportRunResponse:
        requests = _requests_for_payload(payload)
        try:
            resolved_service = service if service is not None else request.app.state.import_service
            result = resolved_service.run(requests)
        except HTTPException:
            raise
        except ImportServiceError as error:
            if error.code == "import_in_progress":
                raise HTTPException(status_code=409, detail=error.code) from None
            raise HTTPException(status_code=422, detail=error.code) from None
        except Exception:
            # 日志保留给服务端诊断；HTTP 响应不能包含路径、原始 CSV 或堆栈。
            logger.exception("历史导入 API 出现未预期异常")
            raise HTTPException(status_code=500, detail="internal_error") from None
        return _run_response(result)

    @router.get("/imports/latest", response_model=LatestRunResponse)
    def latest_import(request: Request) -> LatestRunResponse:
        try:
            resolved_repository = (
                repository if repository is not None else request.app.state.import_repository
            )
            result = resolved_repository.latest_run()
        except Exception:
            logger.exception("读取最近历史导入记录失败")
            raise HTTPException(status_code=500, detail="internal_error") from None
        return LatestRunResponse(latest_run=_latest_run_response(result) if result else None)

    @router.get("/summary", response_model=DataSummaryResponse)
    def data_summary(request: Request) -> DataSummaryResponse:
        try:
            resolved_repository = (
                repository if repository is not None else request.app.state.import_repository
            )
            return DataSummaryResponse.model_validate(resolved_repository.data_summary())
        except Exception:
            logger.exception("读取历史数据摘要失败")
            raise HTTPException(status_code=500, detail="internal_error") from None

    @router.get("/matches", response_model=MatchPageResponse)
    def list_matches(
        request: Request,
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=20, ge=1, le=100),
        competition: str | None = None,
        season: str | None = None,
        team: str | None = None,
    ) -> MatchPageResponse:
        """按安全分页与规范化筛选读取历史比赛，不暴露底层数据库异常。"""
        query = MatchQuery(
            page=page,
            page_size=page_size,
            competition=_optional_filter(competition),
            season=_optional_filter(season),
            team=_optional_filter(team),
        )
        try:
            resolved_repository = (
                repository if repository is not None else request.app.state.import_repository
            )
            result = resolved_repository.list_matches(query)
        except Exception:
            logger.exception("读取历史比赛分页失败")
            raise HTTPException(status_code=500, detail="internal_error") from None
        return _match_page_response(result, page_size=query.page_size)

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


def _optional_filter(value: str | None) -> str | None:
    """去除筛选条件首尾空格；空字符串统一表示未筛选。"""
    return value.strip() or None if value is not None else None


def _match_page_response(page: MatchPage, page_size: int) -> MatchPageResponse:
    """将冻结仓储视图映射为不会泄露数据库行对象的 HTTP 响应。"""
    return MatchPageResponse(
        page=page.page,
        page_size=page_size,
        total_items=page.total_items,
        total_pages=page.total_pages,
        filters=FilterOptionResponse(
            competitions=page.filters.competitions,
            seasons=page.filters.seasons,
        ),
        items=tuple(_historical_match_response(item) for item in page.items),
    )


def _historical_match_response(match: HistoricalMatchView) -> HistoricalMatchResponse:
    """显式公开比赛与赔率字段，避免依赖 Pydantic 的隐式对象转换。"""
    return HistoricalMatchResponse(
        id=match.id,
        competition_code=match.competition_code,
        competition_name=match.competition_name,
        season=match.season,
        kickoff_at=match.kickoff_at,
        home_team=match.home_team,
        away_team=match.away_team,
        half_time_home_score=match.half_time_home_score,
        half_time_away_score=match.half_time_away_score,
        home_score=match.home_score,
        away_score=match.away_score,
        markets=tuple(
            MatchMarketResponse(
                market_type=market.market_type,
                stage=market.stage,
                time_precision=market.time_precision,
                source=market.source,
                provider=market.provider,
                captured_at=market.captured_at,
                available_at=market.available_at,
                line=market.line,
                outcomes=tuple(
                    MarketOutcomeResponse(outcome_code=outcome_code, odds=odds)
                    for outcome_code, odds in market.outcomes
                ),
            )
            for market in match.markets
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
