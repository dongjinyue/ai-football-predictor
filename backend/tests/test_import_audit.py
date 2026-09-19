"""训练前历史数据审计的仓储与接口契约测试。"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.imports.models import (
    DataAuditMarketCoverage,
    DataAuditReport,
    DataAuditScope,
    DataAuditSummary,
    SourceFile,
)
from app.imports.parser import parse_football_data_csv
from app.imports.repository import ImportRepository
from app.imports.router import create_import_router


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "football_data_e0_2324.csv"


def _source_file(code: str, name: str, season: str = "2324") -> SourceFile:
    return SourceFile(
        source="football_data",
        competition_code=code,
        competition_name=name,
        country_code="ENG" if code == "E0" else "DEU",
        season=season,
        url=f"https://football-data.co.uk/mmz4281/{season}/{code}.csv",
    )


def _import_fixture(repository: ImportRepository, source_file: SourceFile) -> None:
    parsed = parse_football_data_csv(source_file, FIXTURE_PATH.read_bytes())
    run_id = repository.start_run(source_file.source, requested_files=1)
    file_id = repository.start_file(run_id, source_file)
    result = repository.import_parsed_file(file_id, source_file, parsed)
    assert result.status == "completed"
    repository.finish_run(run_id)


def test_repository_audit_returns_missing_scopes_and_market_time_semantics(tmp_path: Path) -> None:
    repository = ImportRepository(tmp_path / "audit.duckdb")
    imported = _source_file("E0", "English Premier League")
    missing = _source_file("D1", "German Bundesliga")
    _import_fixture(repository, imported)

    report = repository.data_audit((imported, missing), start_year=2023, end_year=2024)

    assert report.requested_files == 2
    assert report.summary == DataAuditSummary(
        catalog_competitions=2,
        imported_competitions=1,
        requested_files=2,
        files_with_matches=1,
        missing_files=1,
        total_matches=2,
        complete_full_time_matches=2,
        complete_half_time_matches=2,
        missing_half_time_matches=0,
        half_time_result_matches=2,
        total_goals_matches=2,
        label_ready_matches=2,
        pre_match_market_matches=0,
            kickoff_bound_market_matches=1,
            post_kickoff_market_matches=2,
    )
    assert report.scopes[0] == DataAuditScope(
        competition_code="E0",
        competition_name="English Premier League",
        country_code="ENG",
        season="2324",
        match_count=2,
        complete_full_time_matches=2,
        complete_half_time_matches=2,
        missing_half_time_matches=0,
        half_time_result_matches=2,
        total_goals_matches=2,
        label_ready_matches=2,
        pre_match_market_matches=0,
        kickoff_bound_market_matches=1,
        post_kickoff_market_matches=2,
        markets=(
            DataAuditMarketCoverage(
                market_type="asian_handicap",
                snapshot_count=2,
                match_count=2,
                pre_match_snapshot_count=0,
                pre_match_match_count=0,
                kickoff_bound_snapshot_count=1,
                kickoff_bound_match_count=1,
                post_kickoff_snapshot_count=2,
            ),
            DataAuditMarketCoverage(
                market_type="match_result",
                snapshot_count=2,
                match_count=2,
                pre_match_snapshot_count=0,
                pre_match_match_count=0,
                kickoff_bound_snapshot_count=0,
                kickoff_bound_match_count=0,
                post_kickoff_snapshot_count=2,
            ),
            DataAuditMarketCoverage(
                market_type="over_under_2_5",
                snapshot_count=2,
                match_count=2,
                pre_match_snapshot_count=0,
                pre_match_match_count=0,
                kickoff_bound_snapshot_count=1,
                kickoff_bound_match_count=1,
                post_kickoff_snapshot_count=2,
            ),
        ),
    )
    assert report.scopes[1].competition_code == "D1"
    assert report.scopes[1].match_count == 0
    assert report.scopes[1].markets == ()


def test_repository_audit_aggregates_matches_from_a_combined_source_range(tmp_path: Path) -> None:
    """合并源文件的一个请求范围应汇总其中各实际赛季，而不是显示为零场。"""
    repository = ImportRepository(tmp_path / "combined-audit.duckdb")
    source_file = SourceFile(
        source="football_data",
        competition_code="ARG",
        competition_name="Argentine Primera Division",
        country_code="ARG",
        season="2012-2014",
        url="https://football-data.co.uk/new/ARG.csv",
        source_scope="combined",
        start_year=2012,
        end_year=2014,
        season_style="calendar_year",
    )
    content = (
        "Country,League,Season,Date,Time,Home,Away,HG,AG,Res\n"
        "Argentina,Liga,2014,01/05/2014,15:00,Home,Visitor,1,0,H\n"
    ).encode()
    parsed = parse_football_data_csv(source_file, content)
    run_id = repository.start_run(source_file.source, requested_files=1)
    file_id = repository.start_file(run_id, source_file)
    repository.import_parsed_file(file_id, source_file, parsed)
    repository.finish_run(run_id)

    report = repository.data_audit((source_file,), start_year=2012, end_year=2014)

    assert report.scopes[0].season == "2012-2014"
    assert report.scopes[0].match_count == 1
    assert report.summary.total_matches == 1


def test_audit_endpoint_builds_requested_range_and_returns_safe_response() -> None:
    report = DataAuditReport(
        start_year=2000,
        end_year=2001,
        requested_files=1,
        summary=DataAuditSummary(
            catalog_competitions=1,
            imported_competitions=1,
            requested_files=1,
            files_with_matches=1,
            missing_files=0,
            total_matches=380,
            complete_full_time_matches=380,
            complete_half_time_matches=379,
            missing_half_time_matches=1,
            half_time_result_matches=379,
            total_goals_matches=380,
            label_ready_matches=380,
            pre_match_market_matches=0,
            kickoff_bound_market_matches=760,
            post_kickoff_market_matches=1140,
        ),
        scopes=(
            DataAuditScope(
                competition_code="E0",
                competition_name="English Premier League",
                country_code="ENG",
                season="9900",
                match_count=380,
                complete_full_time_matches=380,
                complete_half_time_matches=379,
                missing_half_time_matches=1,
                half_time_result_matches=379,
                total_goals_matches=380,
                label_ready_matches=380,
                pre_match_market_matches=0,
                kickoff_bound_market_matches=760,
                post_kickoff_market_matches=1140,
                markets=(),
            ),
        ),
    )

    class FakeRepository:
        def __init__(self) -> None:
            self.requests: tuple[SourceFile, ...] = ()

        def data_audit(
            self,
            requests: tuple[SourceFile, ...],
            start_year: int,
            end_year: int,
        ) -> DataAuditReport:
            self.requests = requests
            return report

    repository = FakeRepository()
    application = FastAPI()
    application.include_router(create_import_router(repository=repository), prefix="/api/data")

    response = TestClient(application).get(
        "/api/data/audit",
        params={"start_year": 2000, "end_year": 2001, "competition_codes": "E0"},
    )

    assert response.status_code == 200
    assert response.json()["summary"]["label_ready_matches"] == 380
    assert response.json()["scopes"][0]["competition_code"] == "E0"
    assert [(item.competition_code, item.season) for item in repository.requests] == [
        ("E0", "0001")
    ]
