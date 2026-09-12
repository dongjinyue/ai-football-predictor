from pathlib import Path

import duckdb
import pytest

from app.storage import get_database_status, initialize_database


REQUIRED_TABLES = {
    "competitions",
    "import_files",
    "import_runs",
    "market_outcomes",
    "market_snapshots",
    "matches",
    "schema_migrations",
    "team_aliases",
    "teams",
}


def column_details(database_path: Path, table_name: str) -> dict[str, str]:
    """返回表字段及类型，便于验证迁移后的真实数据库结构。"""
    with duckdb.connect(str(database_path), read_only=True) as connection:
        rows = connection.execute(f"DESCRIBE {table_name}").fetchall()
    return {row[0]: row[1] for row in rows}


def table_names(database_path: Path) -> set[str]:
    with duckdb.connect(str(database_path), read_only=True) as connection:
        rows = connection.execute("SHOW TABLES").fetchall()
    return {row[0] for row in rows}


def test_initialize_database_creates_required_tables(tmp_path: Path) -> None:
    database_path = tmp_path / "football.duckdb"

    initialize_database(database_path)

    assert table_names(database_path) == REQUIRED_TABLES


def test_initialize_database_can_run_twice_without_losing_schema(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "football.duckdb"

    initialize_database(database_path)
    initialize_database(database_path)

    status = get_database_status(database_path)
    assert status.ready is True
    assert status.engine == "duckdb"
    assert status.schema_version == 3
    assert status.table_count == 9


def test_initialize_database_upgrades_v1_schema_without_losing_data(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "football.duckdb"

    # 构造一个真实的 v1 数据库，证明升级不是只修改版本号。
    schema = (Path(__file__).parents[1] / "app" / "schema.sql").read_text(
        encoding="utf-8"
    )
    with duckdb.connect(str(database_path)) as connection:
        connection.execute(schema)
        connection.execute(
            """
            INSERT INTO competitions
                (id, name_zh, source, source_competition_id)
            VALUES ('competition-1', '英超', 'test', 'E0')
            """
        )
        connection.execute(
            "INSERT INTO teams (id, name_zh) VALUES ('home-1', '主队'), ('away-1', '客队')"
        )
        connection.execute(
            """
            INSERT INTO matches
                (id, competition_id, season, kickoff_at, home_team_id,
                 away_team_id, status, source, source_match_id, available_at)
            VALUES
                ('match-1', 'competition-1', '2526', TIMESTAMPTZ '2026-01-01 12:00:00+00',
                 'home-1', 'away-1', 'finished', 'test', 'm1',
                 TIMESTAMPTZ '2026-01-02 12:00:00+00')
            """
        )
        connection.execute(
            """
            INSERT INTO market_snapshots
                (id, match_id, provider, market_type, handicap, home_value,
                 draw_value, away_value, captured_at, available_at)
            VALUES
                ('snapshot-1', 'match-1', 'average', 'match_result', NULL,
                 2.0, 3.0, 4.0, TIMESTAMPTZ '2026-01-01 11:00:00+00',
                 TIMESTAMPTZ '2026-01-02 12:00:00+00'),
                ('snapshot-2', 'match-1', 'average', 'match_result', NULL,
                 2.1, 3.1, 4.1, TIMESTAMPTZ '2026-01-01 11:30:00+00',
                 TIMESTAMPTZ '2026-01-02 12:00:00+00')
            """
        )

    initialize_database(database_path)

    match_columns = column_details(database_path, "matches")
    snapshot_columns = column_details(database_path, "market_snapshots")
    assert {"half_time_home_score", "half_time_away_score"} <= match_columns.keys()
    assert snapshot_columns["handicap"].startswith("DECIMAL")
    assert {"source", "stage", "time_precision", "handicap_key"} <= snapshot_columns.keys()

    with duckdb.connect(str(database_path), read_only=True) as connection:
        assert connection.execute("SELECT COUNT(*) FROM matches").fetchone()[0] == 1
        assert (
            connection.execute("SELECT COUNT(*) FROM market_snapshots").fetchone()[0]
            == 1
        )
        migrated = connection.execute(
            """
            SELECT
                source,
                stage,
                time_precision,
                handicap_key,
                captured_at = TIMESTAMPTZ '2026-01-01 12:00:00+00',
                available_at = TIMESTAMPTZ '2026-01-01 12:00:00+00'
            FROM market_snapshots
            WHERE id = 'snapshot-1'
            """
        ).fetchone()
    assert migrated == (
        "legacy_unknown",
        "closing",
        "kickoff_bound",
        "none",
        True,
        True,
    )


def test_market_snapshot_unique_key_rejects_duplicate_without_handicap(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "football.duckdb"
    initialize_database(database_path)

    with duckdb.connect(str(database_path)) as connection:
        connection.execute(
            "INSERT INTO competitions (id, name_zh, source, source_competition_id) VALUES ('c', '联赛', 'test', 'c')"
        )
        connection.execute(
            "INSERT INTO teams (id, name_zh) VALUES ('h', '主队'), ('a', '客队')"
        )
        connection.execute(
            """
            INSERT INTO matches
                (id, competition_id, season, kickoff_at, home_team_id, away_team_id,
                 status, source, source_match_id, available_at)
            VALUES ('m', 'c', '2526', TIMESTAMPTZ '2026-01-01 12:00:00+00',
                    'h', 'a', 'finished', 'test', 'm',
                    TIMESTAMPTZ '2026-01-01 12:00:00+00')
            """
        )
        values = """
            (?, 'm', 'average', 'football_data', 'match_result', NULL, 'none',
             2.0, 3.0, 4.0, TIMESTAMPTZ '2026-01-01 12:00:00+00',
             TIMESTAMPTZ '2026-01-01 12:00:00+00', 'closing', 'kickoff_bound')
        """
        insert_sql = """
            INSERT INTO market_snapshots
                (id, match_id, provider, source, market_type, handicap, handicap_key,
                 home_value, draw_value, away_value, captured_at, available_at,
                 stage, time_precision)
            VALUES
        """ + values
        connection.execute(insert_sql, ["snapshot-1"])
        with pytest.raises(duckdb.ConstraintException):
            connection.execute(insert_sql, ["snapshot-2"])


def test_market_snapshot_preserves_quarter_handicap(tmp_path: Path) -> None:
    database_path = tmp_path / "football.duckdb"
    initialize_database(database_path)

    with duckdb.connect(str(database_path)) as connection:
        connection.execute(
            "INSERT INTO competitions (id, name_zh, source, source_competition_id) VALUES ('c', '联赛', 'test', 'c')"
        )
        connection.execute(
            "INSERT INTO teams (id, name_zh) VALUES ('h', '主队'), ('a', '客队')"
        )
        connection.execute(
            """
            INSERT INTO matches
                (id, competition_id, season, kickoff_at, home_team_id, away_team_id,
                 status, source, source_match_id, available_at)
            VALUES ('m', 'c', '2526', TIMESTAMPTZ '2026-01-01 12:00:00+00',
                    'h', 'a', 'finished', 'test', 'm',
                    TIMESTAMPTZ '2026-01-01 12:00:00+00')
            """
        )
        connection.execute(
            """
            INSERT INTO market_snapshots
                (id, match_id, provider, source, market_type, handicap, handicap_key,
                 home_value, away_value, captured_at, available_at, stage,
                 time_precision)
            VALUES
                ('s', 'm', 'average', 'football_data', 'asian_handicap',
                 0.25, '0.25', 1.9, 1.9,
                 TIMESTAMPTZ '2026-01-01 12:00:00+00',
                 TIMESTAMPTZ '2026-01-01 12:00:00+00', 'closing',
                 'kickoff_bound')
            """
        )
        handicap = connection.execute(
            "SELECT handicap FROM market_snapshots WHERE id = 's'"
        ).fetchone()[0]

    assert str(handicap) == "0.25"


def test_market_outcome_unique_key_rejects_duplicate_outcome_code(
    tmp_path: Path,
) -> None:
    """同一快照的同一结果只能保存一次，避免导入重复赔率。"""
    database_path = tmp_path / "football.duckdb"
    initialize_database(database_path)

    with duckdb.connect(str(database_path)) as connection:
        connection.execute(
            "INSERT INTO competitions (id, name_zh, source, source_competition_id) VALUES ('c', '联赛', 'test', 'c')"
        )
        connection.execute(
            "INSERT INTO teams (id, name_zh) VALUES ('h', '主队'), ('a', '客队')"
        )
        connection.execute(
            """
            INSERT INTO matches
                (id, competition_id, season, kickoff_at, home_team_id, away_team_id,
                 status, source, source_match_id, available_at)
            VALUES ('m', 'c', '2526', TIMESTAMPTZ '2026-01-01 12:00:00+00',
                    'h', 'a', 'finished', 'test', 'm',
                    TIMESTAMPTZ '2026-01-01 12:00:00+00')
            """
        )
        connection.execute(
            """
            INSERT INTO market_snapshots
                (id, match_id, provider, source, market_type, handicap, handicap_key,
                 home_value, draw_value, away_value, captured_at, available_at,
                 stage, time_precision)
            VALUES ('s', 'm', 'average', 'football_data', 'match_result', NULL,
                    'none', 2.0, 3.0, 4.0,
                    TIMESTAMPTZ '2026-01-01 12:00:00+00',
                    TIMESTAMPTZ '2026-01-01 12:00:00+00', 'closing',
                    'kickoff_bound')
            """
        )
        outcome_values = "VALUES (?, 's', 'home', 2.0, 0.5, 'B365H')"
        insert_sql = """
            INSERT INTO market_outcomes
                (id, snapshot_id, outcome_code, odds_value, normalized_probability,
                 source_field)
        """ + outcome_values
        connection.execute(insert_sql, ["outcome-1"])
        with pytest.raises(duckdb.ConstraintException):
            connection.execute(insert_sql, ["outcome-2"])


@pytest.mark.parametrize("counter_column", ["imported_matches", "skipped_rows"])
def test_import_file_rejects_negative_counters(
    tmp_path: Path,
    counter_column: str,
) -> None:
    """文件级导入统计必须是非负数，避免审计记录出现无效计数。"""
    database_path = tmp_path / "football.duckdb"
    initialize_database(database_path)

    with duckdb.connect(str(database_path)) as connection:
        connection.execute(
            """
            INSERT INTO import_runs (id, source, status, requested_files, started_at)
            VALUES ('run-1', 'football_data', 'running', 1,
                    TIMESTAMPTZ '2026-01-01 12:00:00+00')
            """
        )
        with pytest.raises(duckdb.ConstraintException):
            connection.execute(
                f"""
                INSERT INTO import_files
                    (id, run_id, source, competition_code, season, source_url, status,
                     {counter_column})
                VALUES ('file-1', 'run-1', 'football_data', 'E0', '2526',
                        'https://example.test/E0.csv', 'pending', -1)
                """
            )
