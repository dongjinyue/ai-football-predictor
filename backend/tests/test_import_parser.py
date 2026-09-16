from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.imports.models import SourceFile
from app.imports.parser import SourceFormatError, parse_football_data_csv


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "football_data_e0_2324.csv"


def test_parser_selects_real_closing_columns_and_retains_field_evidence(source_file):
    """同时存在两组不同赔率时必须选择收盘 C 字段，含大小球和让球。"""
    content = (
        "Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,AvgH,AvgD,AvgA,AvgCH,AvgCD,AvgCA,"
        "Avg>2.5,Avg<2.5,AvgC>2.5,AvgC<2.5,AHh,AvgAHH,AvgAHA,AHCh,AvgCAHH,AvgCAHA\n"
        "11/08/2023,20:00,Burnley,Man City,0,3,9.02,5.35,1.35,9.27,5.45,1.33,"
        "1.7,2.2,1.61,2.34,1.5,1.9,2.0,1.75,1.85,2.05\n"
    ).encode()
    markets = {item.market_type: item for item in parse_football_data_csv(source_file, content).matches[0].markets}
    assert markets["match_result"].outcomes == (("home", 9.27, "AvgCH"), ("draw", 5.45, "AvgCD"), ("away", 1.33, "AvgCA"))
    assert markets["over_under_2_5"].outcomes == (("over_2_5", 1.61, "AvgC>2.5"), ("under_2_5", 2.34, "AvgC<2.5"))
    assert markets["asian_handicap"].line == 1.75
    assert markets["asian_handicap"].outcomes == (("home", 1.85, "AvgCAHH"), ("away", 2.05, "AvgCAHA"))


def test_preclosing_only_columns_are_not_claimed_as_closing(source_file):
    content = b"Date,HomeTeam,AwayTeam,FTHG,FTAG,AvgH,AvgD,AvgA\n01/05/24,Home,Away,1,0,2,3,4\n"
    assert parse_football_data_csv(source_file, content).matches[0].markets == ()


def test_bwin_closing_fallback_retains_provider_identity(source_file):
    content = b"Date,HomeTeam,AwayTeam,FTHG,FTAG,BWCH,BWCD,BWCA\n01/05/24,Home,Away,1,0,2,3,4\n"
    markets = parse_football_data_csv(source_file, content).matches[0].markets
    assert len(markets) == 1
    assert markets[0].provider == "bwin"
    assert markets[0].outcomes[0] == ("home", 2.0, "BWCH")


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
    assert parsed.matches[0].kickoff_at == datetime(2023, 8, 11, 19, tzinfo=timezone.utc)
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
        ("home", 9.5, "AvgCH"),
        ("draw", 5.0, "AvgCD"),
        ("away", 1.35, "AvgCA"),
    )
    assert result_market.captured_at == parsed.matches[0].kickoff_at
    assert result_market.available_at == parsed.matches[0].kickoff_at + timedelta(days=1)
    assert result_market.stage == "closing"
    assert result_market.time_precision == "result_after_kickoff"


def test_parser_handles_uk_winter_time_and_date_only_precision(source_file):
    content = (
        "Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,AvgCH,AvgCD,AvgCA\n"
        "01/01/2024,15:00,Winter,Visitor,1,0,2,3,4\n"
        "02/01/2024,,Date Only,Visitor,1,0,2,3,4\n"
    ).encode()
    parsed = parse_football_data_csv(source_file, content)
    assert parsed.matches[0].kickoff_at == datetime(2024, 1, 1, 15, tzinfo=timezone.utc)
    market = parsed.matches[1].markets[0]
    assert market.time_precision == "result_after_kickoff"
    assert market.available_at > parsed.matches[1].kickoff_at


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
    assert parsed.matches[0].kickoff_at == datetime(2024, 5, 1, 17, 30, tzinfo=timezone.utc)
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
        "Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,HTHG,HTAG,AvgCH,AvgCD,AvgCA\n"
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
        "Date,HomeTeam,AwayTeam,FTHG,FTAG,B365CH,B365CD,B365CA,BWCH,BWCD,BWCA\n"
        "01/05/24,Home,Away,1,0,2.0,3.0,4.0,1.8,,4.2\n"
    ).encode()

    parsed = parse_football_data_csv(source_file, content)

    assert len(parsed.matches) == 1
    assert parsed.matches[0].markets[0].provider == "bet365"
    assert parsed.matches[0].markets[0].outcomes == (
        ("home", 2.0, "B365CH"),
        ("draw", 3.0, "B365CD"),
        ("away", 4.0, "B365CA"),
    )


def test_parser_does_not_fall_back_when_average_columns_exist_but_are_incomplete(
    source_file: SourceFile,
) -> None:
    """防止缺失的平均赔率被不同口径的博彩公司赔率悄悄替换。"""
    content = (
        "Date,HomeTeam,AwayTeam,FTHG,FTAG,AvgCH,AvgCD,AvgCA,B365CH,B365CD,B365CA\n"
        "01/05/24,Home,Away,1,0,2.0,,4.0,2.1,3.1,4.1\n"
    ).encode()

    parsed = parse_football_data_csv(source_file, content)

    assert parsed.matches[0].markets == ()


@pytest.mark.parametrize(
    ("headers", "values"),
    [
        ("AvgCH,AvgCD,AvgCA", "0,,4.0"),
        ("AvgC>2.5,AvgC<2.5", "0,"),
        ("AHCh,AvgCAHH,AvgCAHA", ",0,"),
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
        ("AvgCH,AvgCD,AvgCA", "nan,3.0,4.0", "invalid_odds"),
        ("AvgC>2.5,AvgC<2.5", "inf,2.0", "invalid_odds"),
        ("AHCh,AvgCAHH,AvgCAHA", "0.5,-inf,1.9", "invalid_odds"),
        ("AHCh,AvgCAHH,AvgCAHA", "nan,1.9,1.9", "invalid_handicap"),
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
