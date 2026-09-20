"""中国竞彩采集器各层共享的不可变数据模型。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any


@dataclass(frozen=True)
class HttpPayload:
    """一次通过 HTTP 和来源业务状态双重校验的 JSON 响应。"""

    data: dict[str, Any]
    status_code: int
    fetched_at: datetime
    request_url: str


@dataclass(frozen=True)
class SportteryMatch:
    """比赛列表中的官方比赛身份、赛果与销售状态。"""

    match_id: int
    match_date: date
    match_number: str
    match_number_label: str
    league_id: int
    league_name: str
    league_abbreviation: str
    home_team_id: int
    home_team: str
    home_team_full_name: str
    away_team_id: int
    away_team: str
    away_team_full_name: str
    half_time_home_score: int | None
    half_time_away_score: int | None
    home_score: int | None
    away_score: int | None
    result: str | None
    handicap: float | None
    result_status: str
    pool_status: str


@dataclass(frozen=True)
class MatchPageRecord:
    """一页比赛及来源提供的完整分页信息。"""

    page_no: int
    page_size: int
    pages: int
    total: int
    matches: tuple[SportteryMatch, ...]
    rejected_matches: int = 0


@dataclass(frozen=True)
class BonusSnapshot:
    """一个官方更新时间下的完整玩法奖金快照。"""

    market_type: str
    captured_at: datetime
    line: float | None
    outcomes: tuple[tuple[str, float], ...]


@dataclass(frozen=True)
class FixedBonusRecord:
    """一场比赛的固定奖金历史及被拒绝快照数量。"""

    match_id: int
    league_id: int
    home_team_id: int
    away_team_id: int
    is_cancelled: bool
    snapshots: tuple[BonusSnapshot, ...]
    single_pools: tuple[tuple[str, bool], ...]
    rejected_snapshots: int
