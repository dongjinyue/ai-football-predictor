"""历史导入的 DuckDB 仓储：一份源文件一个事务，重复导入不覆盖事实。"""

from __future__ import annotations

import re
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from app.imports.models import (
    FileImportResult,
    HistoricalMatchView,
    ImportRequestScope,
    ImportRunAudit,
    ImportRunResult,
    MatchFilterOptions,
    MatchMarketView,
    MatchPage,
    MatchQuery,
    ParsedFile,
    SourceFile,
)
from app.storage import initialize_database


# 固定命名空间让同一来源自然键在不同进程、不同机器上得到完全相同的身份。
APPLICATION_NAMESPACE = uuid.UUID("baf3f034-97ca-5c75-8c35-6e3c678d9b3a")
_WHITESPACE = re.compile(r"\s+")


class RepositoryError(RuntimeError):
    """仓储向上层暴露的安全错误代码，绝不拼接 SQL 或本机路径。"""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def stable_id(kind: str, *parts: str) -> str:
    """以来源拥有的自然键生成稳定 UUIDv5，而非随机 UUID。"""
    return str(uuid.uuid5(APPLICATION_NAMESPACE, ":".join((kind, *parts))))


def normalize_alias(value: str) -> str:
    """只消除 Unicode 与书写格式差异，绝不猜测两支不同球队是否相同。"""
    return _WHITESPACE.sub(" ", unicodedata.normalize("NFKC", value).strip()).casefold()


class ImportRepository:
    """保存导入审计与业务事实的最小仓储接口。"""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        initialize_database(database_path)

    def start_run(self, source: str, requested_files: int) -> str:
        """创建运行审计；运行 ID 故意随机，使每次操作都有独立可追溯记录。"""
        if not source or requested_files < 0:
            raise RepositoryError("invalid_run")
        run_id = str(uuid.uuid4())
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO import_runs (id, source, status, requested_files, started_at)
                VALUES (?, ?, 'running', ?, ?)
                """,
                [run_id, source, requested_files, _utc_now()],
            )
        return run_id

    def start_file(
        self,
        run_id: str,
        source_file: SourceFile,
        *,
        local_path: str | None = None,
        sha256: str | None = None,
    ) -> str:
        """登记待处理文件；下载元数据只作审计，不能改变赔率可用时间。"""
        file_id = str(uuid.uuid4())
        try:
            with self._connect() as connection:
                run = connection.execute(
                    "SELECT status FROM import_runs WHERE id = ?", [run_id]
                ).fetchone()
                if run is None or run[0] != "running":
                    raise RepositoryError("invalid_run_state")
                connection.execute(
                    """
                    INSERT INTO import_files (
                        id, run_id, source, competition_code, season, source_url,
                        local_path, sha256, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')
                    """,
                    [
                        file_id,
                        run_id,
                        source_file.source,
                        source_file.competition_code,
                        source_file.season,
                        source_file.url,
                        local_path,
                        sha256,
                    ],
                )
        except duckdb.Error as error:
            raise RepositoryError("audit_write_failed") from error
        return file_id

    def record_download(
        self,
        file_id: str,
        local_path: str,
        sha256: str,
        downloaded_at: datetime,
    ) -> None:
        """补充 pending 文件的下载审计，绝不触碰比赛或市场时间。"""
        if not local_path or not sha256:
            raise RepositoryError("invalid_download_audit")
        try:
            audited_at = _utc(downloaded_at)
        except (TypeError, ValueError) as error:
            raise RepositoryError("invalid_download_audit") from error

        try:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT status, local_path, sha256, epoch_ms(downloaded_at)
                    FROM import_files WHERE id = ?
                    """,
                    [file_id],
                ).fetchone()
                if row is None or row[0] != "pending":
                    raise RepositoryError("invalid_file_state")

                existing = row[1:]
                candidate = (local_path, sha256, _epoch_milliseconds(audited_at))
                if any(value is not None for value in existing):
                    if existing != candidate:
                        raise RepositoryError("download_audit_conflict")
                    return

                connection.execute(
                    """
                    UPDATE import_files
                    SET local_path = ?, sha256 = ?, downloaded_at = ?
                    WHERE id = ? AND status = 'pending'
                    """,
                    [local_path, sha256, audited_at, file_id],
                )
        except RepositoryError:
            raise
        except duckdb.Error as error:
            raise RepositoryError("audit_write_failed") from error

    def import_parsed_file(
        self,
        file_id: str,
        source_file: SourceFile,
        parsed_file: ParsedFile,
    ) -> FileImportResult:
        """原子写入一个文件的业务数据，成功后才在事务外更新审计状态。"""
        imported_matches = 0
        try:
            with self._connect() as connection:
                connection.execute("BEGIN TRANSACTION")
                try:
                    self._assert_pending_file(connection, file_id, source_file)
                    competition_id = self._write_competition(connection, source_file)
                    for match in parsed_file.matches:
                        imported_matches += self._write_match(
                            connection, competition_id, source_file, match
                        )
                except Exception:
                    connection.execute("ROLLBACK")
                    raise
                else:
                    connection.execute("COMMIT")
        except RepositoryError:
            raise
        except duckdb.Error as error:
            raise RepositoryError("database_error") from error
        except (TypeError, ValueError) as error:
            raise RepositoryError("invalid_record") from error

        # 审计不属于上方业务事务；因此文件失败时 fail_file 仍可留下原因。
        try:
            with self._connect() as connection:
                updated = connection.execute(
                    """
                    UPDATE import_files
                    SET status = 'completed', imported_matches = ?, skipped_rows = ?, error_code = NULL
                    WHERE id = ? AND status = 'pending'
                    RETURNING id
                    """,
                    [imported_matches, parsed_file.skipped_rows, file_id],
                ).fetchone()
                if updated is None:
                    raise RepositoryError("invalid_file_state")
        except RepositoryError:
            raise
        except duckdb.Error as error:
            raise RepositoryError("audit_write_failed") from error

        return FileImportResult(
            file_id=file_id,
            source_file=source_file,
            status="completed",
            imported_matches=imported_matches,
            skipped_rows=parsed_file.skipped_rows,
            errors=parsed_file.errors,
        )

    def fail_file(self, file_id: str, error_code: str) -> FileImportResult:
        """在业务事务回滚后保留安全错误码，不保存异常原文。"""
        if not error_code or not re.fullmatch(r"[a-z0-9_]+", error_code):
            raise RepositoryError("invalid_error_code")
        try:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    UPDATE import_files SET status = 'failed', error_code = ?
                    WHERE id = ? AND status = 'pending'
                    RETURNING source, competition_code, season, source_url
                    """,
                    [error_code, file_id],
                ).fetchone()
        except duckdb.Error as error:
            raise RepositoryError("audit_write_failed") from error
        if row is None:
            raise RepositoryError("invalid_file_state")
        source, competition_code, season, source_url = row
        return FileImportResult(
            file_id=file_id,
            source_file=SourceFile(source, competition_code, competition_code, "", season, source_url),
            status="failed",
            imported_matches=0,
            skipped_rows=0,
            errors=(error_code,),
        )

    def finish_run(self, run_id: str) -> ImportRunResult:
        """依据文件审计汇总运行状态，避免协调器自行计算而产生口径漂移。"""
        with self._connect() as connection:
            run = connection.execute(
                "SELECT source, requested_files, status FROM import_runs WHERE id = ?", [run_id]
            ).fetchone()
            if run is None:
                raise RepositoryError("unknown_run")
            completed, failed, pending, total, imported, skipped = connection.execute(
                """
                SELECT
                    COUNT(*) FILTER (WHERE status = 'completed'),
                    COUNT(*) FILTER (WHERE status = 'failed'),
                    COUNT(*) FILTER (WHERE status = 'pending'),
                    COUNT(*),
                    COALESCE(SUM(imported_matches) FILTER (WHERE status = 'completed'), 0),
                    COALESCE(SUM(skipped_rows) FILTER (WHERE status = 'completed'), 0)
                FROM import_files WHERE run_id = ?
                """,
                [run_id],
            ).fetchone()
            if run[2] != "running":
                raise RepositoryError("invalid_run_state")
            if pending or total != run[1] or completed + failed != run[1]:
                raise RepositoryError("incomplete_run")
            errors = tuple(
                row[0]
                for row in connection.execute(
                    "SELECT error_code FROM import_files WHERE run_id = ? AND status = 'failed' ORDER BY id",
                    [run_id],
                ).fetchall()
            )
            status = "completed" if failed == 0 else "completed_with_errors" if completed else "failed"
            connection.execute(
                """
                UPDATE import_runs
                SET status = ?, completed_files = ?, failed_files = ?, imported_matches = ?,
                    skipped_rows = ?, finished_at = ?, error_summary = ?
                WHERE id = ?
                """,
                [status, completed, failed, imported, skipped, _utc_now(), ",".join(errors) or None, run_id],
            )
        return ImportRunResult(run_id, status, run[1], completed, failed, imported, skipped, errors)

    def latest_run(self) -> ImportRunAudit | None:
        """从运行和文件审计聚合最近一次导入，保留公开所需的真实来源与范围。"""
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, source, status, requested_files, completed_files, failed_files,
                       imported_matches, skipped_rows,
                       CAST(started_at AS VARCHAR), CAST(finished_at AS VARCHAR), error_summary
                FROM import_runs ORDER BY started_at DESC, id DESC LIMIT 1
                """
            ).fetchone()
            scope_rows = () if row is None else connection.execute(
                """
                SELECT competition_code, season
                FROM import_files WHERE run_id = ?
                ORDER BY competition_code, season, source_url
                """,
                [row[0]],
            ).fetchall()
        if row is None:
            return None
        errors = tuple(filter(None, (row[10] or "").split(",")))
        result = ImportRunResult(row[0], row[2], *row[3:8], errors)
        return ImportRunAudit(
            result=result,
            source=row[1],
            started_at=_parse_database_timestamp(row[8]),
            finished_at=_parse_database_timestamp(row[9]) if row[9] else None,
            requested_scope=tuple(ImportRequestScope(*scope_row) for scope_row in scope_rows),
        )

    def data_summary(self) -> dict[str, object]:
        """返回 API 可直接消费的数据规模与最新安全时间点。"""
        with self._connect() as connection:
            counts = {
                table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("competitions", "teams", "matches", "market_snapshots", "market_outcomes")
            }
            latest_kickoff = connection.execute(
                "SELECT CAST(MAX(kickoff_at) AS VARCHAR) FROM matches"
            ).fetchone()[0]
            latest_success = connection.execute(
                "SELECT CAST(MAX(finished_at) AS VARCHAR) FROM import_runs WHERE status IN ('completed', 'completed_with_errors')"
            ).fetchone()[0]
        return {**counts, "latest_kickoff_at": latest_kickoff, "latest_successful_import_at": latest_success}

    def list_matches(self, query: MatchQuery) -> MatchPage:
        """按筛选条件分页读取比赛，并批量组合当前页的 closing 赔率。"""
        if query.page < 1:
            raise ValueError("page must be positive")
        if not 1 <= query.page_size <= 100:
            raise ValueError("page_size must be between 1 and 100")

        conditions, parameters = _match_filter_sql(query)
        where_clause = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        offset = (query.page - 1) * query.page_size

        with self._connect() as connection:
            total_items = int(
                connection.execute(
                    f"""
                    SELECT COUNT(*)
                    FROM matches AS match
                    JOIN competitions AS competition ON competition.id = match.competition_id
                    JOIN teams AS home ON home.id = match.home_team_id
                    JOIN teams AS away ON away.id = match.away_team_id
                    {where_clause}
                    """,
                    parameters,
                ).fetchone()[0]
            )
            match_rows = connection.execute(
                f"""
                SELECT
                    match.id, CAST(match.kickoff_at AS VARCHAR), competition.name_zh, match.season,
                    home.name_zh, away.name_zh, match.home_score, match.away_score
                FROM matches AS match
                JOIN competitions AS competition ON competition.id = match.competition_id
                JOIN teams AS home ON home.id = match.home_team_id
                JOIN teams AS away ON away.id = match.away_team_id
                {where_clause}
                ORDER BY match.kickoff_at DESC, match.id DESC
                LIMIT ? OFFSET ?
                """,
                [*parameters, query.page_size, offset],
            ).fetchall()
            filters = MatchFilterOptions(
                competitions=tuple(
                    row[0]
                    for row in connection.execute(
                        """
                        SELECT DISTINCT source_competition_id
                        FROM competitions
                        ORDER BY source_competition_id
                        """
                    ).fetchall()
                ),
                seasons=tuple(
                    row[0]
                    for row in connection.execute(
                        "SELECT DISTINCT season FROM matches ORDER BY season"
                    ).fetchall()
                ),
            )
            markets_by_match = _load_closing_markets(
                connection, tuple(row[0] for row in match_rows)
            )

        items = tuple(
            HistoricalMatchView(
                id=row[0],
                # DuckDB 在精简环境转换 TIMESTAMPTZ 时依赖可选 pytz（时区库）。
                kickoff_at=_parse_database_timestamp(row[1]),
                competition=row[2],
                season=row[3],
                home_team=row[4],
                away_team=row[5],
                home_score=row[6],
                away_score=row[7],
                markets=markets_by_match.get(row[0], ()),
            )
            for row in match_rows
        )
        return MatchPage(
            page=query.page,
            total_items=total_items,
            total_pages=(total_items + query.page_size - 1) // query.page_size,
            filters=filters,
            items=items,
        )

    def _connect(self) -> duckdb.DuckDBPyConnection:
        return duckdb.connect(str(self.database_path))

    @staticmethod
    def _assert_pending_file(connection: duckdb.DuckDBPyConnection, file_id: str, source_file: SourceFile) -> None:
        row = connection.execute(
            "SELECT source, competition_code, season, source_url, status FROM import_files WHERE id = ?", [file_id]
        ).fetchone()
        if row is None or row[4] != "pending" or row[:4] != (
            source_file.source,
            source_file.competition_code,
            source_file.season,
            source_file.url,
        ):
            raise RepositoryError("invalid_file_state")

    @staticmethod
    def _write_competition(connection: duckdb.DuckDBPyConnection, source_file: SourceFile) -> str:
        competition_id = stable_id("competition", source_file.source, source_file.competition_code)
        existing = connection.execute(
            "SELECT name_zh, country_code FROM competitions WHERE id = ?", [competition_id]
        ).fetchone()
        expected = (source_file.competition_name, source_file.country_code)
        if existing is not None and existing != expected:
            raise RepositoryError("source_fact_conflict")
        connection.execute(
            """
            INSERT OR IGNORE INTO competitions
                (id, name_zh, name_en, country_code, source, source_competition_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [competition_id, source_file.competition_name, source_file.competition_name, source_file.country_code, source_file.source, source_file.competition_code],
        )
        return competition_id

    def _write_match(self, connection: duckdb.DuckDBPyConnection, competition_id: str, source_file: SourceFile, match) -> int:
        home_id = self._write_team(connection, source_file.source, match.home_team)
        away_id = self._write_team(connection, source_file.source, match.away_team)
        kickoff_at = _utc(match.kickoff_at)
        natural_identity = ":".join((source_file.source, source_file.competition_code, source_file.season, normalize_alias(match.home_team), normalize_alias(match.away_team), kickoff_at.isoformat()))
        match_id = stable_id("match", natural_identity)
        existing = connection.execute(
            """
            SELECT competition_id, season, epoch_ms(kickoff_at), home_team_id, away_team_id,
                   home_score, away_score, half_time_home_score, half_time_away_score,
                   epoch_ms(available_at)
            FROM matches WHERE id = ?
            """,
            [match_id],
        ).fetchone()
        facts = (competition_id, source_file.season, kickoff_at, home_id, away_id, match.home_score, match.away_score, match.half_time_home_score, match.half_time_away_score, kickoff_at)
        existing_facts = (*facts[:2], _epoch_milliseconds(kickoff_at), *facts[3:9], _epoch_milliseconds(kickoff_at))
        if existing is not None and existing != existing_facts:
            raise RepositoryError("source_fact_conflict")
        if existing is None:
            connection.execute(
                """
                INSERT INTO matches (
                    id, competition_id, season, kickoff_at, home_team_id, away_team_id,
                    home_score, away_score, half_time_home_score, half_time_away_score,
                    status, source, source_match_id, available_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'finished', ?, ?, ?)
                """,
                [match_id, *facts[:9], source_file.source, natural_identity, facts[9]],
            )
        for market in match.markets:
            self._write_market(connection, match_id, kickoff_at, market)
        return int(existing is None)

    @staticmethod
    def _write_team(connection: duckdb.DuckDBPyConnection, source: str, alias: str) -> str:
        normalized = normalize_alias(alias)
        if not normalized:
            raise RepositoryError("invalid_record")
        team_id = stable_id("team", source, normalized)
        # team_aliases 的业务自然键是 (source, normalized_alias)，不能只查本次
        # 计算出的 UUID；否则异常的既有行会被 INSERT OR IGNORE 静默掩盖。
        alias_owner = connection.execute(
            "SELECT team_id FROM team_aliases WHERE source = ? AND normalized_alias = ?",
            [source, normalized],
        ).fetchone()
        if alias_owner is not None and alias_owner[0] != team_id:
            raise RepositoryError("source_fact_conflict")
        connection.execute(
            "INSERT OR IGNORE INTO teams (id, name_zh) VALUES (?, ?)", [team_id, alias.strip()]
        )
        alias_id = stable_id("team_alias", source, normalized)
        existing = connection.execute("SELECT team_id FROM team_aliases WHERE id = ?", [alias_id]).fetchone()
        if existing is not None and existing[0] != team_id:
            raise RepositoryError("source_fact_conflict")
        connection.execute(
            """
            INSERT OR IGNORE INTO team_aliases (id, team_id, source, alias, normalized_alias)
            VALUES (?, ?, ?, ?, ?)
            """,
            [alias_id, team_id, source, alias.strip(), normalized],
        )
        return team_id

    @staticmethod
    def _write_market(
        connection: duckdb.DuckDBPyConnection,
        match_id: str,
        kickoff_at: datetime,
        market,
    ) -> None:
        captured_at = _utc(market.captured_at)
        available_at = _utc(market.available_at)
        if captured_at > available_at:
            raise RepositoryError("invalid_record")
        # Football-Data 的收盘赔率没有真实采集时间。kickoff_bound 只能表示
        # “开球时才可确认”的 closing 快照，不能被伪造为赛前可用数据。
        if market.time_precision == "kickoff_bound" and (
            market.stage != "closing"
            or captured_at != kickoff_at
            or available_at != kickoff_at
        ):
            raise RepositoryError("invalid_record")
        handicap_key = "none" if market.line is None else f"{market.line:.2f}"
        snapshot_id = stable_id("market_snapshot", match_id, market.source, market.provider, market.market_type, handicap_key, captured_at.isoformat(), market.stage)
        expected = (match_id, market.provider, market.source, market.market_type, handicap_key, captured_at, available_at, market.stage, market.time_precision)
        existing = connection.execute(
            """
            SELECT match_id, provider, source, market_type, handicap_key, epoch_ms(captured_at),
                   epoch_ms(available_at), stage, time_precision
            FROM market_snapshots WHERE id = ?
            """,
            [snapshot_id],
        ).fetchone()
        expected_existing = (*expected[:5], _epoch_milliseconds(captured_at), _epoch_milliseconds(available_at), *expected[7:])
        if existing is not None and existing != expected_existing:
            raise RepositoryError("source_fact_conflict")
        connection.execute(
            """
            INSERT OR IGNORE INTO market_snapshots
                (id, match_id, provider, source, market_type, handicap, handicap_key,
                 captured_at, available_at, stage, time_precision)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [snapshot_id, match_id, market.provider, market.source, market.market_type, market.line, handicap_key, captured_at, available_at, market.stage, market.time_precision],
        )
        for outcome_code, odds_value, source_field in market.outcomes:
            outcome_id = stable_id("market_outcome", snapshot_id, outcome_code)
            current = connection.execute(
                "SELECT odds_value, source_field FROM market_outcomes WHERE id = ?", [outcome_id]
            ).fetchone()
            expected_outcome = (odds_value, source_field)
            if current is not None and current != expected_outcome:
                raise RepositoryError("source_fact_conflict")
            connection.execute(
                """
                INSERT OR IGNORE INTO market_outcomes
                    (id, snapshot_id, outcome_code, odds_value, source_field)
                VALUES (?, ?, ?, ?, ?)
                """,
                [outcome_id, snapshot_id, outcome_code, odds_value, source_field],
            )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("naive_datetime")
    return value.astimezone(timezone.utc)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_database_timestamp(value: str) -> datetime:
    """避免 DuckDB 将 TIMESTAMPTZ 转为 Python 对象时依赖可选 pytz（时区库）。"""
    parsed = datetime.fromisoformat(value.replace("Z", "+00"))
    return _utc(parsed)


def _epoch_milliseconds(value: datetime) -> int:
    """统一 TIMESTAMPTZ 比较口径，避免最小离线环境的时区可选依赖。"""
    return int(value.timestamp() * 1000)


def _match_filter_sql(query: MatchQuery) -> tuple[list[str], list[str]]:
    """构造参数化筛选片段；球队关键词中的 LIKE 元字符按普通文本处理。"""
    conditions: list[str] = []
    parameters: list[str] = []
    if query.competition:
        conditions.append("competition.source_competition_id = ?")
        parameters.append(query.competition)
    if query.season:
        conditions.append("match.season = ?")
        parameters.append(query.season)
    if query.team:
        team_pattern = f"%{_escape_like(query.team.lower())}%"
        conditions.append(
            "(lower(home.name_zh) LIKE ? ESCAPE '\\' OR lower(away.name_zh) LIKE ? ESCAPE '\\')"
        )
        parameters.extend((team_pattern, team_pattern))
    return conditions, parameters


def _escape_like(value: str) -> str:
    """转义 LIKE 的反斜杠、百分号和下划线，避免用户输入扩展匹配范围。"""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _load_closing_markets(
    connection: duckdb.DuckDBPyConnection, match_ids: tuple[str, ...]
) -> dict[str, tuple[MatchMarketView, ...]]:
    """一次批量查询读取当前页 markets 与 outcomes，避免逐比赛查询。"""
    if not match_ids:
        return {}
    placeholders = ", ".join("?" for _ in match_ids)
    rows = connection.execute(
        f"""
        SELECT
            snapshot.match_id, snapshot.id, snapshot.market_type, snapshot.stage,
            snapshot.handicap, outcome.outcome_code, outcome.odds_value
        FROM market_snapshots AS snapshot
        LEFT JOIN market_outcomes AS outcome ON outcome.snapshot_id = snapshot.id
        WHERE snapshot.match_id IN ({placeholders}) AND snapshot.stage = 'closing'
        ORDER BY snapshot.match_id, snapshot.market_type, snapshot.id, outcome.outcome_code
        """,
        list(match_ids),
    ).fetchall()
    grouped: dict[str, list[MatchMarketView]] = {}
    current_snapshot_id: str | None = None
    current_match_id: str | None = None
    current_type: str | None = None
    current_stage: str | None = None
    current_line: float | None = None
    current_outcomes: list[tuple[str, float]] = []

    def finish_market() -> None:
        if current_snapshot_id is None or current_match_id is None or current_type is None or current_stage is None:
            return
        grouped.setdefault(current_match_id, []).append(
            MatchMarketView(
                market_type=current_type,
                stage=current_stage,
                line=current_line,
                outcomes=tuple(current_outcomes),
            )
        )

    for match_id, snapshot_id, market_type, stage, line, outcome_code, odds_value in rows:
        if snapshot_id != current_snapshot_id:
            finish_market()
            current_snapshot_id = snapshot_id
            current_match_id = match_id
            current_type = market_type
            current_stage = stage
            current_line = float(line) if line is not None else None
            current_outcomes = []
        if outcome_code is not None:
            current_outcomes.append((outcome_code, float(odds_value)))
    finish_market()
    return {match_id: tuple(markets) for match_id, markets in grouped.items()}
