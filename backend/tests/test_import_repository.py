"""ImportRepository 的真实 DuckDB 集成测试，不使用网络或数据库 mock。"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import duckdb
import pytest

from app.imports.models import (
    MarketRecord,
    MatchQuery,
    MatchRecord,
    ParsedFile,
    SourceFile,
)
from app.imports.parser import parse_football_data_csv
from app.imports.repository import ImportRepository, RepositoryError, normalize_alias


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


def _two_match_file(parsed_file: ParsedFile) -> ParsedFile:
    """生成时间不同的第二场比赛，覆盖查询排序与分页。"""
    first_match = parsed_file.matches[0]
    second_kickoff = first_match.kickoff_at + timedelta(days=7)
    second_match = replace(
        first_match,
        row_number=first_match.row_number + 1,
        source_match_id=f"{first_match.source_match_id}:second",
        kickoff_at=second_kickoff,
        home_team="Chelsea",
        away_team="Liverpool",
        # kickoff_bound 的 closing 赔率只能在其对应比赛开球时可用。
        markets=tuple(
            replace(market, captured_at=second_kickoff, available_at=second_kickoff)
            for market in first_match.markets
        ),
    )
    return ParsedFile(matches=(first_match, second_match), skipped_rows=0, errors=())


def test_list_matches_returns_latest_page_with_closing_market_views(
    tmp_path: Path, source_file: SourceFile, parsed_file: ParsedFile
) -> None:
    """默认查询按开球时间倒序分页，并组合当前页比赛的 closing 赔率。"""
    repository = ImportRepository(tmp_path / "match-list.duckdb")
    _import_once(repository, source_file, _two_match_file(parsed_file))

    page = repository.list_matches(MatchQuery(page=1, page_size=1))
    second_page = repository.list_matches(MatchQuery(page=2, page_size=1))

    assert page.total_items == 2
    assert page.total_pages == 2
    assert len(page.items) == 1
    assert page.items[0].kickoff_at > second_page.items[0].kickoff_at
    assert {market.market_type for market in page.items[0].markets} == {
        "match_result",
        "over_under_2_5",
        "asian_handicap",
    }
    assert all(market.stage == "closing" for market in page.items[0].markets)


def test_list_matches_filters_by_competition_season_and_case_insensitive_team(
    tmp_path: Path, source_file: SourceFile, parsed_file: ParsedFile
) -> None:
    """联赛和赛季精确筛选；球队名称则支持大小写无关的包含匹配。"""
    repository = ImportRepository(tmp_path / "match-filters.duckdb")
    _import_once(repository, source_file, parsed_file)
    german_source = replace(
        source_file,
        competition_code="D1",
        competition_name="German Bundesliga",
        season="2425",
        url="https://www.football-data.co.uk/mmz4281/2425/D1.csv",
    )
    _import_once(repository, german_source, parsed_file)

    competition_page = repository.list_matches(
        MatchQuery(competition="English Premier League")
    )
    season_page = repository.list_matches(MatchQuery(season="2425"))
    team_page = repository.list_matches(MatchQuery(team="bUrNl"))

    assert [item.competition for item in competition_page.items] == [
        "English Premier League"
    ]
    assert [item.season for item in season_page.items] == ["2425"]
    assert len(team_page.items) == 2


def test_list_matches_returns_empty_page_for_unknown_or_literal_wildcard_filter(
    tmp_path: Path, source_file: SourceFile, parsed_file: ParsedFile
) -> None:
    """不存在的条件与百分号查询均返回空页，百分号不能扩大为通配搜索。"""
    repository = ImportRepository(tmp_path / "empty-filter.duckdb")
    _import_once(repository, source_file, parsed_file)

    unknown_page = repository.list_matches(MatchQuery(competition="Unknown League"))
    percent_page = repository.list_matches(MatchQuery(team="%"))

    assert unknown_page.total_items == 0
    assert unknown_page.total_pages == 0
    assert unknown_page.items == ()
    assert percent_page.items == ()


def test_list_matches_keeps_matches_without_odds_and_respects_second_page(
    tmp_path: Path, source_file: SourceFile, parsed_file: ParsedFile
) -> None:
    """没有赔率的比赛仍应出现在分页结果中，markets 使用空元组表达。"""
    repository = ImportRepository(tmp_path / "no-odds.duckdb")
    _import_once(repository, source_file, parsed_file)
    first_match = parsed_file.matches[0]
    no_odds_match = replace(
        first_match,
        row_number=first_match.row_number + 1,
        source_match_id=f"{first_match.source_match_id}:no-odds",
        kickoff_at=first_match.kickoff_at + timedelta(days=14),
        home_team="Newcastle",
        away_team="Brighton",
        markets=(),
    )
    _import_once(
        repository,
        source_file,
        ParsedFile(matches=(no_odds_match,), skipped_rows=0, errors=()),
    )

    first_page = repository.list_matches(MatchQuery(page=1, page_size=1))
    second_page = repository.list_matches(MatchQuery(page=2, page_size=1))

    assert first_page.items[0].home_team == "Newcastle"
    assert first_page.items[0].markets == ()
    assert second_page.items[0].home_team != "Newcastle"


def test_list_matches_returns_empty_filter_options_for_empty_database(tmp_path: Path) -> None:
    """空数据库不会伪造可筛选的联赛或赛季。"""
    repository = ImportRepository(tmp_path / "empty-database.duckdb")

    page = repository.list_matches(MatchQuery())

    assert page.total_items == 0
    assert page.total_pages == 0
    assert page.items == ()
    assert page.filters.competitions == ()
    assert page.filters.seasons == ()


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


def test_finish_run_rejects_incomplete_requested_scope_and_keeps_audit_running(
    tmp_path: Path, source_file: SourceFile
) -> None:
    """尚未生成或处理完所有请求文件时，不能把运行伪装成已完成。"""
    repository = ImportRepository(tmp_path / "incomplete.duckdb")
    run_id = repository.start_run(source_file.source, requested_files=2)
    repository.start_file(run_id, source_file)

    with pytest.raises(RepositoryError, match="incomplete_run"):
        repository.finish_run(run_id)

    latest = repository.latest_run()
    assert latest is not None
    assert latest.result.status == "running"


def test_start_file_rejects_run_that_has_already_finished(
    tmp_path: Path, source_file: SourceFile, parsed_file: ParsedFile
) -> None:
    """结束后的运行不允许补写审计文件，防止汇总计数被事后改变。"""
    repository = ImportRepository(tmp_path / "finished.duckdb")
    run_id = _import_once(repository, source_file, parsed_file)

    with pytest.raises(RepositoryError, match="invalid_run_state"):
        repository.start_file(run_id, source_file)


def test_record_download_persists_only_consistent_pending_file_audit(
    tmp_path: Path, source_file: SourceFile
) -> None:
    """下载元数据只能补充 pending 审计；矛盾重试不能覆盖首次来源事实。"""
    repository = ImportRepository(tmp_path / "download-audit.duckdb")
    run_id = repository.start_run(source_file.source, requested_files=1)
    file_id = repository.start_file(run_id, source_file)
    downloaded_at = datetime(2026, 9, 10, 12, tzinfo=timezone.utc)

    repository.record_download(file_id, "raw/E0/matches.csv", "checksum", downloaded_at)
    repository.record_download(file_id, "raw/E0/matches.csv", "checksum", downloaded_at)

    with pytest.raises(RepositoryError, match="download_audit_conflict"):
        repository.record_download(file_id, "raw/E0/other.csv", "other", downloaded_at)
    with duckdb.connect(str(repository.database_path), read_only=True) as connection:
        assert connection.execute(
            "SELECT local_path, sha256, epoch_ms(downloaded_at) FROM import_files WHERE id = ?",
            [file_id],
        ).fetchone() == ("raw/E0/matches.csv", "checksum", 1789041600000)


def test_repository_rejects_kickoff_bound_market_not_tied_to_match_kickoff(
    tmp_path: Path, source_file: SourceFile, parsed_file: ParsedFile
) -> None:
    """kickoff_bound 收盘赔率只能在开球时可用，不能被提前时间绕过回测边界。"""
    repository = ImportRepository(tmp_path / "timing.duckdb")
    match = parsed_file.matches[0]
    invalid_market = replace(
        match.markets[0],
        captured_at=match.kickoff_at - timedelta(minutes=1),
        available_at=match.kickoff_at - timedelta(minutes=1),
    )
    invalid_file = ParsedFile(
        matches=(replace(match, markets=(invalid_market,)),), skipped_rows=0, errors=()
    )
    run_id = repository.start_run(source_file.source, requested_files=1)
    file_id = repository.start_file(run_id, source_file)

    with pytest.raises(RepositoryError, match="invalid_record"):
        repository.import_parsed_file(file_id, source_file, invalid_file)

    assert _counts(repository.database_path)["matches"] == 0


def test_repository_rejects_alias_owned_by_a_different_team(
    tmp_path: Path, source_file: SourceFile, parsed_file: ParsedFile
) -> None:
    """来源别名冲突必须显式失败，不能由 INSERT OR IGNORE 吞掉。"""
    repository = ImportRepository(tmp_path / "alias-conflict.duckdb")
    match = parsed_file.matches[0]
    with duckdb.connect(str(repository.database_path)) as connection:
        connection.execute("INSERT INTO teams (id, name_zh) VALUES ('other-team', 'Other')")
        connection.execute(
            """
            INSERT INTO team_aliases (id, team_id, source, alias, normalized_alias)
            VALUES ('other-alias', 'other-team', ?, ?, ?)
            """,
            [source_file.source, match.home_team, normalize_alias(match.home_team)],
        )
    run_id = repository.start_run(source_file.source, requested_files=1)
    file_id = repository.start_file(run_id, source_file)

    with pytest.raises(RepositoryError, match="source_fact_conflict"):
        repository.import_parsed_file(file_id, source_file, parsed_file)


def test_repository_rejects_file_when_source_url_differs_from_audit_record(
    tmp_path: Path, source_file: SourceFile, parsed_file: ParsedFile
) -> None:
    """文件审计必须绑定完整来源地址，不能只比较联赛和赛季。"""
    repository = ImportRepository(tmp_path / "url-mismatch.duckdb")
    run_id = repository.start_run(source_file.source, requested_files=1)
    file_id = repository.start_file(run_id, source_file)
    different_url = replace(source_file, url="https://example.invalid/replaced.csv")

    with pytest.raises(RepositoryError, match="invalid_file_state"):
        repository.import_parsed_file(file_id, different_url, parsed_file)
