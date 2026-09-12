from dataclasses import FrozenInstanceError
from datetime import date, datetime, timezone

import pytest

from app.imports.catalog import COMPETITIONS, build_default_requests
from app.imports.models import (
    FileImportResult,
    ImportRunResult,
    MarketRecord,
    MatchRecord,
    ParsedFile,
    SourceFile,
)


# Football-Data 官方目录包含 22 个主联赛分区及 16 个 Extra Leagues（额外联赛）。
# 此处故意不从 catalog 导入期望值，以便目录遗漏时测试能够失败。
EXPECTED_COMPETITION_SEASON_STYLES = {
    "E0": "split_year",
    "E1": "split_year",
    "E2": "split_year",
    "E3": "split_year",
    "EC": "split_year",
    "SC0": "split_year",
    "SC1": "split_year",
    "SC2": "split_year",
    "SC3": "split_year",
    "D1": "split_year",
    "D2": "split_year",
    "I1": "split_year",
    "I2": "split_year",
    "SP1": "split_year",
    "SP2": "split_year",
    "F1": "split_year",
    "F2": "split_year",
    "N1": "split_year",
    "B1": "split_year",
    "P1": "split_year",
    "T1": "split_year",
    "G1": "split_year",
    "ARG": "calendar_year",
    "AUT": "split_year",
    "BRA": "calendar_year",
    "CHN": "calendar_year",
    "DNK": "split_year",
    "FIN": "calendar_year",
    "IRL": "calendar_year",
    "JPN": "calendar_year",
    "MEX": "split_year",
    "NOR": "calendar_year",
    "POL": "split_year",
    "ROU": "split_year",
    "RUS": "split_year",
    "SWE": "calendar_year",
    "SWZ": "split_year",
    "USA": "calendar_year",
}


def test_default_requests_cover_each_configured_league_once_per_season() -> None:
    """防止目录遗漏某联赛，或为同一来源文件生成重复请求。"""
    requests = build_default_requests(date(2026, 9, 10), seasons=5)

    assert requests
    assert len(requests) == len(COMPETITIONS) * 5
    assert len({item.url for item in requests}) == len(requests)
    assert {item.competition_code for item in requests} == {
        competition[0] for competition in COMPETITIONS
    }
    assert all(item.source == "football_data" for item in requests)
    assert all(
        item.url.startswith("https://www.football-data.co.uk/mmz4281/")
        for item in requests
    )


def test_catalog_matches_all_official_football_data_competitions_and_season_styles() -> None:
    """防止 Football-Data 的公开主联赛或 Extra Leagues 被悄然遗漏。"""
    configured_styles = {code: season_style for code, _, _, season_style in COMPETITIONS}

    assert configured_styles == EXPECTED_COMPETITION_SEASON_STYLES


def test_default_requests_use_completed_seasons_for_each_season_style() -> None:
    """防止把进行中的赛季或错误的年份写进 Football-Data 地址。"""
    requests = build_default_requests(date(2026, 9, 10), seasons=5)
    split_year_seasons = {
        item.season for item in requests if item.competition_code == "E0"
    }
    calendar_year_seasons = {
        item.season for item in requests if item.competition_code == "BRA"
    }

    assert split_year_seasons == {"2526", "2425", "2324", "2223", "2122"}
    assert calendar_year_seasons == {"2025", "2024", "2023", "2022", "2021"}
    assert (
        "https://www.football-data.co.uk/mmz4281/2526/E0.csv"
        in {item.url for item in requests}
    )


def test_domain_records_are_immutable_and_reports_use_tuples_and_counters() -> None:
    """防止后续导入层交换可变记录或无类型错误字典。"""
    source = SourceFile(
        source="football_data",
        competition_code="E0",
        competition_name="English Premier League",
        country_code="ENG",
        season="2526",
        url="https://www.football-data.co.uk/mmz4281/2526/E0.csv",
    )
    market = MarketRecord(
        provider="average",
        source="football_data",
        market_type="match_result",
        stage="closing",
        captured_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
        available_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
        time_precision="kickoff_bound",
        line=None,
        outcomes=(("home", 2.0, "AvgH"), ("draw", 3.0, "AvgD")),
    )
    match = MatchRecord(
        row_number=2,
        source_match_id="football-data:E0:2526:2",
        kickoff_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
        home_team="Home",
        away_team="Away",
        half_time_home_score=1,
        half_time_away_score=0,
        home_score=2,
        away_score=1,
        markets=(market,),
    )
    parsed = ParsedFile(matches=(match,), skipped_rows=1, errors=("row_3:invalid_score",))
    file_result = FileImportResult(
        file_id="file-1",
        source_file=source,
        status="completed",
        imported_matches=1,
        skipped_rows=1,
        errors=("row_3:invalid_score",),
    )
    run_result = ImportRunResult(
        run_id="run-1",
        status="completed_with_errors",
        requested_files=1,
        completed_files=1,
        failed_files=0,
        imported_matches=1,
        skipped_rows=1,
        errors=("row_3:invalid_score",),
    )

    with pytest.raises(FrozenInstanceError):
        source.season = "2425"  # type: ignore[misc]

    assert parsed.matches == (match,)
    assert file_result.imported_matches == 1
    assert run_result.errors == ("row_3:invalid_score",)
