from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.imports.models import SourceFile
from app.imports.parser import SourceFormatError, parse_football_data_csv


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "football_data_e0_2324.csv"


@pytest.fixture
def source_file() -> SourceFile:
    return SourceFile(
        source="football_data",
        competition_code="E0",
        competition_name="English Premier League",
        country_code="ENG",
        season="2324",
        url="https://www.football-data.co.uk/mmz4281/2324/E0.csv",
    )


def test_parser_converts_real_shape_fixture_and_keeps_safe_row_errors(
    source_file: SourceFile,
) -> None:
    """防止解析器遗漏可用比赛，或把不安全的原始行内容暴露给调用方。"""
    parsed = parse_football_data_csv(source_file, FIXTURE_PATH.read_bytes())

    assert len(parsed.matches) == 2
    assert parsed.skipped_rows == 1
    assert parsed.errors == ("row_4:home_away_same",)
    assert parsed.matches[0].source_match_id == "football_data:E0:2324:2"
    assert parsed.matches[0].kickoff_at == datetime(2023, 8, 11, 20, tzinfo=timezone.utc)
    assert parsed.matches[1].kickoff_at == datetime(2023, 8, 12, 12, tzinfo=timezone.utc)
    assert {market.market_type for market in parsed.matches[0].markets} == {
        "match_result",
        "over_under_2_5",
        "asian_handicap",
    }

    result_market = next(
        market
        for market in parsed.matches[0].markets
        if market.market_type == "match_result"
    )
    assert result_market.provider == "average"
    assert result_market.outcomes == (
        ("home", 9.5, "AvgH"),
        ("draw", 5.0, "AvgD"),
        ("away", 1.35, "AvgA"),
    )
    assert result_market.captured_at == parsed.matches[0].kickoff_at
    assert result_market.available_at == parsed.matches[0].kickoff_at
    assert result_market.stage == "closing"
    assert result_market.time_precision == "kickoff_bound"


def test_parser_accepts_bom_four_digit_dates_and_missing_odds(
    source_file: SourceFile,
) -> None:
    """防止 BOM、四位年份或空赔率让本应导入的赛果被丢弃。"""
    content = (
        "\ufeffDate,Time,HomeTeam,AwayTeam,FTHG,FTAG\n"
        "01/05/2024,18:30,Home Team,Away Team,2,0\n"
    ).encode()

    parsed = parse_football_data_csv(source_file, content)

    assert parsed.skipped_rows == 0
    assert parsed.matches[0].kickoff_at == datetime(2024, 5, 1, 18, 30, tzinfo=timezone.utc)
    assert parsed.matches[0].half_time_home_score is None
    assert parsed.matches[0].markets == ()


@pytest.mark.parametrize(
    ("row", "error_code"),
    [
        ("01/05/24,12:00,Home,Away,-1,0", "invalid_score"),
        ("01/05/24,12:00,Home,Away,one,0", "invalid_score"),
        ("01/05/24,12:00,Home,Home,1,0", "home_away_same"),
        ("01/05/24,12:00,Home,Away,1,0,0,0,0,3,4", "invalid_odds"),
    ],
)
def test_parser_skips_invalid_rows_with_stable_codes(
    source_file: SourceFile, row: str, error_code: str
) -> None:
    """防止无效比分、同队对阵或非正赔率进入后续导入层。"""
    content = (
        "Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,HTHG,HTAG,AvgH,AvgD,AvgA\n"
        f"{row}\n"
    ).encode()

    parsed = parse_football_data_csv(source_file, content)

    assert parsed.matches == ()
    assert parsed.skipped_rows == 1
    assert parsed.errors == (f"row_2:{error_code}",)


def test_parser_rejects_file_without_required_headers(source_file: SourceFile) -> None:
    """防止来源列结构变化时静默映射出错误比赛。"""
    content = b"Date,HomeTeam,AwayTeam,FTHG\n01/05/24,Home,Away,1\n"

    with pytest.raises(SourceFormatError, match="missing_required_headers"):
        parse_football_data_csv(source_file, content)


def test_parser_falls_back_to_one_complete_bookmaker_triplet_without_mixing(
    source_file: SourceFile,
) -> None:
    """防止平均赔率缺失时把不同博彩公司赔率混成一个市场快照。"""
    content = (
        "Date,HomeTeam,AwayTeam,FTHG,FTAG,B365H,B365D,B365A,BWH,BWD,BWA\n"
        "01/05/24,Home,Away,1,0,2.0,3.0,4.0,1.8,,4.2\n"
    ).encode()

    parsed = parse_football_data_csv(source_file, content)

    assert len(parsed.matches) == 1
    assert parsed.matches[0].markets[0].provider == "bet365"
    assert parsed.matches[0].markets[0].outcomes == (
        ("home", 2.0, "B365H"),
        ("draw", 3.0, "B365D"),
        ("away", 4.0, "B365A"),
    )


def test_parser_does_not_fall_back_when_average_columns_exist_but_are_incomplete(
    source_file: SourceFile,
) -> None:
    """防止缺失的平均赔率被不同口径的博彩公司赔率悄悄替换。"""
    content = (
        "Date,HomeTeam,AwayTeam,FTHG,FTAG,AvgH,AvgD,AvgA,B365H,B365D,B365A\n"
        "01/05/24,Home,Away,1,0,2.0,,4.0,2.1,3.1,4.1\n"
    ).encode()

    parsed = parse_football_data_csv(source_file, content)

    assert parsed.matches[0].markets == ()


@pytest.mark.parametrize(
    ("headers", "values"),
    [
        ("AvgH,AvgD,AvgA", "0,,4.0"),
        ("Avg>2.5,Avg<2.5", "0,"),
        ("AHh,AvgAHH,AvgAHA", ",0,"),
    ],
)
def test_parser_rejects_non_positive_odds_in_incomplete_market_groups(
    source_file: SourceFile, headers: str, values: str
) -> None:
    """防止不完整赔率组把 0 或负数静默当作“市场缺失”。"""
    content = (
        f"Date,HomeTeam,AwayTeam,FTHG,FTAG,{headers}\n"
        f"01/05/24,Home,Away,1,0,{values}\n"
    ).encode()

    parsed = parse_football_data_csv(source_file, content)

    assert parsed.matches == ()
    assert parsed.skipped_rows == 1
    assert parsed.errors == ("row_2:invalid_odds",)


@pytest.mark.parametrize(
    ("headers", "values", "error_code"),
    [
        ("AvgH,AvgD,AvgA", "nan,3.0,4.0", "invalid_odds"),
        ("Avg>2.5,Avg<2.5", "inf,2.0", "invalid_odds"),
        ("AHh,AvgAHH,AvgAHA", "0.5,-inf,1.9", "invalid_odds"),
        ("AHh,AvgAHH,AvgAHA", "nan,1.9,1.9", "invalid_handicap"),
    ],
)
def test_parser_rejects_non_finite_odds_and_handicap_values(
    source_file: SourceFile, headers: str, values: str, error_code: str
) -> None:
    """防止 NaN 或 Infinity 进入市场记录和后续数据库约束。"""
    content = (
        f"Date,HomeTeam,AwayTeam,FTHG,FTAG,{headers}\n"
        f"01/05/24,Home,Away,1,0,{values}\n"
    ).encode()

    parsed = parse_football_data_csv(source_file, content)

    assert parsed.matches == ()
    assert parsed.skipped_rows == 1
    assert parsed.errors == (f"row_2:{error_code}",)
