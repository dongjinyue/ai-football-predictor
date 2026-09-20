"""可恢复中国竞彩采集服务与命令行参数测试。"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import date, datetime, timezone
from pathlib import Path

from app.sporttery.cli import parse_args
from app.sporttery.client import BlockedBySourceError, SourceBusinessError
from app.sporttery.models import HttpPayload
from app.sporttery.repository import SportteryRepository
from app.sporttery.service import SportteryCollectionService
from app.sporttery.storage import CheckpointStore, RawResponseStore


FIXTURES = Path(__file__).parent / "fixtures"


def _json(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _http(data: dict, key: str) -> HttpPayload:
    return HttpPayload(
        data=data,
        status_code=200,
        fetched_at=datetime(2026, 9, 19, tzinfo=timezone.utc),
        request_url=f"https://example.test/{key}",
    )


class FakeClient:
    def __init__(self, *, fail_bonus: dict[int, Exception] | None = None) -> None:
        self.match_calls: list[tuple[date, date, int, int]] = []
        self.bonus_calls: list[int] = []
        self.fail_bonus = fail_bonus or {}

    def fetch_match_page(self, begin: date, end: date, page_no: int, page_size: int):
        self.match_calls.append((begin, end, page_no, page_size))
        payload = deepcopy(_json("sporttery_match_page.json"))
        payload["value"]["pageNo"] = page_no
        # 第二页故意重复同两场，验证跨页去重但原始页面仍被审计。
        return _http(payload, f"page-{page_no}")

    def fetch_fixed_bonus(self, match_id: int):
        self.bonus_calls.append(match_id)
        if match_id in self.fail_bonus:
            raise self.fail_bonus[match_id]
        payload = deepcopy(_json("sporttery_fixed_bonus.json"))
        history = payload["value"]["oddsHistory"]
        if match_id == 62374:
            history.update({"matchId": 62374, "leagueId": 37, "homeTeamId": 1003, "awayTeamId": 1004})
        return _http(payload, str(match_id))


def _service(tmp_path: Path, client: FakeClient, waits: list[float] | None = None):
    raw_root = tmp_path / "raw"
    return SportteryCollectionService(
        client=client,
        raw_store=RawResponseStore(raw_root),
        checkpoint_store=CheckpointStore(raw_root),
        repository=SportteryRepository(tmp_path / "sporttery.duckdb"),
        delay_min=3,
        delay_max=5,
        sleep=(waits.append if waits is not None else lambda _: None),
        choose_delay=lambda low, high: 4.0,
    )


def test_collect_follows_source_pages_deduplicates_matches_and_paces_requests(tmp_path: Path) -> None:
    client = FakeClient()
    waits: list[float] = []

    report = _service(tmp_path, client, waits).collect_range(
        date(2015, 1, 1), date(2015, 1, 3)
    )

    assert [call[2] for call in client.match_calls] == [1, 2]
    assert client.bonus_calls == [62373, 62374]
    assert report.status == "completed"
    assert report.discovered_matches == 2
    assert report.duplicate_match_rows == 2
    assert report.completed_bonus == 2
    assert report.failed_bonus == 0
    assert waits == [4.0, 4.0, 4.0]


def test_resume_uses_checkpoint_and_does_not_repeat_network_requests(tmp_path: Path) -> None:
    first_client = FakeClient()
    _service(tmp_path, first_client).collect_range(date(2015, 1, 1), date(2015, 1, 3))
    second_client = FakeClient()

    report = _service(tmp_path, second_client).collect_range(
        date(2015, 1, 1), date(2015, 1, 3), resume=True
    )

    assert second_client.match_calls == []
    assert second_client.bonus_calls == []
    assert report.status == "completed"
    assert report.completed_bonus == 2


def test_resume_replays_cached_pages_into_idempotent_repository(tmp_path: Path) -> None:
    """数据库映射升级后，已完成页应从缓存重放，而不重新访问来源。"""
    first_client = FakeClient()
    _service(tmp_path, first_client).collect_range(date(2015, 1, 1), date(2015, 1, 3))
    second_client = FakeClient()
    service = _service(tmp_path, second_client)
    calls = 0
    original = service.repository.import_match_page

    def recording_import(page, raw):
        nonlocal calls
        calls += 1
        original(page, raw)

    service.repository.import_match_page = recording_import
    service.collect_range(date(2015, 1, 1), date(2015, 1, 3), resume=True)

    assert second_client.match_calls == []
    assert calls == 2


def test_resume_replays_cached_bonus_without_network_requests(tmp_path: Path) -> None:
    """已完成奖金也要从缓存重放，才能补齐数据库升级后的页面映射。"""
    _service(tmp_path, FakeClient()).collect_range(
        date(2015, 1, 1), date(2015, 1, 3)
    )
    second_client = FakeClient()
    service = _service(tmp_path, second_client)
    calls = 0
    original = service.repository.import_fixed_bonus

    def recording_import(record, raw):
        nonlocal calls
        calls += 1
        original(record, raw)

    service.repository.import_fixed_bonus = recording_import
    service.collect_range(date(2015, 1, 1), date(2015, 1, 3), resume=True)

    assert second_client.bonus_calls == []
    assert calls == 2


def test_valid_raw_pages_are_reused_when_crash_preceded_checkpoint(tmp_path: Path) -> None:
    """原始文件已落盘但检查点未写入时，恢复过程不能重复访问列表接口。"""
    client = FakeClient()
    raw = RawResponseStore(tmp_path / "raw")
    for page_no in (1, 2):
        payload = deepcopy(_json("sporttery_match_page.json"))
        payload["value"]["pageNo"] = page_no
        raw.write(
            "match_lists",
            2015,
            f"2015-01-01_2015-01-03/page-{page_no}",
            _http(payload, f"page-{page_no}"),
        )

    report = _service(tmp_path, client).collect_range(
        date(2015, 1, 1), date(2015, 1, 3), resume=True
    )

    assert client.match_calls == []
    assert client.bonus_calls == [62373, 62374]
    assert report.completed_pages == 2


def test_one_missing_bonus_is_recorded_and_remaining_matches_continue(tmp_path: Path) -> None:
    client = FakeClient(fail_bonus={62373: SourceBusinessError("business_missing")})

    report = _service(tmp_path, client).collect_range(date(2015, 1, 1), date(2015, 1, 3))

    assert client.bonus_calls == [62373, 62374]
    assert report.status == "completed_with_errors"
    assert report.completed_bonus == 1
    assert report.failed_bonus == 1
    assert CheckpointStore(tmp_path / "raw").load(2015).failed_bonus_ids == (62373,)


def test_http_567_stops_and_preserves_checkpoint_for_resume(tmp_path: Path) -> None:
    client = FakeClient(fail_bonus={62374: BlockedBySourceError("http_567")})

    report = _service(tmp_path, client).collect_range(date(2015, 1, 1), date(2015, 1, 3))
    checkpoint = CheckpointStore(tmp_path / "raw").load(2015)

    assert report.status == "blocked"
    assert report.completed_bonus == 1
    assert report.stopped_reason == "http_567"
    assert checkpoint.completed_bonus_ids == (62373,)
    assert checkpoint.stopped_reason == "http_567"


def test_unknown_list_shape_stops_with_parse_code_and_keeps_raw_page(tmp_path: Path) -> None:
    class InvalidScoreClient(FakeClient):
        def fetch_match_page(self, begin: date, end: date, page_no: int, page_size: int):
            payload = deepcopy(_json("sporttery_match_page.json"))
            payload["value"]["pages"] = 1
            payload["value"]["matchResult"][0]["sectionsNo999"] = "未知状态"
            return _http(payload, "invalid-page")

    report = _service(tmp_path, InvalidScoreClient()).collect_range(
        date(2015, 1, 1), date(2015, 1, 3)
    )

    assert report.status == "failed"
    assert report.stopped_reason == "parse_invalid_score"
    assert (tmp_path / "raw/match_lists/2015/2015-01-01_2015-01-03/page-1.json").exists()


def test_cli_parses_collection_controls_and_dry_run() -> None:
    args = parse_args([
        "collect", "--start", "2015-01-01", "--end", "2015-12-31",
        "--delay-min", "3", "--delay-max", "5", "--resume", "--dry-run",
    ])

    assert args.command == "collect"
    assert (args.start, args.end) == (date(2015, 1, 1), date(2015, 12, 31))
    assert (args.delay_min, args.delay_max) == (3.0, 5.0)
    assert args.resume is True
    assert args.dry_run is True
