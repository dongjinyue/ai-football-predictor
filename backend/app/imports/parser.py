"""Football-Data CSV 的纯解析器，不负责下载或持久化。"""

import csv
import io
import math
from datetime import datetime, time, timezone

from app.imports.models import MarketRecord, MatchRecord, ParsedFile, SourceFile


REQUIRED_HEADERS = frozenset({"Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG"})
BOOKMAKERS = (
    ("bet365", "B365H", "B365D", "B365A"),
    ("betway", "BWH", "BWD", "BWA"),
)


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
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise SourceFormatError("invalid_encoding") from error

    reader = csv.DictReader(io.StringIO(text))
    headers = set(reader.fieldnames or ())
    if not REQUIRED_HEADERS <= headers:
        raise SourceFormatError("missing_required_headers")

    matches: list[MatchRecord] = []
    errors: list[str] = []
    for row_number, row in enumerate(reader, start=2):
        try:
            matches.append(_parse_row(source_file, row_number, row))
        except _RowError as error:
            errors.append(f"row_{row_number}:{error}")

    return ParsedFile(
        matches=tuple(matches),
        skipped_rows=len(errors),
        errors=tuple(errors),
    )


def _parse_row(
    source_file: SourceFile, row_number: int, row: dict[str, str | None]
) -> MatchRecord:
    home_team = _required_text(row, "HomeTeam")
    away_team = _required_text(row, "AwayTeam")
    if home_team.casefold() == away_team.casefold():
        raise _RowError("home_away_same")

    home_score = _score(row, "FTHG", required=True)
    away_score = _score(row, "FTAG", required=True)
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
            f"{source_file.season}:{row_number}"
        ),
        kickoff_at=kickoff_at,
        home_team=home_team,
        away_team=away_team,
        half_time_home_score=half_home,
        half_time_away_score=half_away,
        home_score=home_score,
        away_score=away_score,
        markets=markets,
    )


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
        kickoff_time = time(12, tzinfo=timezone.utc)
    else:
        try:
            parsed_time = datetime.strptime(time_value, "%H:%M").time()
        except ValueError as error:
            raise _RowError("invalid_kickoff") from error
        kickoff_time = parsed_time.replace(tzinfo=timezone.utc)
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
        fields=(("over_2_5", "Avg>2.5"), ("under_2_5", "Avg<2.5")),
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
    average_fields = (("home", "AvgH"), ("draw", "AvgD"), ("away", "AvgA"))
    average = _two_or_three_outcome_market(
        row, kickoff_at, "match_result", None, "average", average_fields
    )
    if average is not None:
        return average

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
            return fallback
    return None


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
    return MarketRecord(
        provider=provider,
        source="football_data",
        market_type=market_type,
        stage="closing",
        captured_at=kickoff_at,
        available_at=kickoff_at,
        time_precision="kickoff_bound",
        line=line,
        outcomes=outcomes,
    )


def _asian_handicap_market(
    row: dict[str, str | None], kickoff_at: datetime
) -> MarketRecord | None:
    line_value = (row.get("AHh") or "").strip()
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
        (("home", "AvgAHH"), ("away", "AvgAHA")),
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
