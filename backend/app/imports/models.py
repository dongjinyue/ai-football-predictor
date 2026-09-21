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
    source_scope: str = "seasonal"
    start_year: int | None = None
    end_year: int | None = None
    season_style: str | None = None


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
    # 合并源文件必须保留每一行自己的数据库赛季；普通文件为空时由来源文件补足。
    season: str | None = None


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
class ImportProgress:
    """导入任务对页面公开的单文件进度；不携带本机路径或异常原文。"""

    completed_files: int
    failed_files: int
    imported_matches: int
    skipped_rows: int
    current_competition_code: str | None = None
    current_season: str | None = None


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
class DataAuditMarketCoverage:
    """一个联赛赛季中单类市场的覆盖与时间语义统计。"""

    market_type: str
    snapshot_count: int
    match_count: int
    pre_match_snapshot_count: int
    pre_match_match_count: int
    kickoff_bound_snapshot_count: int
    kickoff_bound_match_count: int
    post_kickoff_snapshot_count: int


@dataclass(frozen=True)
class DataAuditScope:
    """一个经请求的联赛赛季的赛果、派生字段和盘口审计结果。"""

    competition_code: str
    competition_name: str
    country_code: str
    season: str
    match_count: int
    complete_full_time_matches: int
    complete_half_time_matches: int
    missing_half_time_matches: int
    half_time_result_matches: int
    total_goals_matches: int
    label_ready_matches: int
    pre_match_market_matches: int
    kickoff_bound_market_matches: int
    post_kickoff_market_matches: int
    markets: tuple[DataAuditMarketCoverage, ...]


@dataclass(frozen=True)
class DataAuditSummary:
    """训练前审计的全局汇总；赔率时间口径单独统计，避免数据泄漏。"""

    catalog_competitions: int
    imported_competitions: int
    requested_files: int
    files_with_matches: int
    missing_files: int
    total_matches: int
    complete_full_time_matches: int
    complete_half_time_matches: int
    missing_half_time_matches: int
    half_time_result_matches: int
    total_goals_matches: int
    label_ready_matches: int
    pre_match_market_matches: int
    kickoff_bound_market_matches: int
    post_kickoff_market_matches: int


@dataclass(frozen=True)
class DataAuditReport:
    """一个时间范围内全部请求联赛赛季的训练前审计报告。"""

    start_year: int
    end_year: int
    requested_files: int
    summary: DataAuditSummary
    scopes: tuple[DataAuditScope, ...]


@dataclass(frozen=True)
class MatchQuery:
    """历史比赛列表的分页和可选筛选条件，联赛使用来源代码。"""

    page: int = 1
    page_size: int = 20
    source: str | None = None
    competition: str | None = None
    season: str | None = None
    team: str | None = None


@dataclass(frozen=True)
class MatchMarketView:
    """列表页展示的一个赔率市场；赔率选项不泄露数据库行对象。"""

    market_type: str
    stage: str
    # 明确赔率时间语义，供界面提示 kickoff_bound 不能用于开球前回测。
    time_precision: str
    source: str
    provider: str
    captured_at: datetime
    available_at: datetime
    line: float | None
    outcomes: tuple[tuple[str, float], ...]


@dataclass(frozen=True)
class HistoricalMatchView:
    """历史比赛及其收盘赔率市场的不可变展示视图。"""

    id: str
    kickoff_at: datetime
    competition_code: str
    competition_name: str
    # 保留既有字段，避免仓储调用方在迁移期间中断；新 HTTP API 使用上方明确字段。
    competition: str
    season: str
    home_team: str
    away_team: str
    half_time_home_score: int | None
    half_time_away_score: int | None
    home_score: int | None
    away_score: int | None
    markets: tuple[MatchMarketView, ...]
    # date_only 的 kickoff_at 仅为排序锚点，界面不得显示其时分秒。
    kickoff_time_precision: str = "exact"


@dataclass(frozen=True)
class MarketHistorySnapshotView:
    """中国竞彩彩票在一个官方发布时间发布的一组赔率。"""

    captured_at: datetime
    available_at: datetime
    outcomes: tuple[tuple[str, float], ...]


@dataclass(frozen=True)
class MarketHistoryGroupView:
    """同一玩法和盘口的完整赔率时间线。"""

    market_type: str
    line: float | None
    source: str
    provider: str
    stage: str
    time_precision: str
    outcome_codes: tuple[str, ...]
    snapshots: tuple[MarketHistorySnapshotView, ...]


@dataclass(frozen=True)
class MatchMarketHistoryView:
    """单场比赛及其所有已采集的中国竞彩彩票赔率记录。"""

    id: str
    competition_code: str
    competition_name: str
    season: str
    kickoff_at: datetime
    kickoff_time_precision: str
    home_team: str
    away_team: str
    half_time_home_score: int | None
    half_time_away_score: int | None
    home_score: int | None
    away_score: int | None
    markets: tuple[MarketHistoryGroupView, ...]


@dataclass(frozen=True)
class MatchFilterOptions:
    """历史比赛浏览器可选的来源联赛代码与赛季，均为稳定排序的文本。"""

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
