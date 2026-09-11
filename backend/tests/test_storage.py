from pathlib import Path

import duckdb

from app.storage import get_database_status, initialize_database


REQUIRED_TABLES = {
    "competitions",
    "market_snapshots",
    "matches",
    "schema_migrations",
    "team_aliases",
    "teams",
}


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
    assert status.schema_version == 1
    assert status.table_count == 6
