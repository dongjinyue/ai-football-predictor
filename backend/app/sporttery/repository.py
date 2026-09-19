"""中国竞彩事实的 DuckDB 幂等仓储。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

import duckdb

from app.sporttery.models import FixedBonusRecord, MatchPageRecord
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
                for match in page.matches:
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO sporttery_matches (
                            match_id, match_date, match_number, match_number_label,
                            league_id, league_name, league_abbreviation,
                            home_team_id, home_team_name, home_team_full_name,
                            away_team_id, away_team_name, away_team_full_name,
                            half_time_home_score, half_time_away_score,
                            home_score, away_score, result, handicap,
                            result_status, pool_status, raw_sha256
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        [
                            match.match_id, match.match_date, match.match_number,
                            match.match_number_label, match.league_id, match.league_name,
                            match.league_abbreviation, match.home_team_id, match.home_team,
                            match.home_team_full_name, match.away_team_id, match.away_team,
                            match.away_team_full_name, match.half_time_home_score,
                            match.half_time_away_score, match.home_score, match.away_score,
                            match.result, match.handicap, match.result_status,
                            match.pool_status, raw.sha256,
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
                for snapshot in record.snapshots:
                    line_key = "none" if snapshot.line is None else format(snapshot.line, "g")
                    snapshot_id = _stable_id(
                        "snapshot", str(record.match_id), snapshot.market_type,
                        line_key, snapshot.captured_at.isoformat(),
                    )
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO sporttery_bonus_snapshots
                            (id, match_id, market_type, handicap, handicap_key,
                             captured_at, raw_sha256)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        [snapshot_id, record.match_id, snapshot.market_type, snapshot.line,
                         line_key, snapshot.captured_at, raw.sha256],
                    )
                    for outcome_code, odds in snapshot.outcomes:
                        outcome_id = _stable_id("outcome", snapshot_id, outcome_code)
                        connection.execute(
                            """
                            INSERT OR IGNORE INTO sporttery_bonus_outcomes
                                (id, snapshot_id, outcome_code, odds_value)
                            VALUES (?, ?, ?, ?)
                            """,
                            [outcome_id, snapshot_id, outcome_code, odds],
                        )
                for pool_code, is_single in record.single_pools:
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO sporttery_single_pools
                            (match_id, pool_code, is_single, raw_sha256)
                        VALUES (?, ?, ?, ?)
                        """,
                        [record.match_id, pool_code, is_single, raw.sha256],
                    )
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


def _stable_id(kind: str, *parts: str) -> str:
    return str(uuid.uuid5(_NAMESPACE, ":".join((kind, *parts))))

