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
