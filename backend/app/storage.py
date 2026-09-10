from dataclasses import dataclass
from pathlib import Path

import duckdb

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
REQUIRED_TABLES = frozenset(
    {
        "competitions",
        "market_snapshots",
        "matches",
        "schema_migrations",
        "team_aliases",
        "teams",
    }
)


@dataclass(frozen=True)
class DatabaseStatus:
    ready: bool
    engine: str
    schema_version: int
    table_count: int


def initialize_database(database_path: Path) -> None:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    schema = SCHEMA_PATH.read_text(encoding="utf-8")

    with duckdb.connect(str(database_path)) as connection:
        connection.execute(schema)


def get_database_status(database_path: Path) -> DatabaseStatus:
    if not database_path.exists():
        return DatabaseStatus(
            ready=False,
            engine="duckdb",
            schema_version=0,
            table_count=0,
        )

    with duckdb.connect(str(database_path), read_only=True) as connection:
        tables = {row[0] for row in connection.execute("SHOW TABLES").fetchall()}
        schema_version = connection.execute(
            "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
        ).fetchone()[0]

    return DatabaseStatus(
        ready=REQUIRED_TABLES.issubset(tables),
        engine="duckdb",
        schema_version=int(schema_version),
        table_count=len(tables),
    )
