from dataclasses import dataclass
from pathlib import Path

import duckdb

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
MIGRATIONS_PATH = Path(__file__).with_name("migrations")
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
    """初始化数据库，并按版本顺序原子执行尚未应用的迁移。"""
    database_path.parent.mkdir(parents=True, exist_ok=True)
    schema = SCHEMA_PATH.read_text(encoding="utf-8")

    with duckdb.connect(str(database_path)) as connection:
        connection.execute(schema)
        current_version = int(
            connection.execute(
                "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
            ).fetchone()[0]
        )

        for migration_path in sorted(MIGRATIONS_PATH.glob("*.sql")):
            migration_version = int(migration_path.stem.split("_", maxsplit=1)[0])
            if migration_version <= current_version:
                continue

            migration = migration_path.read_text(encoding="utf-8")
            connection.execute("BEGIN TRANSACTION")
            try:
                connection.execute(migration)
            except Exception:
                connection.execute("ROLLBACK")
                raise
            else:
                connection.execute("COMMIT")
                current_version = migration_version


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
