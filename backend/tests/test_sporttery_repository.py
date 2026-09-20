"""中国竞彩事实表的事务与幂等性测试。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pytest

from app.sporttery.parser import parse_fixed_bonus, parse_match_page
from app.sporttery.repository import SportteryRepository
from app.sporttery.storage import StoredResponse
from app.imports.models import MatchQuery
from app.imports.repository import ImportRepository
from app.storage import initialize_database


FIXTURES = Path(__file__).parent / "fixtures"


def _parsed(name: str):
    payload = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return parse_match_page(payload) if "match_page" in name else parse_fixed_bonus(payload)


def _stored(key: str) -> StoredResponse:
    return StoredResponse(
        path=Path(f"data/raw/{key}.json"),
        sha256=f"sha-{key}",
        fetched_at=datetime(2026, 9, 19, tzinfo=timezone.utc),
        request_url=f"https://example.test/{key}",
        status_code=200,
        data={},
        from_cache=False,
    )


def test_migration_creates_sporttery_tables(tmp_path: Path) -> None:
    database = tmp_path / "sporttery.duckdb"
    initialize_database(database)

    with duckdb.connect(str(database), read_only=True) as connection:
        tables = {row[0] for row in connection.execute("SHOW TABLES").fetchall()}
        version = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]

    assert version == 8
    assert {
        "sporttery_matches",
        "sporttery_bonus_snapshots",
        "sporttery_bonus_outcomes",
        "sporttery_single_pools",
        "sporttery_requests",
    } <= tables


def test_reimport_is_idempotent_and_coverage_counts_each_fact_once(tmp_path: Path) -> None:
    repository = SportteryRepository(tmp_path / "sporttery.duckdb")
    page = _parsed("sporttery_match_page.json")
    bonus = _parsed("sporttery_fixed_bonus.json")

    repository.import_match_page(page, _stored("page-1"))
    repository.import_match_page(page, _stored("page-1"))
    repository.import_fixed_bonus(bonus, _stored("62373"))
    repository.import_fixed_bonus(bonus, _stored("62373"))
    report = repository.coverage_report(2015)

    assert report.matches == 2
    assert report.matches_with_bonus == 1
    assert report.snapshots == 5
    assert dict(report.snapshots_by_market) == {
        "correct_score": 1,
        "half_full": 1,
        "handicap_result": 1,
        "match_result": 1,
        "total_goals": 1,
    }
    assert report.outcomes == 54
    assert report.request_records == 2


def test_bonus_import_rolls_back_when_match_is_unknown(tmp_path: Path) -> None:
    database = tmp_path / "sporttery.duckdb"
    repository = SportteryRepository(database)

    with pytest.raises(ValueError, match="unknown_match"):
        repository.import_fixed_bonus(_parsed("sporttery_fixed_bonus.json"), _stored("62373"))

    with duckdb.connect(str(database), read_only=True) as connection:
        assert connection.execute("SELECT COUNT(*) FROM sporttery_bonus_snapshots").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM sporttery_requests").fetchone()[0] == 0


def test_sporttery_facts_are_visible_in_history_browser_without_fake_exact_time(
    tmp_path: Path,
) -> None:
    """体彩比赛同步到历史页，但必须明确标记只有日期，页面市场只取最新快照。"""
    database = tmp_path / "sporttery.duckdb"
    repository = SportteryRepository(database)
    repository.import_match_page(_parsed("sporttery_match_page.json"), _stored("page-1"))
    repository.import_fixed_bonus(_parsed("sporttery_fixed_bonus.json"), _stored("62373"))

    page = ImportRepository(database).list_matches(MatchQuery(season="2015", page_size=10))

    assert page.total_items == 2
    visible = next(item for item in page.items if "主队甲" in item.home_team)
    assert visible.competition_code == "JC25"
    assert visible.kickoff_time_precision == "date_only"
    assert visible.kickoff_at.date().isoformat() == "2015-01-03"
    assert {market.market_type for market in visible.markets} == {
        "match_result",
        "handicap_result",
        "total_goals",
        "correct_score",
        "half_full",
    }
    assert all(market.source == "sporttery" for market in visible.markets)

    with duckdb.connect(str(database), read_only=True) as connection:
        source, precision = connection.execute(
            "SELECT source, kickoff_time_precision FROM matches WHERE source_match_id = '62373'"
        ).fetchone()
    assert (source, precision) == ("sporttery", "date_only")


def test_replay_supports_legacy_match_with_null_core_mapping_and_existing_bonus(
    tmp_path: Path,
) -> None:
    """旧记录已有赔率外键时不更新主行，仍可按稳定 ID 补齐页面数据。"""
    database = tmp_path / "sporttery.duckdb"
    repository = SportteryRepository(database)
    page = _parsed("sporttery_match_page.json")
    bonus = _parsed("sporttery_fixed_bonus.json")
    repository.import_match_page(page, _stored("page-1"))

    with duckdb.connect(str(database)) as connection:
        connection.execute(
            "UPDATE sporttery_matches SET core_match_id = NULL WHERE match_id = 62373"
        )
    repository.import_fixed_bonus(bonus, _stored("62373"))

    # 赔率表已引用比赛后，DuckDB 不允许更新该主行；回放必须绕开这个限制。
    repository.import_match_page(page, _stored("page-1"))
    repository.import_fixed_bonus(bonus, _stored("62373"))

    visible = ImportRepository(database).list_matches(
        MatchQuery(season="2015", page_size=10)
    )
    assert any(item.id for item in visible.items if "主队甲" in item.home_team)
