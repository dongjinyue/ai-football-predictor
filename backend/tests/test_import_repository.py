"""ImportRepository 的真实 DuckDB 集成测试，不使用网络或数据库 mock。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pytest

from app.imports.models import MarketRecord, MatchRecord, ParsedFile, SourceFile
from app.imports.parser import parse_football_data_csv
from app.imports.repository import ImportRepository, RepositoryError


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


@pytest.fixture
def parsed_file(source_file: SourceFile) -> ParsedFile:
    parsed = parse_football_data_csv(source_file, FIXTURE_PATH.read_bytes())
    # 仓储职责聚焦在“一个源文件的一场比赛”完整落库；解析器的多行覆盖另有测试。
    return ParsedFile(matches=(parsed.matches[0],), skipped_rows=0, errors=())


def _counts(database_path: Path) -> dict[str, int]:
    tables = (
        "competitions",
        "teams",
        "team_aliases",
        "matches",
        "market_snapshots",
        "market_outcomes",
        "import_runs",
        "import_files",
    )
    with duckdb.connect(str(database_path), read_only=True) as connection:
        return {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in tables
        }


def _import_once(
    repository: ImportRepository,
    source_file: SourceFile,
    parsed_file: ParsedFile,
) -> str:
    run_id = repository.start_run(source_file.source, requested_files=1)
    file_id = repository.start_file(run_id, source_file)
    result = repository.import_parsed_file(file_id, source_file, parsed_file)
    assert result.status == "completed"
    repository.finish_run(run_id)
    return run_id


def test_repository_persists_complete_file_and_keeps_repeat_business_data_idempotent(
    tmp_path: Path, source_file: SourceFile, parsed_file: ParsedFile
) -> None:
    """相同来源文件重跑只增加审计行，绝不覆盖既有来源事实或时间。"""
    database_path = tmp_path / "history.duckdb"
    repository = ImportRepository(database_path)

    first_run_id = _import_once(repository, source_file, parsed_file)
    first_counts = _counts(database_path)
    second_run_id = _import_once(repository, source_file, parsed_file)
    second_counts = _counts(database_path)

    assert first_run_id != second_run_id
    assert first_counts == {
        "competitions": 1,
        "teams": 2,
        "team_aliases": 2,
        "matches": 1,
        "market_snapshots": 3,
        "market_outcomes": 7,
        "import_runs": 1,
        "import_files": 1,
    }
    assert {
        key: second_counts[key]
        for key in ("competitions", "teams", "team_aliases", "matches", "market_snapshots", "market_outcomes")
    } == {
        key: first_counts[key]
        for key in ("competitions", "teams", "team_aliases", "matches", "market_snapshots", "market_outcomes")
    }
    assert second_counts["import_runs"] == 2
    assert second_counts["import_files"] == 2

    with duckdb.connect(str(database_path), read_only=True) as connection:
        snapshot = connection.execute(
            """
            SELECT handicap, epoch_ms(captured_at), epoch_ms(available_at), stage, time_precision
            FROM market_snapshots
            WHERE market_type = 'asian_handicap'
            """
        ).fetchone()
        match = connection.execute(
            """
            SELECT half_time_home_score, half_time_away_score, epoch_ms(available_at)
            FROM matches
            ORDER BY kickoff_at
            LIMIT 1
            """
        ).fetchone()

    assert float(snapshot[0]) == 1.5
    assert snapshot[1] == snapshot[2]
    assert snapshot[3:] == ("closing", "kickoff_bound")
    assert match == (0, 2, 1691784000000)


def test_repository_rolls_back_all_business_rows_and_preserves_failed_audit(
    tmp_path: Path, source_file: SourceFile
) -> None:
    """后半段市场写入失败时，前面创建的实体也必须随文件事务全部撤销。"""
    database_path = tmp_path / "rollback.duckdb"
    repository = ImportRepository(database_path)
    invalid_market = MarketRecord(
        provider="average",
        source="football_data",
        market_type="match_result",
        stage="closing",
        captured_at=datetime(2023, 8, 11, 20, tzinfo=timezone.utc),
        available_at=datetime(2023, 8, 11, 20, tzinfo=timezone.utc),
        time_precision="kickoff_bound",
        line=None,
        outcomes=(("home", 0.0, "AvgH"),),
    )
    parsed_file = ParsedFile(
        matches=(
            MatchRecord(
                row_number=2,
                source_match_id="football_data:E0:2324:2",
                kickoff_at=datetime(2023, 8, 11, 20, tzinfo=timezone.utc),
                home_team="  Ａrsenal   ",
                away_team="Chelsea",
                half_time_home_score=0,
                half_time_away_score=0,
                home_score=1,
                away_score=0,
                markets=(invalid_market,),
            ),
        ),
        skipped_rows=0,
        errors=(),
    )
    run_id = repository.start_run(source_file.source, requested_files=1)
    file_id = repository.start_file(run_id, source_file)

    with pytest.raises(RepositoryError, match="database_error"):
        repository.import_parsed_file(file_id, source_file, parsed_file)
    repository.fail_file(file_id, "database_error")
    run = repository.finish_run(run_id)

    assert _counts(database_path) == {
        "competitions": 0,
        "teams": 0,
        "team_aliases": 0,
        "matches": 0,
        "market_snapshots": 0,
        "market_outcomes": 0,
        "import_runs": 1,
        "import_files": 1,
    }
    assert run.status == "failed"
    assert run.errors == ("database_error",)
    with duckdb.connect(str(database_path), read_only=True) as connection:
        assert connection.execute(
            "SELECT status, error_code FROM import_files WHERE id = ?", [file_id]
        ).fetchone() == ("failed", "database_error")
