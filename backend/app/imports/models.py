"""导入流程各层共享的不可变领域记录。"""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class SourceFile:
    """一个可下载的、来源明确的联赛赛季文件。"""

    source: str
    competition_code: str
    competition_name: str
    country_code: str
    season: str
    url: str


@dataclass(frozen=True)
class MarketRecord:
    """一场比赛中同一提供方、同一玩法的赔率快照。"""

    provider: str
    source: str
    market_type: str
    stage: str
    captured_at: datetime
    available_at: datetime
    time_precision: str
    line: float | None
    outcomes: tuple[tuple[str, float, str], ...]


@dataclass(frozen=True)
class MatchRecord:
    """CSV 一行解析出的比赛赛果及其可用市场。"""

    row_number: int
    source_match_id: str
    kickoff_at: datetime
    home_team: str
    away_team: str
    half_time_home_score: int | None
    half_time_away_score: int | None
    home_score: int
    away_score: int
    markets: tuple[MarketRecord, ...]


@dataclass(frozen=True)
class ParsedFile:
    """一个源文件的解析结果；错误使用元组以保持跨层接口稳定。"""

    matches: tuple[MatchRecord, ...]
    skipped_rows: int
    errors: tuple[str, ...]


@dataclass(frozen=True)
class FileImportResult:
    """一个源文件的导入统计和可安全展示的错误代码。"""

    file_id: str
    source_file: SourceFile
    status: str
    imported_matches: int
    skipped_rows: int
    errors: tuple[str, ...]


@dataclass(frozen=True)
class ImportRunResult:
    """一次多文件导入运行的汇总统计。"""

    run_id: str
    status: str
    requested_files: int
    completed_files: int
    failed_files: int
    imported_matches: int
    skipped_rows: int
    errors: tuple[str, ...]


@dataclass(frozen=True)
class ImportRequestScope:
    """最近一次导入中一个经审计的联赛赛季请求范围。"""

    competition_code: str
    season: str


@dataclass(frozen=True)
class ImportRunAudit:
    """最近一次导入的不可变审计视图，供 API 安全展示。"""

    result: ImportRunResult
    source: str
    started_at: datetime
    finished_at: datetime | None
    requested_scope: tuple[ImportRequestScope, ...]


@dataclass(frozen=True)
class MatchQuery:
    """历史比赛列表的分页和可选筛选条件。"""

    page: int = 1
    page_size: int = 20
    competition: str | None = None
    season: str | None = None
    team: str | None = None


@dataclass(frozen=True)
class MatchMarketView:
    """列表页展示的一个赔率市场；赔率选项不泄露数据库行对象。"""

    market_type: str
    stage: str
    line: float | None
    outcomes: tuple[tuple[str, float], ...]


@dataclass(frozen=True)
class HistoricalMatchView:
    """历史比赛及其收盘赔率市场的不可变展示视图。"""

    id: str
    kickoff_at: datetime
    competition: str
    season: str
    home_team: str
    away_team: str
    home_score: int | None
    away_score: int | None
    markets: tuple[MatchMarketView, ...]


@dataclass(frozen=True)
class MatchFilterOptions:
    """历史比赛浏览器可选的联赛与赛季，均为稳定排序的文本。"""

    competitions: tuple[str, ...]
    seasons: tuple[str, ...]


@dataclass(frozen=True)
class MatchPage:
    """一次历史比赛分页查询的完整结果。"""

    page: int
    total_items: int
    total_pages: int
    filters: MatchFilterOptions
    items: tuple[HistoricalMatchView, ...]
