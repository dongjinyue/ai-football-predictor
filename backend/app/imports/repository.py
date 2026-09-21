"""历史导入的 DuckDB 仓储：一份源文件一个事务，重复导入不覆盖事实。"""

from __future__ import annotations

import csv
import re
import tempfile
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from app.imports.models import (
    DataAuditMarketCoverage,
    DataAuditReport,
    DataAuditScope,
    DataAuditSummary,
    FileImportResult,
    HistoricalMatchView,
    ImportRequestScope,
    ImportRunAudit,
    ImportRunResult,
    MatchFilterOptions,
    MatchMarketHistoryView,
    MarketHistoryGroupView,
    MarketHistorySnapshotView,
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

_MARKET_ORDER = {
    "match_result": 0,
    "handicap_result": 1,
    "correct_score": 2,
    "total_goals": 3,
    "half_full": 4,
}
_OUTCOME_ORDER = {
    "match_result": ("home", "draw", "away"),
    "handicap_result": ("home", "draw", "away"),
    "correct_score": (
        "1_0", "2_0", "2_1", "3_0", "3_1", "3_2",
        "4_0", "4_1", "4_2", "5_0", "5_1", "5_2",
        "0_0", "1_1", "2_2", "3_3",
        "0_1", "0_2", "1_2", "0_3", "1_3", "2_3",
        "0_4", "1_4", "2_4", "0_5", "1_5", "2_5",
        "other_home", "other_draw", "other_away",
    ),
    "total_goals": ("0", "1", "2", "3", "4", "5", "6", "7_plus"),
    "half_full": (
        "home_home", "home_draw", "home_away",
        "draw_home", "draw_draw", "draw_away",
        "away_home", "away_draw", "away_away",
    ),
}


class RepositoryError(RuntimeError):
    """仓储向上层暴露的安全错误代码，绝不拼接 SQL 或本机路径。"""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class _PreparedTeam:
    """批量写入前整理好的球队与来源别名。"""

    team_id: str
    alias_id: str
    source: str
    alias: str
    normalized_alias: str


@dataclass(frozen=True)
class _PreparedOutcome:
    """批量写入前整理好的赔率结果。"""

    outcome_id: str
    row: tuple[object, ...]
    facts: tuple[object, ...]


@dataclass(frozen=True)
class _PreparedMarket:
    """批量写入前整理好的赔率快照及其结果。"""

    snapshot_id: str
    row: tuple[object, ...]
    facts: tuple[object, ...]
    outcomes: tuple[_PreparedOutcome, ...]


@dataclass(frozen=True)
class _PreparedMatch:
    """批量写入前整理好的比赛与市场关联。"""

    match_id: str
    row: tuple[object, ...]
    facts: tuple[object, ...]
    markets: tuple[_PreparedMarket, ...]


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
        """业务数据和成功审计在同一事务中提交；失败审计由回滚后的调用方保存。"""
        imported_matches = 0
        try:
            with self._connect() as connection:
                connection.execute("BEGIN TRANSACTION")
                try:
                    self._assert_pending_file(connection, file_id, source_file)
                    competition_id = self._write_competition(connection, source_file)
                    imported_matches = self._bulk_write_matches(
                        connection, competition_id, source_file, parsed_file
                    )
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

    def data_summary(self, source: str | None = None) -> dict[str, object]:
        if source is not None:
            return self._source_summary(source)
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

    def _source_summary(self, source: str) -> dict[str, object]:
        """统计仅关联当前来源的比赛和赔率，避免旧来源混入页面。"""
        with self._connect() as connection:
            row = connection.execute("""
                SELECT COUNT(*), COUNT(DISTINCT competition_id),
                       CAST(MAX(kickoff_at) AS VARCHAR)
                FROM matches WHERE source = ?
            """, [source]).fetchone()
            teams = connection.execute("""
                SELECT COUNT(*) FROM (
                    SELECT home_team_id FROM matches WHERE source = ?
                    UNION SELECT away_team_id FROM matches WHERE source = ?
                )
            """, [source, source]).fetchone()[0]
            markets = connection.execute("""
                SELECT COUNT(DISTINCT s.id), COUNT(o.id)
                FROM market_snapshots s
                JOIN matches m ON m.id = s.match_id
                LEFT JOIN market_outcomes o ON o.snapshot_id = s.id
                WHERE m.source = ? AND s.source = ?
            """, [source, source]).fetchone()
            if source == "sporttery":
                latest = connection.execute(
                    "SELECT CAST(MAX(imported_at) AS VARCHAR) FROM sporttery_matches"
                ).fetchone()[0]
            else:
                latest = connection.execute("""
                    SELECT CAST(MAX(finished_at) AS VARCHAR) FROM import_runs
                    WHERE source = ? AND status IN ('completed', 'completed_with_errors')
                """, [source]).fetchone()[0]
        return dict(matches=row[0], competitions=row[1], teams=teams,
                    market_snapshots=markets[0], market_outcomes=markets[1],
                    latest_kickoff_at=row[2], latest_successful_import_at=latest)

    def data_audit(
        self,
        requests: tuple[SourceFile, ...],
        start_year: int,
        end_year: int,
    ) -> DataAuditReport:
        """Aggregate requested competition-season coverage in a small number of scans."""
        if not requests:
            empty = DataAuditSummary(
                catalog_competitions=0,
                imported_competitions=0,
                requested_files=0,
                files_with_matches=0,
                missing_files=0,
                total_matches=0,
                complete_full_time_matches=0,
                complete_half_time_matches=0,
                missing_half_time_matches=0,
                half_time_result_matches=0,
                total_goals_matches=0,
                label_ready_matches=0,
                pre_match_market_matches=0,
                kickoff_bound_market_matches=0,
                post_kickoff_market_matches=0,
            )
            return DataAuditReport(start_year, end_year, 0, empty, ())

        with self._connect() as connection:
            match_rows = connection.execute(
                """
                SELECT competition.source_competition_id, match.season,
                       COUNT(*) AS match_count,
                       COUNT(*) FILTER (
                           WHERE match.home_score IS NOT NULL AND match.away_score IS NOT NULL
                       ) AS complete_full_time_matches,
                       COUNT(*) FILTER (
                           WHERE match.half_time_home_score IS NOT NULL
                             AND match.half_time_away_score IS NOT NULL
                       ) AS complete_half_time_matches,
                       COUNT(*) FILTER (
                           WHERE match.half_time_home_score IS NULL
                              OR match.half_time_away_score IS NULL
                       ) AS missing_half_time_matches
                FROM matches AS match
                JOIN competitions AS competition ON competition.id = match.competition_id
                GROUP BY competition.source_competition_id, match.season
                """
            ).fetchall()
            market_rows = connection.execute(
                """
                SELECT competition.source_competition_id, match.season,
                       snapshot.market_type,
                       COUNT(*) AS snapshot_count,
                       COUNT(DISTINCT snapshot.match_id) AS match_count,
                       COUNT(*) FILTER (
                           WHERE snapshot.available_at < match.kickoff_at
                       ) AS pre_match_snapshot_count,
                       COUNT(DISTINCT snapshot.match_id) FILTER (
                           WHERE snapshot.available_at < match.kickoff_at
                       ) AS pre_match_match_count,
                       COUNT(*) FILTER (
                           WHERE snapshot.time_precision = 'kickoff_bound'
                       ) AS kickoff_bound_snapshot_count,
                       COUNT(DISTINCT snapshot.match_id) FILTER (
                           WHERE snapshot.time_precision = 'kickoff_bound'
                       ) AS kickoff_bound_match_count,
                       COUNT(*) FILTER (
                           WHERE snapshot.available_at >= match.kickoff_at
                       ) AS post_kickoff_snapshot_count
                FROM market_snapshots AS snapshot
                JOIN matches AS match ON match.id = snapshot.match_id
                JOIN competitions AS competition ON competition.id = match.competition_id
                GROUP BY competition.source_competition_id, match.season, snapshot.market_type
                ORDER BY competition.source_competition_id, match.season, snapshot.market_type
                """
            ).fetchall()
            market_summary_rows = connection.execute(
                """
                SELECT competition.source_competition_id, match.season,
                       COUNT(DISTINCT snapshot.match_id) FILTER (
                           WHERE snapshot.available_at < match.kickoff_at
                       ) AS pre_match_market_matches,
                       COUNT(DISTINCT snapshot.match_id) FILTER (
                           WHERE snapshot.time_precision = 'kickoff_bound'
                       ) AS kickoff_bound_market_matches,
                       COUNT(DISTINCT snapshot.match_id) FILTER (
                           WHERE snapshot.available_at >= match.kickoff_at
                       ) AS post_kickoff_market_matches
                FROM market_snapshots AS snapshot
                JOIN matches AS match ON match.id = snapshot.match_id
                JOIN competitions AS competition ON competition.id = match.competition_id
                GROUP BY competition.source_competition_id, match.season
                """
            ).fetchall()

        matches_by_scope = {
            (row[0], row[1]): {
                "match_count": int(row[2]),
                "complete_full_time_matches": int(row[3]),
                "complete_half_time_matches": int(row[4]),
                "missing_half_time_matches": int(row[5]),
            }
            for row in match_rows
        }
        markets_by_scope: dict[tuple[str, str], list[DataAuditMarketCoverage]] = {}
        for row in market_rows:
            key = (row[0], row[1])
            markets_by_scope.setdefault(key, []).append(
                DataAuditMarketCoverage(
                    market_type=row[2],
                    snapshot_count=int(row[3]),
                    match_count=int(row[4]),
                    pre_match_snapshot_count=int(row[5]),
                    pre_match_match_count=int(row[6]),
                    kickoff_bound_snapshot_count=int(row[7]),
                    kickoff_bound_match_count=int(row[8]),
                    post_kickoff_snapshot_count=int(row[9]),
                )
            )

        market_summary_by_scope = {
            (row[0], row[1]): {
                "pre_match_market_matches": int(row[2]),
                "kickoff_bound_market_matches": int(row[3]),
                "post_kickoff_market_matches": int(row[4]),
            }
            for row in market_summary_rows
        }

        scopes: list[DataAuditScope] = []
        for source_file in requests:
            seasons = _audit_seasons(source_file)
            match_stats = _sum_match_audit_stats(
                matches_by_scope,
                source_file.competition_code,
                seasons,
            )
            market_stats = _sum_market_audit_stats(
                market_summary_by_scope,
                source_file.competition_code,
                seasons,
            )
            market_coverage = _merge_market_coverage(
                markets_by_scope,
                source_file.competition_code,
                seasons,
            )
            complete_full_time = match_stats["complete_full_time_matches"]
            complete_half_time = match_stats["complete_half_time_matches"]
            scopes.append(
                DataAuditScope(
                    competition_code=source_file.competition_code,
                    competition_name=source_file.competition_name,
                    country_code=source_file.country_code,
                    season=source_file.season,
                    match_count=match_stats["match_count"],
                    complete_full_time_matches=complete_full_time,
                    complete_half_time_matches=complete_half_time,
                    missing_half_time_matches=match_stats["missing_half_time_matches"],
                    half_time_result_matches=complete_half_time,
                    total_goals_matches=complete_full_time,
                    label_ready_matches=complete_full_time,
                    **market_stats,
                    markets=market_coverage,
                )
            )

        summary = DataAuditSummary(
            catalog_competitions=len({item.competition_code for item in requests}),
            imported_competitions=len({
                item.competition_code for item in scopes if item.match_count > 0
            }),
            requested_files=len(scopes),
            files_with_matches=sum(item.match_count > 0 for item in scopes),
            missing_files=sum(item.match_count == 0 for item in scopes),
            total_matches=sum(item.match_count for item in scopes),
            complete_full_time_matches=sum(item.complete_full_time_matches for item in scopes),
            complete_half_time_matches=sum(item.complete_half_time_matches for item in scopes),
            missing_half_time_matches=sum(item.missing_half_time_matches for item in scopes),
            half_time_result_matches=sum(item.half_time_result_matches for item in scopes),
            total_goals_matches=sum(item.total_goals_matches for item in scopes),
            label_ready_matches=sum(item.label_ready_matches for item in scopes),
            pre_match_market_matches=sum(item.pre_match_market_matches for item in scopes),
            kickoff_bound_market_matches=sum(item.kickoff_bound_market_matches for item in scopes),
            post_kickoff_market_matches=sum(item.post_kickoff_market_matches for item in scopes),
        )
        return DataAuditReport(start_year, end_year, len(scopes), summary, tuple(scopes))

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
                    match.id, CAST(match.kickoff_at AS VARCHAR), competition.source_competition_id,
                    competition.name_zh, match.season, home.name_zh, away.name_zh,
                    match.half_time_home_score, match.half_time_away_score, match.home_score,
                    match.away_score, match.kickoff_time_precision
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
                        WHERE (? IS NULL OR source = ?)
                        ORDER BY source_competition_id
                        """, [query.source, query.source]
                    ).fetchall()
                ),
                seasons=tuple(
                    row[0]
                    for row in connection.execute(
                        "SELECT DISTINCT season FROM matches WHERE (? IS NULL OR source = ?) ORDER BY season",
                        [query.source, query.source],
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
                competition_code=row[2],
                competition_name=row[3],
                competition=row[3],
                season=row[4],
                home_team=row[5],
                away_team=row[6],
                half_time_home_score=row[7],
                half_time_away_score=row[8],
                home_score=row[9],
                away_score=row[10],
                markets=markets_by_match.get(row[0], ()),
                kickoff_time_precision=row[11],
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

    def get_match_market_history(self, match_id: str) -> MatchMarketHistoryView | None:
        """按核心比赛 ID 读取完整体彩赔率时间线，不复用列表页的最新快照。"""
        with self._connect() as connection:
            match_row = connection.execute(
                """
                SELECT match.id, competition.source_competition_id, competition.name_zh,
                       match.season, CAST(match.kickoff_at AS VARCHAR),
                       match.kickoff_time_precision, home.name_zh, away.name_zh,
                       match.half_time_home_score, match.half_time_away_score,
                       match.home_score, match.away_score, sporttery.match_id
                FROM matches AS match
                JOIN competitions AS competition ON competition.id = match.competition_id
                JOIN teams AS home ON home.id = match.home_team_id
                JOIN teams AS away ON away.id = match.away_team_id
                JOIN sporttery_matches AS sporttery
                  ON CAST(sporttery.match_id AS VARCHAR) = match.source_match_id
                WHERE match.id = ? AND match.source = 'sporttery'
                """,
                [match_id],
            ).fetchone()
            if match_row is None:
                return None

            rows = connection.execute(
                """
                SELECT snapshot.id, snapshot.market_type, CAST(snapshot.handicap AS DOUBLE),
                       snapshot.handicap_key, CAST(snapshot.captured_at AS VARCHAR),
                       outcome.outcome_code, outcome.odds_value
                FROM sporttery_bonus_snapshots AS snapshot
                LEFT JOIN sporttery_bonus_outcomes AS outcome
                  ON outcome.snapshot_id = snapshot.id
                WHERE snapshot.match_id = ?
                ORDER BY snapshot.captured_at, snapshot.id, outcome.outcome_code
                """,
                [match_row[12]],
            ).fetchall()

        return _build_match_market_history(match_row, rows)

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

    def _bulk_write_matches(
        self,
        connection: duckdb.DuckDBPyConnection,
        competition_id: str,
        source_file: SourceFile,
        parsed_file: ParsedFile,
    ) -> int:
        """先在内存中整理自然键，再以少量批量语句写入一份文件。

        旧实现每场比赛都要查询球队、别名、比赛、市场和赔率结果，380 场比赛
        会产生数千次 Python 到 DuckDB 的往返。这里先生成稳定 ID 并一次性校验
        已有事实，再按外键顺序批量写入，重复导入仍保持幂等和冲突可检测。
        """
        teams_by_alias: dict[str, _PreparedTeam] = {}
        matches_by_id: dict[str, _PreparedMatch] = {}
        markets_by_id: dict[str, _PreparedMarket] = {}
        outcomes_by_id: dict[str, _PreparedOutcome] = {}

        def team_id_for(alias: str) -> str:
            normalized = normalize_alias(alias)
            if not normalized:
                raise RepositoryError("invalid_record")
            prepared = teams_by_alias.get(normalized)
            if prepared is None:
                team_id = stable_id("team", source_file.source, normalized)
                prepared = _PreparedTeam(
                    team_id=team_id,
                    alias_id=stable_id("team_alias", source_file.source, normalized),
                    source=source_file.source,
                    alias=alias.strip(),
                    normalized_alias=normalized,
                )
                teams_by_alias[normalized] = prepared
            return prepared.team_id

        for match in parsed_file.matches:
            kickoff_at = _utc(match.kickoff_at)
            match_season = match.season or source_file.season
            home_team_id = team_id_for(match.home_team)
            away_team_id = team_id_for(match.away_team)
            natural_identity = ":".join(
                (
                    source_file.source,
                    source_file.competition_code,
                    match_season,
                    normalize_alias(match.home_team),
                    normalize_alias(match.away_team),
                    kickoff_at.isoformat(),
                )
            )
            match_id = stable_id("match", natural_identity)
            match_facts = (
                competition_id,
                match_season,
                _epoch_milliseconds(kickoff_at),
                home_team_id,
                away_team_id,
                match.home_score,
                match.away_score,
                match.half_time_home_score,
                match.half_time_away_score,
                _epoch_milliseconds(kickoff_at),
            )
            prepared_markets: list[_PreparedMarket] = []
            for market in match.markets:
                prepared_market = self._prepare_market(
                    match_id,
                    kickoff_at,
                    market,
                    outcomes_by_id,
                )
                previous_market = markets_by_id.get(prepared_market.snapshot_id)
                if previous_market is not None and previous_market.facts != prepared_market.facts:
                    raise RepositoryError("source_fact_conflict")
                if previous_market is None:
                    markets_by_id[prepared_market.snapshot_id] = prepared_market
                prepared_markets.append(prepared_market)

            prepared_match = _PreparedMatch(
                match_id=match_id,
                row=(
                    match_id,
                    competition_id,
                    match_season,
                    _epoch_milliseconds(kickoff_at),
                    home_team_id,
                    away_team_id,
                    match.home_score,
                    match.away_score,
                    match.half_time_home_score,
                    match.half_time_away_score,
                    "finished",
                    source_file.source,
                    natural_identity,
                    _epoch_milliseconds(kickoff_at),
                ),
                facts=match_facts,
                markets=tuple(prepared_markets),
            )
            previous_match = matches_by_id.get(match_id)
            if previous_match is not None and previous_match.facts != prepared_match.facts:
                raise RepositoryError("source_fact_conflict")
            if previous_match is None:
                matches_by_id[match_id] = prepared_match

        teams = tuple(teams_by_alias.values())
        matches = tuple(matches_by_id.values())
        markets = tuple(markets_by_id.values())
        outcomes = tuple(outcomes_by_id.values())

        # read_csv（CSV 批量读取）只把每个临时文件绑定一次，避免把数千个业务值
        # 作为 Python 参数逐个传给 DuckDB。临时文件在事务结束后立即删除。
        with tempfile.TemporaryDirectory(
            prefix=".football-import-",
            dir=str(self.database_path.parent),
        ) as stage_root:
            stage_tables = {
                "teams": _create_stage_table(
                    connection,
                    Path(stage_root) / "teams.csv",
                    "stage_import_teams",
                    ("team_id", "alias"),
                    {"team_id": "VARCHAR", "alias": "VARCHAR"},
                    tuple((team.team_id, team.alias) for team in teams),
                ),
                "aliases": _create_stage_table(
                    connection,
                    Path(stage_root) / "aliases.csv",
                    "stage_import_aliases",
                    ("alias_id", "team_id", "source", "alias", "normalized_alias"),
                    {
                        "alias_id": "VARCHAR",
                        "team_id": "VARCHAR",
                        "source": "VARCHAR",
                        "alias": "VARCHAR",
                        "normalized_alias": "VARCHAR",
                    },
                    tuple(
                        (
                            team.alias_id,
                            team.team_id,
                            team.source,
                            team.alias,
                            team.normalized_alias,
                        )
                        for team in teams
                    ),
                ),
                "matches": _create_stage_table(
                    connection,
                    Path(stage_root) / "matches.csv",
                    "stage_import_matches",
                    (
                        "id",
                        "competition_id",
                        "season",
                        "kickoff_ms",
                        "home_team_id",
                        "away_team_id",
                        "home_score",
                        "away_score",
                        "half_time_home_score",
                        "half_time_away_score",
                        "status",
                        "source",
                        "source_match_id",
                        "available_ms",
                    ),
                    {
                        "id": "VARCHAR",
                        "competition_id": "VARCHAR",
                        "season": "VARCHAR",
                        "kickoff_ms": "BIGINT",
                        "home_team_id": "VARCHAR",
                        "away_team_id": "VARCHAR",
                        "home_score": "INTEGER",
                        "away_score": "INTEGER",
                        "half_time_home_score": "INTEGER",
                        "half_time_away_score": "INTEGER",
                        "status": "VARCHAR",
                        "source": "VARCHAR",
                        "source_match_id": "VARCHAR",
                        "available_ms": "BIGINT",
                    },
                    tuple(match.row for match in matches),
                ),
                "markets": _create_stage_table(
                    connection,
                    Path(stage_root) / "markets.csv",
                    "stage_import_markets",
                    (
                        "id",
                        "match_id",
                        "provider",
                        "source",
                        "market_type",
                        "handicap",
                        "handicap_key",
                        "captured_ms",
                        "available_ms",
                        "stage",
                        "time_precision",
                    ),
                    {
                        "id": "VARCHAR",
                        "match_id": "VARCHAR",
                        "provider": "VARCHAR",
                        "source": "VARCHAR",
                        "market_type": "VARCHAR",
                        "handicap": "DOUBLE",
                        "handicap_key": "VARCHAR",
                        "captured_ms": "BIGINT",
                        "available_ms": "BIGINT",
                        "stage": "VARCHAR",
                        "time_precision": "VARCHAR",
                    },
                    tuple(
                        (
                            market.snapshot_id,
                            market.row[1],
                            market.row[2],
                            market.row[3],
                            market.row[4],
                            market.row[5],
                            market.row[6],
                            _epoch_milliseconds(market.row[7]),
                            _epoch_milliseconds(market.row[8]),
                            market.row[9],
                            market.row[10],
                        )
                        for market in markets
                    ),
                ),
                "outcomes": _create_stage_table(
                    connection,
                    Path(stage_root) / "outcomes.csv",
                    "stage_import_outcomes",
                    ("id", "snapshot_id", "outcome_code", "odds_value", "source_field"),
                    {
                        "id": "VARCHAR",
                        "snapshot_id": "VARCHAR",
                        "outcome_code": "VARCHAR",
                        "odds_value": "DOUBLE",
                        "source_field": "VARCHAR",
                    },
                    tuple(outcome.row for outcome in outcomes),
                ),
            }
            try:
                _validate_staged_facts(connection, stage_tables)
                existing_matches = int(
                    connection.execute(
                        """
                        SELECT COUNT(*)
                        FROM stage_import_matches AS staged
                        JOIN matches AS existing ON existing.id = staged.id
                        """
                    ).fetchone()[0]
                )
                _insert_staged_rows(connection, stage_tables)
            finally:
                for table_name in stage_tables.values():
                    connection.execute(f"DROP TABLE IF EXISTS {table_name}")

        return len(matches) - existing_matches

    @staticmethod
    def _prepare_market(
        match_id: str,
        kickoff_at: datetime,
        market,
        outcomes_by_id: dict[str, _PreparedOutcome],
    ) -> _PreparedMarket:
        captured_at = _utc(market.captured_at)
        available_at = _utc(market.available_at)
        if captured_at > available_at:
            raise RepositoryError("invalid_record")
        if market.time_precision == "kickoff_bound" and (
            market.stage != "closing"
            or captured_at != kickoff_at
            or available_at != kickoff_at
        ):
            raise RepositoryError("invalid_record")

        handicap_key = "none" if market.line is None else f"{market.line:.2f}"
        snapshot_id = stable_id(
            "market_snapshot",
            match_id,
            market.source,
            market.provider,
            market.market_type,
            handicap_key,
            captured_at.isoformat(),
            market.stage,
        )
        snapshot_facts = (
            match_id,
            market.provider,
            market.source,
            market.market_type,
            handicap_key,
            _epoch_milliseconds(captured_at),
            _epoch_milliseconds(available_at),
            market.stage,
            market.time_precision,
        )
        outcomes: list[_PreparedOutcome] = []
        for outcome_code, odds_value, source_field in market.outcomes:
            outcome_id = stable_id("market_outcome", snapshot_id, outcome_code)
            prepared_outcome = _PreparedOutcome(
                outcome_id=outcome_id,
                row=(outcome_id, snapshot_id, outcome_code, odds_value, source_field),
                facts=(odds_value, source_field),
            )
            previous_outcome = outcomes_by_id.get(outcome_id)
            if previous_outcome is not None and previous_outcome.facts != prepared_outcome.facts:
                raise RepositoryError("source_fact_conflict")
            if previous_outcome is None:
                outcomes_by_id[outcome_id] = prepared_outcome
            outcomes.append(prepared_outcome)

        return _PreparedMarket(
            snapshot_id=snapshot_id,
            row=(
                snapshot_id,
                match_id,
                market.provider,
                market.source,
                market.market_type,
                market.line,
                handicap_key,
                captured_at,
                available_at,
                market.stage,
                market.time_precision,
            ),
            facts=snapshot_facts,
            outcomes=tuple(outcomes),
        )

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
        match_season = match.season or source_file.season
        natural_identity = ":".join((source_file.source, source_file.competition_code, match_season, normalize_alias(match.home_team), normalize_alias(match.away_team), kickoff_at.isoformat()))
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
        facts = (competition_id, match_season, kickoff_at, home_id, away_id, match.home_score, match.away_score, match.half_time_home_score, match.half_time_away_score, kickoff_at)
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


def _execute_set_insert(
    connection,
    sql_prefix: str,
    rows: tuple[tuple[object, ...], ...],
    *,
    chunk_size: int = 500,
) -> None:
    """用单条多值 INSERT 批量写入，避免 executemany 逐行执行。

    每 500 行分一批是为了控制 SQL 文本和参数数量；每批仍只有一次数据库
    往返，且调用方已经处于同一个文件事务中，失败会整体回滚。
    """
    if not rows:
        return
    width = len(rows[0])
    if width < 1 or any(len(row) != width for row in rows):
        raise RepositoryError("invalid_record")
    if chunk_size < 1:
        raise ValueError("chunk_size_must_be_positive")

    value_placeholders = f"({', '.join('?' for _ in range(width))})"
    for offset in range(0, len(rows), chunk_size):
        batch = rows[offset : offset + chunk_size]
        sql = sql_prefix + ", ".join(value_placeholders for _ in batch)
        parameters = [value for row in batch for value in row]
        connection.execute(sql, parameters)


def _create_stage_table(
    connection,
    path: Path,
    table_name: str,
    headers: tuple[str, ...],
    columns: dict[str, str],
    rows: tuple[tuple[object, ...], ...],
) -> str:
    """把一组已验证记录写成临时 CSV，并注册为 DuckDB 临时表。"""
    if any(len(row) != len(headers) for row in rows):
        raise RepositoryError("invalid_record")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(headers)
        writer.writerows(rows)

    column_sql = "{" + ", ".join(
        f"'{name}': '{column_type}'" for name, column_type in columns.items()
    ) + "}"
    connection.execute(
        f"""
        CREATE TEMP TABLE {table_name} AS
        SELECT * FROM read_csv(
            ?,
            header = true,
            nullstr = '',
            columns = {column_sql}
        )
        """,
        [str(path)],
    )
    return table_name


def _validate_staged_facts(connection, stage_tables: dict[str, str]) -> None:
    """用集合查询校验幂等重跑，避免为每个稳定 ID 绑定一个参数。"""
    conflict_queries = (
        """
        SELECT 1
        FROM stage_import_aliases AS staged
        JOIN team_aliases AS existing
          ON existing.source = staged.source
         AND existing.normalized_alias = staged.normalized_alias
        WHERE existing.id IS DISTINCT FROM staged.alias_id
           OR existing.team_id IS DISTINCT FROM staged.team_id
        LIMIT 1
        """,
        """
        SELECT 1
        FROM stage_import_matches AS staged
        JOIN matches AS existing ON existing.id = staged.id
        WHERE existing.competition_id IS DISTINCT FROM staged.competition_id
           OR existing.season IS DISTINCT FROM staged.season
           OR epoch_ms(existing.kickoff_at) IS DISTINCT FROM staged.kickoff_ms
           OR existing.home_team_id IS DISTINCT FROM staged.home_team_id
           OR existing.away_team_id IS DISTINCT FROM staged.away_team_id
           OR existing.home_score IS DISTINCT FROM staged.home_score
           OR existing.away_score IS DISTINCT FROM staged.away_score
           OR existing.half_time_home_score IS DISTINCT FROM staged.half_time_home_score
           OR existing.half_time_away_score IS DISTINCT FROM staged.half_time_away_score
           OR epoch_ms(existing.available_at) IS DISTINCT FROM staged.available_ms
        LIMIT 1
        """,
        """
        SELECT 1
        FROM stage_import_markets AS staged
        JOIN market_snapshots AS existing ON existing.id = staged.id
        WHERE existing.match_id IS DISTINCT FROM staged.match_id
           OR existing.provider IS DISTINCT FROM staged.provider
           OR existing.source IS DISTINCT FROM staged.source
           OR existing.market_type IS DISTINCT FROM staged.market_type
           OR existing.handicap_key IS DISTINCT FROM staged.handicap_key
           OR epoch_ms(existing.captured_at) IS DISTINCT FROM staged.captured_ms
           OR epoch_ms(existing.available_at) IS DISTINCT FROM staged.available_ms
           OR existing.stage IS DISTINCT FROM staged.stage
           OR existing.time_precision IS DISTINCT FROM staged.time_precision
        LIMIT 1
        """,
        """
        SELECT 1
        FROM stage_import_outcomes AS staged
        JOIN market_outcomes AS existing ON existing.id = staged.id
        WHERE existing.odds_value IS DISTINCT FROM staged.odds_value
           OR existing.source_field IS DISTINCT FROM staged.source_field
        LIMIT 1
        """,
    )
    for query in conflict_queries:
        if connection.execute(query).fetchone() is not None:
            raise RepositoryError("source_fact_conflict")


def _insert_staged_rows(connection, stage_tables: dict[str, str]) -> None:
    """按外键顺序把临时表一次性写入业务表。"""
    connection.execute(
        f"""
        INSERT OR IGNORE INTO teams (id, name_zh)
        SELECT team_id, alias FROM {stage_tables['teams']}
        """
    )
    connection.execute(
        f"""
        INSERT OR IGNORE INTO team_aliases
            (id, team_id, source, alias, normalized_alias)
        SELECT alias_id, team_id, source, alias, normalized_alias
        FROM {stage_tables['aliases']}
        """
    )
    connection.execute(
        f"""
        INSERT OR IGNORE INTO matches (
            id, competition_id, season, kickoff_at, home_team_id, away_team_id,
            home_score, away_score, half_time_home_score, half_time_away_score,
            status, source, source_match_id, available_at
        )
        SELECT
            id, competition_id, season,
            to_timestamp(kickoff_ms / 1000.0),
            home_team_id, away_team_id,
            home_score, away_score, half_time_home_score, half_time_away_score,
            status, source, source_match_id,
            to_timestamp(available_ms / 1000.0)
        FROM {stage_tables['matches']}
        """
    )
    connection.execute(
        f"""
        INSERT OR IGNORE INTO market_snapshots
            (id, match_id, provider, source, market_type, handicap, handicap_key,
             captured_at, available_at, stage, time_precision)
        SELECT
            id, match_id, provider, source, market_type, handicap, handicap_key,
            to_timestamp(captured_ms / 1000.0),
            to_timestamp(available_ms / 1000.0),
            stage, time_precision
        FROM {stage_tables['markets']}
        """
    )
    connection.execute(
        f"""
        INSERT OR IGNORE INTO market_outcomes
            (id, snapshot_id, outcome_code, odds_value, source_field)
        SELECT id, snapshot_id, outcome_code, odds_value, source_field
        FROM {stage_tables['outcomes']}
        """
    )


def _select_by_ids(
    connection,
    table: str,
    columns: str,
    ids: tuple[str, ...],
) -> tuple[tuple[object, ...], ...]:
    """按内部生成的稳定 ID 批量查询，避免为每条事实单独往返数据库。"""
    if not ids:
        return ()
    placeholders = ", ".join("?" for _ in ids)
    return tuple(
        connection.execute(
            f"SELECT {columns} FROM {table} WHERE id IN ({placeholders})",
            list(ids),
        ).fetchall()
    )


def _validate_existing_teams(
    connection,
    source: str,
    teams: tuple[_PreparedTeam, ...],
) -> None:
    """检查来源别名的既有归属，防止批量 INSERT OR IGNORE 掩盖冲突。"""
    if not teams:
        return
    by_normalized = {team.normalized_alias: team for team in teams}
    normalized_aliases = tuple(by_normalized)
    placeholders = ", ".join("?" for _ in normalized_aliases)
    existing = connection.execute(
        f"""
        SELECT id, team_id, normalized_alias
        FROM team_aliases
        WHERE source = ? AND normalized_alias IN ({placeholders})
        """,
        [source, *normalized_aliases],
    ).fetchall()
    for alias_id, team_id, normalized_alias in existing:
        expected = by_normalized[normalized_alias]
        if alias_id != expected.alias_id or team_id != expected.team_id:
            raise RepositoryError("source_fact_conflict")

    by_alias_id = {team.alias_id: team for team in teams}
    for alias_id, team_id in _select_by_ids(
        connection,
        "team_aliases",
        "id, team_id",
        tuple(by_alias_id),
    ):
        expected = by_alias_id[alias_id]
        if team_id != expected.team_id:
            raise RepositoryError("source_fact_conflict")


def _validate_existing_matches(
    connection,
    matches: tuple[_PreparedMatch, ...],
) -> set[str]:
    existing_ids: set[str] = set()
    by_id = {match.match_id: match for match in matches}
    for row in _select_by_ids(
        connection,
        "matches",
        "id, competition_id, season, epoch_ms(kickoff_at), home_team_id, away_team_id, "
        "home_score, away_score, half_time_home_score, half_time_away_score, "
        "epoch_ms(available_at)",
        tuple(by_id),
    ):
        match_id = row[0]
        expected = by_id[match_id]
        if tuple(row[1:]) != expected.facts:
            raise RepositoryError("source_fact_conflict")
        existing_ids.add(match_id)
    return existing_ids


def _validate_existing_markets(
    connection,
    markets: tuple[_PreparedMarket, ...],
) -> None:
    by_id = {market.snapshot_id: market for market in markets}
    for row in _select_by_ids(
        connection,
        "market_snapshots",
        "id, match_id, provider, source, market_type, handicap_key, "
        "epoch_ms(captured_at), epoch_ms(available_at), stage, time_precision",
        tuple(by_id),
    ):
        snapshot_id = row[0]
        if tuple(row[1:]) != by_id[snapshot_id].facts:
            raise RepositoryError("source_fact_conflict")


def _validate_existing_outcomes(
    connection,
    outcomes: tuple[_PreparedOutcome, ...],
) -> None:
    by_id = {outcome.outcome_id: outcome for outcome in outcomes}
    for row in _select_by_ids(
        connection,
        "market_outcomes",
        "id, odds_value, source_field",
        tuple(by_id),
    ):
        outcome_id = row[0]
        if tuple(row[1:]) != by_id[outcome_id].facts:
            raise RepositoryError("source_fact_conflict")


def _audit_seasons(source_file: SourceFile) -> tuple[str, ...]:
    """把一个请求文件展开为数据库中应被审计的实际赛季。"""
    if source_file.source_scope != "combined":
        return (source_file.season,)
    if source_file.start_year is None or source_file.end_year is None:
        return (source_file.season,)
    if source_file.season_style == "split_year":
        return tuple(
            f"{(year - 1) % 100:02d}{year % 100:02d}"
            for year in range(source_file.start_year + 1, source_file.end_year + 1)
        )
    return tuple(str(year) for year in range(source_file.start_year, source_file.end_year + 1))


def _sum_match_audit_stats(
    stats_by_scope: dict[tuple[str, str], dict[str, int]],
    competition_code: str,
    seasons: tuple[str, ...],
) -> dict[str, int]:
    fields = (
        "match_count",
        "complete_full_time_matches",
        "complete_half_time_matches",
        "missing_half_time_matches",
    )
    result = {field: 0 for field in fields}
    for season in seasons:
        row = stats_by_scope.get((competition_code, season))
        if row is None:
            continue
        for field in fields:
            result[field] += row[field]
    return result


def _sum_market_audit_stats(
    stats_by_scope: dict[tuple[str, str], dict[str, int]],
    competition_code: str,
    seasons: tuple[str, ...],
) -> dict[str, int]:
    fields = (
        "pre_match_market_matches",
        "kickoff_bound_market_matches",
        "post_kickoff_market_matches",
    )
    result = {field: 0 for field in fields}
    for season in seasons:
        row = stats_by_scope.get((competition_code, season))
        if row is None:
            continue
        for field in fields:
            result[field] += row[field]
    return result


def _merge_market_coverage(
    markets_by_scope: dict[tuple[str, str], list[DataAuditMarketCoverage]],
    competition_code: str,
    seasons: tuple[str, ...],
) -> tuple[DataAuditMarketCoverage, ...]:
    totals: dict[str, list[int]] = {}
    for season in seasons:
        for market in markets_by_scope.get((competition_code, season), ()):
            values = totals.setdefault(market.market_type, [0] * 7)
            values[0] += market.snapshot_count
            values[1] += market.match_count
            values[2] += market.pre_match_snapshot_count
            values[3] += market.pre_match_match_count
            values[4] += market.kickoff_bound_snapshot_count
            values[5] += market.kickoff_bound_match_count
            values[6] += market.post_kickoff_snapshot_count
    return tuple(
        DataAuditMarketCoverage(market_type, *values)
        for market_type, values in sorted(totals.items())
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
    if query.source:
        conditions.append("match.source = ?")
        parameters.append(query.source)
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


def _build_match_market_history(
    match_row: tuple[object, ...],
    rows: list[tuple[object, ...]],
) -> MatchMarketHistoryView:
    """把联表结果按玩法、盘口和快照分层，防止同一发布时间的数据互相覆盖。"""
    grouped: dict[
        tuple[str, str],
        dict[str, object],
    ] = {}
    for snapshot_id, market_type, line, line_key, captured_at, outcome_code, odds_value in rows:
        group_key = (str(market_type), str(line_key))
        group = grouped.setdefault(
            group_key,
            {
                "market_type": str(market_type),
                "line": float(line) if line is not None else None,
                "snapshots": {},
            },
        )
        snapshots = group["snapshots"]
        assert isinstance(snapshots, dict)
        snapshot = snapshots.setdefault(
            str(snapshot_id),
            {
                "captured_at": _parse_database_timestamp(str(captured_at)),
                "outcomes": {},
            },
        )
        outcomes = snapshot["outcomes"]
        assert isinstance(outcomes, dict)
        if outcome_code is not None:
            outcomes[str(outcome_code)] = float(odds_value)

    market_groups: list[MarketHistoryGroupView] = []
    for group in grouped.values():
        market_type = str(group["market_type"])
        snapshots_by_id = group["snapshots"]
        assert isinstance(snapshots_by_id, dict)
        outcome_codes = _OUTCOME_ORDER.get(market_type)
        if outcome_codes is None:
            outcome_codes = tuple(sorted({
                code
                for snapshot in snapshots_by_id.values()
                for code in snapshot["outcomes"]
            }))
        snapshots = tuple(
            MarketHistorySnapshotView(
                captured_at=snapshot["captured_at"],
                available_at=snapshot["captured_at"],
                outcomes=tuple(
                    (code, snapshot["outcomes"][code])
                    for code in outcome_codes
                    if code in snapshot["outcomes"]
                ),
            )
            for snapshot in sorted(
                snapshots_by_id.values(), key=lambda item: item["captured_at"]
            )
        )
        market_groups.append(
            MarketHistoryGroupView(
                market_type=market_type,
                line=group["line"],
                source="sporttery",
                provider="china_sports_lottery",
                stage="closing",
                time_precision="exact",
                outcome_codes=outcome_codes,
                snapshots=snapshots,
            )
        )

    market_groups.sort(
        key=lambda group: (
            _MARKET_ORDER.get(group.market_type, len(_MARKET_ORDER)),
            group.line is None,
            group.line if group.line is not None else 0.0,
        )
    )
    return MatchMarketHistoryView(
        id=str(match_row[0]),
        competition_code=str(match_row[1]),
        competition_name=str(match_row[2]),
        season=str(match_row[3]),
        kickoff_at=_parse_database_timestamp(str(match_row[4])),
        kickoff_time_precision=str(match_row[5]),
        home_team=str(match_row[6]),
        away_team=str(match_row[7]),
        half_time_home_score=match_row[8],
        half_time_away_score=match_row[9],
        home_score=match_row[10],
        away_score=match_row[11],
        markets=tuple(market_groups),
    )


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
            snapshot.match_id, snapshot.id, snapshot.provider, snapshot.source,
            snapshot.market_type, snapshot.stage, snapshot.time_precision,
            CAST(snapshot.captured_at AS VARCHAR), CAST(snapshot.available_at AS VARCHAR),
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
    current_time_precision: str | None = None
    current_source: str | None = None
    current_provider: str | None = None
    current_captured_at: datetime | None = None
    current_available_at: datetime | None = None
    current_line: float | None = None
    current_outcomes: list[tuple[str, float]] = []

    def finish_market() -> None:
        if (
            current_snapshot_id is None
            or current_match_id is None
            or current_type is None
            or current_stage is None
            or current_time_precision is None
            or current_source is None
            or current_provider is None
            or current_captured_at is None
            or current_available_at is None
        ):
            return
        grouped.setdefault(current_match_id, []).append(
            MatchMarketView(
                market_type=current_type,
                stage=current_stage,
                time_precision=current_time_precision,
                source=current_source,
                provider=current_provider,
                captured_at=current_captured_at,
                available_at=current_available_at,
                line=current_line,
                outcomes=tuple(current_outcomes),
            )
        )

    for (
        match_id,
        snapshot_id,
        provider,
        source,
        market_type,
        stage,
        time_precision,
        captured_at,
        available_at,
        line,
        outcome_code,
        odds_value,
    ) in rows:
        if snapshot_id != current_snapshot_id:
            finish_market()
            current_snapshot_id = snapshot_id
            current_match_id = match_id
            current_type = market_type
            current_stage = stage
            current_time_precision = time_precision
            current_source = source
            current_provider = provider
            current_captured_at = _parse_database_timestamp(captured_at)
            current_available_at = _parse_database_timestamp(available_at)
            current_line = float(line) if line is not None else None
            current_outcomes = []
        if outcome_code is not None:
            current_outcomes.append((outcome_code, float(odds_value)))
    finish_market()
    return {match_id: tuple(markets) for match_id, markets in grouped.items()}
