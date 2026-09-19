"""把中国竞彩官方 JSON 转换为经过校验的统一记录。"""

from __future__ import annotations

import math
import re
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.sporttery.models import (
    BonusSnapshot,
    FixedBonusRecord,
    MatchPageRecord,
    SportteryMatch,
)


SHANGHAI = ZoneInfo("Asia/Shanghai")
UTC = ZoneInfo("UTC")
_SCORE = re.compile(r"^(\d+):(\d+)$")

_MARKET_FIELDS: dict[str, tuple[str, dict[str, str]]] = {
    "hadList": (
        "match_result",
        {"h": "home", "d": "draw", "a": "away"},
    ),
    "hhadList": (
        "handicap_result",
        {"h": "home", "d": "draw", "a": "away"},
    ),
    "ttgList": (
        "total_goals",
        {**{f"s{number}": str(number) for number in range(7)}, "s7": "7_plus"},
    ),
    "hafuList": (
        "half_full",
        {
            "hh": "home_home", "hd": "home_draw", "ha": "home_away",
            "dh": "draw_home", "dd": "draw_draw", "da": "draw_away",
            "ah": "away_home", "ad": "away_draw", "aa": "away_away",
        },
    ),
}


class SportteryParseError(ValueError):
    """来源字段不符合已确认契约时使用的稳定错误。"""


def parse_match_page(payload: dict[str, Any]) -> MatchPageRecord:
    """解析比赛列表页；身份字段无效时拒绝整页，防止错误关联奖金。"""
    value = _object(payload.get("value"), "invalid_value")
    raw_matches = value.get("matchResult")
    if not isinstance(raw_matches, list):
        raise SportteryParseError("invalid_match_result")
    matches = tuple(_parse_match(_object(item, "invalid_match")) for item in raw_matches)
    page_no = _positive_int(value.get("pageNo"), "invalid_page_no")
    page_size = _positive_int(value.get("pageSize"), "invalid_page_size")
    pages = _nonnegative_int(value.get("pages"), "invalid_pages")
    total = _nonnegative_int(value.get("total"), "invalid_total")
    if page_no > max(pages, 1):
        raise SportteryParseError("page_out_of_range")
    return MatchPageRecord(page_no, page_size, pages, total, matches)


def parse_fixed_bonus(payload: dict[str, Any]) -> FixedBonusRecord:
    """解析五类奖金；单个坏快照被隔离，其余来源事实仍可使用。"""
    value = _object(payload.get("value"), "invalid_value")
    history = _object(value.get("oddsHistory"), "invalid_odds_history")
    match_id = _positive_int(history.get("matchId"), "invalid_match_id")
    league_id = _positive_int(history.get("leagueId"), "invalid_league_id")
    home_team_id = _positive_int(history.get("homeTeamId"), "invalid_home_team_id")
    away_team_id = _positive_int(history.get("awayTeamId"), "invalid_away_team_id")
    if home_team_id == away_team_id:
        raise SportteryParseError("home_away_same")

    snapshots: list[BonusSnapshot] = []
    rejected = 0
    for source_name, (market_type, fields) in _MARKET_FIELDS.items():
        items = history.get(source_name) or []
        if not isinstance(items, list):
            raise SportteryParseError(f"invalid_{source_name}")
        for item in items:
            try:
                snapshots.append(
                    _parse_market_snapshot(
                        _object(item, "invalid_snapshot"),
                        market_type,
                        fields,
                        requires_line=source_name == "hhadList",
                    )
                )
            except SportteryParseError:
                rejected += 1

    correct_scores = history.get("crsList") or []
    if not isinstance(correct_scores, list):
        raise SportteryParseError("invalid_crsList")
    score_fields = _correct_score_fields()
    for item in correct_scores:
        try:
            snapshots.append(
                _parse_market_snapshot(
                    _object(item, "invalid_snapshot"),
                    "correct_score",
                    score_fields,
                    requires_line=False,
                )
            )
        except SportteryParseError:
            rejected += 1

    raw_single = history.get("singleList") or []
    if not isinstance(raw_single, list):
        raise SportteryParseError("invalid_single_list")
    single_pools = tuple(
        (_required_text(item, "poolCode"), bool(_nonnegative_int(item.get("single"), "invalid_single")))
        for item in (_object(raw, "invalid_single_pool") for raw in raw_single)
    )
    snapshots.sort(key=lambda item: (item.captured_at, item.market_type, item.line or 0.0))
    return FixedBonusRecord(
        match_id=match_id,
        league_id=league_id,
        home_team_id=home_team_id,
        away_team_id=away_team_id,
        is_cancelled=bool(_nonnegative_int(value.get("isCancel", 0), "invalid_cancel")),
        snapshots=tuple(snapshots),
        single_pools=single_pools,
        rejected_snapshots=rejected,
    )


def _parse_match(row: dict[str, Any]) -> SportteryMatch:
    match_id = _positive_int(row.get("matchId"), "invalid_match_id")
    home_team_id = _positive_int(row.get("homeTeamId"), "invalid_home_team_id")
    away_team_id = _positive_int(row.get("awayTeamId"), "invalid_away_team_id")
    home_team = _required_text(row, "homeTeam")
    away_team = _required_text(row, "awayTeam")
    if home_team_id == away_team_id or home_team == away_team:
        raise SportteryParseError("home_away_same")
    half_home, half_away = _optional_score(row.get("sectionsNo1"))
    home_score, away_score = _optional_score(row.get("sectionsNo999"))
    raw_result = str(row.get("winFlag") or "").strip().upper()
    result = {"H": "home", "D": "draw", "A": "away", "": None}.get(raw_result)
    if raw_result and result is None:
        raise SportteryParseError("invalid_result")
    if home_score is not None:
        expected = "home" if home_score > away_score else "away" if home_score < away_score else "draw"
        if result is not None and result != expected:
            raise SportteryParseError("result_score_mismatch")
    return SportteryMatch(
        match_id=match_id,
        match_date=_date(row.get("matchDate")),
        match_number=_required_text(row, "matchNum"),
        match_number_label=_required_text(row, "matchNumStr"),
        league_id=_positive_int(row.get("leagueId"), "invalid_league_id"),
        league_name=_required_text(row, "leagueName"),
        league_abbreviation=_required_text(row, "leagueNameAbbr"),
        home_team_id=home_team_id,
        home_team=home_team,
        home_team_full_name=str(row.get("allHomeTeam") or home_team).strip(),
        away_team_id=away_team_id,
        away_team=away_team,
        away_team_full_name=str(row.get("allAwayTeam") or away_team).strip(),
        half_time_home_score=half_home,
        half_time_away_score=half_away,
        home_score=home_score,
        away_score=away_score,
        result=result,
        handicap=_optional_float(row.get("goalLine")),
        result_status=str(row.get("matchResultStatus") or "").strip(),
        pool_status=str(row.get("poolStatus") or "").strip(),
    )


def _parse_market_snapshot(
    row: dict[str, Any],
    market_type: str,
    fields: dict[str, str],
    *,
    requires_line: bool,
) -> BonusSnapshot:
    outcomes = tuple((outcome, _positive_float(row.get(field))) for field, outcome in fields.items())
    line = _optional_float(row.get("goalLine"))
    if requires_line and line is None:
        raise SportteryParseError("missing_goal_line")
    return BonusSnapshot(
        market_type=market_type,
        captured_at=_timestamp(row.get("updateDate"), row.get("updateTime")),
        line=line if requires_line else None,
        outcomes=outcomes,
    )


def _correct_score_fields() -> dict[str, str]:
    fields: dict[str, str] = {}
    for home, away in (
        (1, 0), (2, 0), (2, 1), (3, 0), (3, 1), (3, 2),
        (4, 0), (4, 1), (4, 2), (5, 0), (5, 1), (5, 2),
        (0, 0), (1, 1), (2, 2), (3, 3),
        (0, 1), (0, 2), (1, 2), (0, 3), (1, 3), (2, 3),
        (0, 4), (1, 4), (2, 4), (0, 5), (1, 5), (2, 5),
    ):
        fields[f"s{home:02d}s{away:02d}"] = f"{home}_{away}"
    fields.update({"s-1sh": "other_home", "s-1sd": "other_draw", "s-1sa": "other_away"})
    return fields


def _timestamp(raw_date: Any, raw_time: Any) -> datetime:
    try:
        local = datetime.strptime(f"{raw_date} {raw_time}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=SHANGHAI)
    except (TypeError, ValueError) as error:
        raise SportteryParseError("invalid_update_time") from error
    return local.astimezone(UTC)


def _date(value: Any) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError as error:
        raise SportteryParseError("invalid_match_date") from error


def _optional_score(value: Any) -> tuple[int | None, int | None]:
    text = str(value or "").strip()
    if not text:
        return None, None
    match = _SCORE.fullmatch(text)
    if match is None:
        raise SportteryParseError("invalid_score")
    return int(match.group(1)), int(match.group(2))


def _required_text(row: dict[str, Any], field: str) -> str:
    value = str(row.get(field) or "").strip()
    if not value:
        raise SportteryParseError(f"missing_{field}")
    return value


def _object(value: Any, code: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SportteryParseError(code)
    return value


def _positive_int(value: Any, code: str) -> int:
    number = _nonnegative_int(value, code)
    if number <= 0:
        raise SportteryParseError(code)
    return number


def _nonnegative_int(value: Any, code: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as error:
        raise SportteryParseError(code) from error
    if number < 0:
        raise SportteryParseError(code)
    return number


def _positive_float(value: Any) -> float:
    number = _optional_float(value)
    if number is None or number <= 0:
        raise SportteryParseError("invalid_odds")
    return number


def _optional_float(value: Any) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise SportteryParseError("invalid_number") from error
    if not math.isfinite(number):
        raise SportteryParseError("invalid_number")
    return number

