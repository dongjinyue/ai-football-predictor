"""中国竞彩事实的 DuckDB 幂等仓储。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb

from app.sporttery.models import (
    BonusSnapshot,
    FixedBonusRecord,
    MatchPageRecord,
    SportteryMatch,
)
from app.sporttery.storage import StoredResponse
from app.storage import initialize_database


_NAMESPACE = uuid.UUID("810f7a35-2c79-53cf-9560-d26e69ffcb52")


@dataclass(frozen=True)
class CoverageReport:
    """指定年份已经落库的数据覆盖摘要。"""

    year: int
    matches: int
    matches_with_bonus: int
    snapshots: int
    outcomes: int
    request_records: int
    snapshots_by_market: tuple[tuple[str, int], ...]


class SportteryRepository:
    """按原始响应为事务边界写入比赛和固定奖金。"""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        initialize_database(database_path)

    def import_match_page(self, page: MatchPageRecord, raw: StoredResponse) -> None:
        with duckdb.connect(str(self.database_path)) as connection:
            connection.execute("BEGIN TRANSACTION")
            try:
                match_ids = [match.match_id for match in page.matches]
                core_ids = {
                    match.match_id: _stable_id("core-match", str(match.match_id))
                    for match in page.matches
                }
                placeholders = ", ".join("?" for _ in match_ids)
                if match_ids:
                    existing_core_ids = {
                        str(row[0])
                        for row in connection.execute(
                            f"SELECT id FROM matches WHERE id IN ({placeholders})",
                            list(core_ids.values()),
                        ).fetchall()
                    }
                    existing_match_ids = {
                        int(row[0])
                        for row in connection.execute(
                            f"SELECT match_id FROM sporttery_matches WHERE match_id IN ({placeholders})",
                            match_ids,
                        ).fetchall()
                    }
                else:
                    existing_core_ids = set()
                    existing_match_ids = set()

                missing_core = [
                    match for match in page.matches
                    if core_ids[match.match_id] not in existing_core_ids
                ]
                self._sync_core_matches(connection, missing_core, raw)

                missing_matches = [
                    match for match in page.matches
                    if match.match_id not in existing_match_ids
                ]
                if missing_matches:
                    _insert_rows(
                        connection,
                        """
                        INSERT OR IGNORE INTO sporttery_matches (
                            match_id, core_match_id, match_date, match_number, match_number_label,
                            league_id, league_name, league_abbreviation,
                            home_team_id, home_team_name, home_team_full_name,
                            away_team_id, away_team_name, away_team_full_name,
                            half_time_home_score, half_time_away_score,
                            home_score, away_score, result, handicap,
                            result_status, pool_status, raw_sha256
                        ) VALUES
                        """,
                        "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        [
                            [
                                match.match_id, core_ids[match.match_id], match.match_date,
                                match.match_number, match.match_number_label, match.league_id,
                                match.league_name, match.league_abbreviation,
                                match.home_team_id, match.home_team,
                                match.home_team_full_name, match.away_team_id,
                                match.away_team, match.away_team_full_name,
                                match.half_time_home_score, match.half_time_away_score,
                                match.home_score, match.away_score, match.result,
                                match.handicap, match.result_status, match.pool_status,
                                raw.sha256,
                            ]
                            for match in missing_matches
                        ],
                    )
                self._insert_request(connection, "match_list", raw)
            except Exception:
                connection.execute("ROLLBACK")
                raise
            else:
                connection.execute("COMMIT")

    def import_fixed_bonus(self, record: FixedBonusRecord, raw: StoredResponse) -> None:
        with duckdb.connect(str(self.database_path)) as connection:
            connection.execute("BEGIN TRANSACTION")
            try:
                exists = connection.execute(
                    "SELECT 1 FROM sporttery_matches WHERE match_id = ?", [record.match_id]
                ).fetchone()
                if exists is None:
                    raise ValueError("unknown_match")
                snapshot_rows: list[list[object]] = []
                outcome_rows: list[list[object]] = []
                for snapshot in record.snapshots:
                    line_key = "none" if snapshot.line is None else format(snapshot.line, "g")
                    snapshot_id = _stable_id(
                        "snapshot", str(record.match_id), snapshot.market_type,
                        line_key, snapshot.captured_at.isoformat(),
                    )
                    snapshot_rows.append(
                        [snapshot_id, record.match_id, snapshot.market_type, snapshot.line,
                         line_key, snapshot.captured_at, raw.sha256]
                    )
                    for outcome_code, odds in snapshot.outcomes:
                        outcome_id = _stable_id("outcome", snapshot_id, outcome_code)
                        outcome_rows.append(
                            [outcome_id, snapshot_id, outcome_code, odds]
                        )

                if snapshot_rows:
                    _insert_rows(
                        connection,
                        """
                        INSERT OR IGNORE INTO sporttery_bonus_snapshots
                            (id, match_id, market_type, handicap, handicap_key,
                             captured_at, raw_sha256)
                        VALUES
                        """,
                        "(?, ?, ?, ?, ?, ?, ?)",
                        snapshot_rows,
                    )
                if outcome_rows:
                    _insert_rows(
                        connection,
                        """
                        INSERT OR IGNORE INTO sporttery_bonus_outcomes
                            (id, snapshot_id, outcome_code, odds_value)
                        VALUES
                        """,
                        "(?, ?, ?, ?)",
                        outcome_rows,
                    )
                if record.single_pools:
                    _insert_rows(
                        connection,
                        """
                        INSERT OR IGNORE INTO sporttery_single_pools
                            (match_id, pool_code, is_single, raw_sha256)
                        VALUES
                        """,
                        "(?, ?, ?, ?)",
                        [
                            [record.match_id, pool_code, is_single, raw.sha256]
                            for pool_code, is_single in record.single_pools
                        ],
                    )
                self._sync_core_markets(connection, record)
                self._insert_request(connection, "fixed_bonus", raw)
            except Exception:
                connection.execute("ROLLBACK")
                raise
            else:
                connection.execute("COMMIT")

    def coverage_report(self, year: int) -> CoverageReport:
        with duckdb.connect(str(self.database_path), read_only=True) as connection:
            match_count = int(connection.execute(
                "SELECT COUNT(*) FROM sporttery_matches WHERE year(match_date) = ?", [year]
            ).fetchone()[0])
            matches_with_bonus, snapshots, outcomes = connection.execute(
                """
                SELECT COUNT(DISTINCT snapshot.match_id), COUNT(DISTINCT snapshot.id),
                       COUNT(outcome.id)
                FROM sporttery_bonus_snapshots AS snapshot
                JOIN sporttery_matches AS match ON match.match_id = snapshot.match_id
                LEFT JOIN sporttery_bonus_outcomes AS outcome ON outcome.snapshot_id = snapshot.id
                WHERE year(match.match_date) = ?
                """,
                [year],
            ).fetchone()
            by_market = tuple(
                (str(row[0]), int(row[1]))
                for row in connection.execute(
                    """
                    SELECT snapshot.market_type, COUNT(*)
                    FROM sporttery_bonus_snapshots AS snapshot
                    JOIN sporttery_matches AS match ON match.match_id = snapshot.match_id
                    WHERE year(match.match_date) = ?
                    GROUP BY snapshot.market_type ORDER BY snapshot.market_type
                    """,
                    [year],
                ).fetchall()
            )
            requests = int(connection.execute(
                "SELECT COUNT(*) FROM sporttery_requests WHERE year(fetched_at) >= 2000"
            ).fetchone()[0])
        return CoverageReport(
            year=year,
            matches=match_count,
            matches_with_bonus=int(matches_with_bonus),
            snapshots=int(snapshots),
            outcomes=int(outcomes),
            request_records=requests,
            snapshots_by_market=by_market,
        )

    @staticmethod
    def _insert_request(connection, kind: str, raw: StoredResponse) -> None:
        request_key = _stable_id("request", kind, str(raw.path))
        connection.execute(
            """
            INSERT OR IGNORE INTO sporttery_requests
                (request_key, request_kind, request_url, local_path, sha256,
                 status_code, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [request_key, kind, raw.request_url, str(raw.path), raw.sha256,
            raw.status_code, raw.fetched_at],
        )

    @staticmethod
    def _sync_core_matches(
        connection,
        matches: list[SportteryMatch],
        raw: StoredResponse,
    ) -> None:
        """按页批量同步历史浏览表，并明确标记只有比赛日期。"""
        if not matches:
            return

        competitions: dict[str, list[object]] = {}
        teams: dict[int, list[object]] = {}
        aliases: dict[int, list[object]] = {}
        match_rows: list[list[object]] = []
        for match in matches:
            competition_code = (
                f"JC{match.league_id}"
                if match.league_id > 0
                else f"JC0-{_stable_id('league-name', match.league_name)[:8]}"
            )
            competition_id = _stable_id("core-competition", competition_code)
            competitions[competition_code] = [
                competition_id, match.league_name, competition_code,
            ]
            team_rows = (
                (match.home_team_id, match.home_team_full_name or match.home_team),
                (match.away_team_id, match.away_team_full_name or match.away_team),
            )
            core_team_ids: list[str] = []
            for source_team_id, name in team_rows:
                team_id = _stable_id("core-team", str(source_team_id))
                alias_id = _stable_id("core-team-alias", str(source_team_id))
                teams[source_team_id] = [team_id, name]
                aliases[source_team_id] = [
                    alias_id, team_id, name, f"sporttery:{source_team_id}",
                ]
                core_team_ids.append(team_id)

            # 中午只作为不跨日期的排序锚点，并非真实开球时刻。
            kickoff_anchor = datetime.combine(
                match.match_date, time(12, 0), tzinfo=ZoneInfo("Asia/Shanghai")
            ).astimezone(ZoneInfo("UTC"))
            status = "finished" if match.home_score is not None else "cancelled"
            match_rows.append([
                _stable_id("core-match", str(match.match_id)), competition_id,
                str(match.match_date.year), kickoff_anchor, core_team_ids[0],
                core_team_ids[1], match.home_score, match.away_score, status,
                str(match.match_id), raw.fetched_at, match.half_time_home_score,
                match.half_time_away_score,
            ])

        _insert_rows(
            connection,
            """
            INSERT OR IGNORE INTO competitions
                (id, name_zh, source, source_competition_id)
            VALUES
            """,
            "(?, ?, 'sporttery', ?)",
            list(competitions.values()),
        )
        _insert_rows(
            connection,
            "INSERT OR IGNORE INTO teams (id, name_zh) VALUES",
            "(?, ?)",
            list(teams.values()),
        )
        _insert_rows(
            connection,
            """
            INSERT OR IGNORE INTO team_aliases
                (id, team_id, source, alias, normalized_alias)
            VALUES
            """,
            "(?, ?, 'sporttery', ?, ?)",
            list(aliases.values()),
        )
        _insert_rows(
            connection,
            """
            INSERT OR IGNORE INTO matches (
                id, competition_id, season, kickoff_at, home_team_id, away_team_id,
                home_score, away_score, status, source, source_match_id,
                available_at, half_time_home_score, half_time_away_score,
                kickoff_time_precision
            ) VALUES
            """,
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, 'sporttery', ?, ?, ?, ?, 'date_only')",
            match_rows,
        )

    @staticmethod
    def _sync_core_markets(connection, record: FixedBonusRecord) -> None:
        # 兼容早期 core_match_id 为空且已被外键引用、无法再 UPDATE 的历史行。
        core_match_id = _stable_id("core-match", str(record.match_id))
        latest: dict[tuple[str, str], BonusSnapshot] = {}
        for snapshot in record.snapshots:
            line_key = "none" if snapshot.line is None else format(snapshot.line, "g")
            key = (snapshot.market_type, line_key)
            existing = latest.get(key)
            if existing is None or snapshot.captured_at > existing.captured_at:
                latest[key] = snapshot

        snapshot_rows: list[list[object]] = []
        outcome_rows: list[list[object]] = []
        for (market_type, _line_key), snapshot in latest.items():
            core_line_key = "none" if snapshot.line is None else f"{snapshot.line:.2f}"
            snapshot_id = _stable_id(
                "core-market", core_match_id, market_type, core_line_key,
                snapshot.captured_at.isoformat(),
            )
            odds = dict(snapshot.outcomes)
            snapshot_rows.append(
                [
                    snapshot_id, core_match_id, market_type, snapshot.line, core_line_key,
                    odds.get("home"), odds.get("draw"), odds.get("away"),
                    snapshot.captured_at, snapshot.captured_at,
                ]
            )
            for outcome_code, odds_value in snapshot.outcomes:
                outcome_id = _stable_id("core-outcome", snapshot_id, outcome_code)
                outcome_rows.append(
                    [outcome_id, snapshot_id, outcome_code, odds_value]
                )

        if snapshot_rows:
            _insert_rows(
                connection,
                """
                INSERT OR IGNORE INTO market_snapshots (
                    id, match_id, provider, source, market_type, handicap,
                    handicap_key, home_value, draw_value, away_value,
                    captured_at, available_at, stage, time_precision
                ) VALUES
                """,
                "(?, ?, 'china_sports_lottery', 'sporttery', ?, ?, ?, ?, ?, ?, ?, ?, 'closing', 'exact')",
                snapshot_rows,
            )
        if outcome_rows:
            _insert_rows(
                connection,
                """
                INSERT OR IGNORE INTO market_outcomes
                    (id, snapshot_id, outcome_code, odds_value, source_field)
                VALUES
                """,
                "(?, ?, ?, ?, 'sporttery.fixed_bonus')",
                outcome_rows,
            )


def _stable_id(kind: str, *parts: str) -> str:
    return str(uuid.uuid5(_NAMESPACE, ":".join((kind, *parts))))


def _insert_rows(connection, statement: str, row_template: str, rows: list[list[object]]) -> None:
    """用一条多行 VALUES 语句写入，避免 executemany 逐行往返。"""
    if not rows:
        return
    values_sql = ", ".join(row_template for _ in rows)
    parameters = [value for row in rows for value in row]
    connection.execute(f"{statement} {values_sql}", parameters)
