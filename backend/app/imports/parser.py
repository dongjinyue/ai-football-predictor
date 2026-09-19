"""Football-Data CSV 的纯解析器，不负责下载或持久化。"""

import csv
import io
import math
import re
from dataclasses import replace
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from app.imports.models import MarketRecord, MatchRecord, ParsedFile, SourceFile


REQUIRED_HEADERS = frozenset({"Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG"})
LEGACY_TEAM_HEADERS = frozenset({"Date", "HT", "AT", "FTHG", "FTAG"})
COMBINED_HEADERS = frozenset({"Date", "Season", "Home", "Away", "HG", "AG"})
BOOKMAKERS = (
    ("bet365", "B365CH", "B365CD", "B365CA"),
    ("bwin", "BWCH", "BWCD", "BWCA"),
)
SOURCE_TIMEZONE = ZoneInfo("Europe/London")


class SourceFormatError(ValueError):
    """表示整份文件无法安全解析的稳定错误，不包含来源行内容。"""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class _RowError(ValueError):
    """仅在本模块内部使用的逐行安全错误代码。"""


def parse_football_data_csv(source_file: SourceFile, content: bytes) -> ParsedFile:
    """将 Football-Data CSV 转为不可变领域记录。

    历史赔率没有可验证的采集时刻，因此可用时间固定绑定开球时间，避免后续
    回测把收盘赔率当作赛前已知信息。
    """
    text = decode_football_data_text(content)

    reader = csv.DictReader(io.StringIO(text))
    headers = {field.strip() for field in (reader.fieldnames or ()) if field is not None}
    header_mapping = _header_mapping(headers)
    if header_mapping is None:
        raise SourceFormatError("missing_required_headers")

    matches: list[MatchRecord] = []
    errors: list[str] = []
    for row_number, row in enumerate(reader, start=2):
        try:
            parsed = _parse_row(source_file, row_number, row, header_mapping)
            if parsed is not None:
                matches.append(parsed)
        except _RowError as error:
            errors.append(f"row_{row_number}:{error}")

    return ParsedFile(
        matches=tuple(matches),
        skipped_rows=len(errors),
        errors=tuple(errors),
    )


def _parse_row(
    source_file: SourceFile,
    row_number: int,
    row: dict[str, str | None],
    header_mapping: dict[str, str],
) -> MatchRecord | None:
    match_season = _row_season(source_file, row)
    if match_season is None:
        return None
    home_team = _required_text(row, header_mapping["home"])
    away_team = _required_text(row, header_mapping["away"])
    if home_team.casefold() == away_team.casefold():
        raise _RowError("home_away_same")

    home_score = _score(row, header_mapping["home_score"], required=True)
    away_score = _score(row, header_mapping["away_score"], required=True)
    half_home = _score(row, "HTHG", required=False)
    half_away = _score(row, "HTAG", required=False)
    if (half_home is None) != (half_away is None):
        raise _RowError("invalid_half_time_score")
    if half_home is not None and (half_home > home_score or half_away > away_score):
        raise _RowError("inconsistent_half_time_score")

    kickoff_at = _kickoff_at(row)
    markets = _markets(row, kickoff_at)
    return MatchRecord(
        row_number=row_number,
        source_match_id=(
            f"{source_file.source}:{source_file.competition_code}:"
            f"{match_season}:{row_number}"
        ),
        kickoff_at=kickoff_at,
        home_team=home_team,
        away_team=away_team,
        half_time_home_score=half_home,
        half_time_away_score=half_away,
        home_score=home_score,
        away_score=away_score,
        markets=markets,
        season=match_season if source_file.source_scope == "combined" else None,
    )


def decode_football_data_text(content: bytes) -> str:
    """按来源历史实际使用的编码解码 CSV，优先 UTF-8，再兼容西欧旧编码。"""
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise SourceFormatError("invalid_encoding")


def has_supported_headers(headers: set[str]) -> bool:
    """下载阶段只检查文件契约，不解析具体行。"""
    return _header_mapping(headers) is not None


def _header_mapping(headers: set[str]) -> dict[str, str] | None:
    if REQUIRED_HEADERS <= headers:
        return {
            "home": "HomeTeam",
            "away": "AwayTeam",
            "home_score": "FTHG",
            "away_score": "FTAG",
        }
    if LEGACY_TEAM_HEADERS <= headers:
        return {
            "home": "HT",
            "away": "AT",
            "home_score": "FTHG",
            "away_score": "FTAG",
        }
    if COMBINED_HEADERS <= headers:
        return {
            "home": "Home",
            "away": "Away",
            "home_score": "HG",
            "away_score": "AG",
        }
    return None


def _row_season(source_file: SourceFile, row: dict[str, str | None]) -> str | None:
    if source_file.source_scope != "combined":
        return source_file.season

    raw_season = (row.get("Season") or "").strip()
    season_year = _season_end_year(raw_season)
    if season_year is None:
        raise _RowError("invalid_season")
    if source_file.start_year is not None and season_year < source_file.start_year:
        return None
    if source_file.end_year is not None and season_year > source_file.end_year:
        return None
    if source_file.season_style == "split_year":
        start_year = season_year - 1
        return f"{start_year % 100:02d}{season_year % 100:02d}"
    return str(season_year)


def _season_end_year(value: str) -> int | None:
    """将 2012、2012/2013、2012/13 等来源写法统一为结束年份。"""
    if not value:
        return None
    years = re.findall(r"\d{2,4}", value)
    if not years:
        return None
    last = years[-1]
    if len(last) == 4:
        return int(last)
    if len(years) >= 2 and len(years[0]) == 4:
        base = int(years[0]) // 100 * 100
        candidate = base + int(last)
        if candidate < int(years[0]):
            candidate += 100
        return candidate
    year = int(last)
    return 2000 + year if year <= 20 else 1900 + year


def _required_text(row: dict[str, str | None], field: str) -> str:
    value = (row.get(field) or "").strip()
    if not value:
        raise _RowError("missing_required_value")
    return value


def _score(row: dict[str, str | None], field: str, *, required: bool) -> int | None:
    value = (row.get(field) or "").strip()
    if not value:
        if required:
            raise _RowError("missing_required_value")
        return None
    try:
        score = int(value)
    except ValueError as error:
        raise _RowError("invalid_score") from error
    if score < 0 or str(score) != value:
        raise _RowError("invalid_score")
    return score


def _kickoff_at(row: dict[str, str | None]) -> datetime:
    date_value = (row.get("Date") or "").strip()
    for pattern in ("%d/%m/%y", "%d/%m/%Y"):
        try:
            date_part = datetime.strptime(date_value, pattern).date()
            break
        except ValueError:
            continue
    else:
        raise _RowError("invalid_kickoff")

    time_value = (row.get("Time") or "").strip()
    if not time_value:
        # 只有日期时保留数据库需要的占位时刻，并由市场精度字段标明未知。
        kickoff_time = time(12, tzinfo=timezone.utc)
    else:
        try:
            parsed_time = datetime.strptime(time_value, "%H:%M").time()
        except ValueError as error:
            raise _RowError("invalid_kickoff") from error
        # football-data.co.uk 使用英国当地时间；ZoneInfo 会自动处理 GMT/BST。
        return datetime.combine(date_part, parsed_time, tzinfo=SOURCE_TIMEZONE).astimezone(timezone.utc)
    return datetime.combine(date_part, kickoff_time)


def _markets(row: dict[str, str | None], kickoff_at: datetime) -> tuple[MarketRecord, ...]:
    markets: list[MarketRecord] = []
    result = _result_market(row, kickoff_at)
    if result is not None:
        markets.append(result)
    over_under = _two_outcome_market(
        row,
        kickoff_at,
        market_type="over_under_2_5",
        line=2.5,
        provider="average",
        fields=(("over_2_5", "AvgC>2.5"), ("under_2_5", "AvgC<2.5")),
    )
    if over_under is not None:
        markets.append(over_under)
    asian_handicap = _asian_handicap_market(row, kickoff_at)
    if asian_handicap is not None:
        markets.append(asian_handicap)
    return tuple(markets)


def _result_market(
    row: dict[str, str | None], kickoff_at: datetime
) -> MarketRecord | None:
    average_fields = (("home", "AvgCH"), ("draw", "AvgCD"), ("away", "AvgCA"))
    average = _two_or_three_outcome_market(
        row, kickoff_at, "match_result", None, "average", average_fields
    )
    if average is not None:
        return _mark_result_available_after_kickoff(average)

    # 平均赔率列只要存在，就代表该文件选择了平均口径；某一行不完整时宁可
    # 缺少市场，也不能以另一提供方的赔率替换，避免同一文件口径悄然变化。
    if any(field in row for _, field in average_fields):
        return None

    for provider, home, draw, away in BOOKMAKERS:
        fallback = _two_or_three_outcome_market(
            row,
            kickoff_at,
            "match_result",
            None,
            provider,
            (("home", home), ("draw", draw), ("away", away)),
        )
        if fallback is not None:
            return _mark_result_available_after_kickoff(fallback)
    return None


def _mark_result_available_after_kickoff(market: MarketRecord) -> MarketRecord:
    """完赛比分对应的市场只能在开球后可用，避免回测未来信息泄漏。"""
    return replace(
        market,
        available_at=market.captured_at + timedelta(days=1),
        time_precision="result_after_kickoff",
    )


def _two_outcome_market(
    row: dict[str, str | None],
    kickoff_at: datetime,
    *,
    market_type: str,
    line: float,
    provider: str,
    fields: tuple[tuple[str, str], ...],
) -> MarketRecord | None:
    return _two_or_three_outcome_market(
        row, kickoff_at, market_type, line, provider, fields
    )


def _two_or_three_outcome_market(
    row: dict[str, str | None],
    kickoff_at: datetime,
    market_type: str,
    line: float | None,
    provider: str,
    fields: tuple[tuple[str, str], ...],
) -> MarketRecord | None:
    values = [(outcome, field, (row.get(field) or "").strip()) for outcome, field in fields]
    if not any(value for _, _, value in values):
        return None

    # 空值表示来源没有该结果；但只要出现了数值，就必须先验证。这样不完整
    # 赔率组里的 0、NaN 或 Infinity 不会被误判为可忽略的“市场缺失”。
    for _, _, value in values:
        if value:
            _positive_odds(value)
    if not all(value for _, _, value in values):
        return None

    outcomes = tuple(
        (outcome, _positive_odds(value), field) for outcome, field, value in values
    )
    has_source_time = bool((row.get("Time") or "").strip())
    return MarketRecord(
        provider=provider,
        source="football_data",
        market_type=market_type,
        stage="closing",
        captured_at=kickoff_at,
        available_at=kickoff_at,
        time_precision="kickoff_bound" if has_source_time else "date_only_unknown",
        line=line,
        outcomes=outcomes,
    )


def _asian_handicap_market(
    row: dict[str, str | None], kickoff_at: datetime
) -> MarketRecord | None:
    line_value = (row.get("AHCh") or "").strip()
    line: float | None = None
    if line_value:
        try:
            line = float(line_value)
        except ValueError as error:
            raise _RowError("invalid_handicap") from error
        if not math.isfinite(line):
            raise _RowError("invalid_handicap")
    odds = _two_or_three_outcome_market(
        row,
        kickoff_at,
        "asian_handicap",
        None,
        "average",
        (("home", "AvgCAHH"), ("away", "AvgCAHA")),
    )
    if odds is None:
        return None
    if not line_value:
        return None
    return MarketRecord(
        provider=odds.provider,
        source=odds.source,
        market_type=odds.market_type,
        stage=odds.stage,
        captured_at=odds.captured_at,
        available_at=odds.available_at,
        time_precision=odds.time_precision,
        line=line,
        outcomes=odds.outcomes,
    )


def _positive_odds(value: str) -> float:
    try:
        odds = float(value)
    except ValueError as error:
        raise _RowError("invalid_odds") from error
    if not math.isfinite(odds) or odds <= 0:
        raise _RowError("invalid_odds")
    return odds
