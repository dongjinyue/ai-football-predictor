"""可恢复中国竞彩采集服务与命令行参数测试。"""

from __future__ import annotations

import json
import threading
import time
from copy import deepcopy
from datetime import date, datetime, timezone
from pathlib import Path

from app.sporttery.cli import _collect_single_range, _coverage_payload, parse_args
from app.sporttery.client import BlockedBySourceError, SourceBusinessError
from app.sporttery.models import HttpPayload
from app.sporttery.preview import PREVIEW_DATASETS
from app.sporttery.repository import CoverageReport, SportteryRepository, SynchronizedSportteryRepository
from app.sporttery.service import (
    CollectionReport,
    SportteryCollectionService,
    collect_with_blocked_retries,
    collect_years,
)
from app.sporttery.storage import (
    CheckpointStore,
    CollectionCheckpoint,
    PreviewDatasetCheckpoint,
    RawResponseStore,
    get_preview_checkpoint,
)


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
    def __init__(
        self,
        *,
        fail_bonus: dict[int, Exception] | None = None,
        fail_preview: dict[tuple[int, str], Exception] | None = None,
        empty_preview: set[tuple[int, str]] | None = None,
    ) -> None:
        self.match_calls: list[tuple[date, date, int, int]] = []
        self.bonus_calls: list[int] = []
        self.fail_bonus = fail_bonus or {}
        self.fail_preview = fail_preview or {}
        self.empty_preview = empty_preview or set()
        self.preview_calls: list[tuple[int, str]] = []
        self.calls: list[str] = []

    def fetch_match_page(self, begin: date, end: date, page_no: int, page_size: int):
        self.calls.append(f"list:{page_no}")
        self.match_calls.append((begin, end, page_no, page_size))
        payload = deepcopy(_json("sporttery_match_page.json"))
        payload["value"]["pageNo"] = page_no
        # 第二页故意重复同两场，验证跨页去重但原始页面仍被审计。
        return _http(payload, f"page-{page_no}")

    def fetch_fixed_bonus(self, match_id: int):
        self.calls.append(f"bonus:{match_id}")
        self.bonus_calls.append(match_id)
        if match_id in self.fail_bonus:
            raise self.fail_bonus[match_id]
        payload = deepcopy(_json("sporttery_fixed_bonus.json"))
        history = payload["value"]["oddsHistory"]
        if match_id == 62374:
            history.update({"matchId": 62374, "leagueId": 37, "homeTeamId": 1003, "awayTeamId": 1004})
        return _http(payload, str(match_id))

    def fetch_preview(self, dataset, match_id: int):
        self.calls.append(f"preview:{match_id}:{dataset.code}")
        self.preview_calls.append((match_id, dataset.code))
        error = self.fail_preview.get((match_id, dataset.code))
        if error is not None:
            raise error
        if (match_id, dataset.code) in self.empty_preview:
            return _http({"emptyFlag": True, "value": None}, f"preview-{match_id}-{dataset.code}")
        return _http({"emptyFlag": False, "value": {"matchId": match_id}}, f"preview-{match_id}-{dataset.code}")


def _service(
    tmp_path: Path,
    client: FakeClient,
    waits: list[float] | None = None,
    *,
    include_preview: bool = False,
):
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
        include_preview=include_preview,
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


def test_collects_each_pages_bonus_before_requesting_the_next_list_page(tmp_path: Path) -> None:
    """列表采集尚未完成时，也必须让已发现比赛的赔率立即落库。"""
    client = FakeClient()

    _service(tmp_path, client).collect_range(date(2015, 1, 1), date(2015, 1, 3))

    assert client.calls[:3] == ["list:1", "bonus:62373", "bonus:62374"]


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


def test_preview_collection_is_opt_in_and_follows_catalog_order(tmp_path: Path) -> None:
    default_client = FakeClient()
    _service(tmp_path / "default", default_client).collect_range(
        date(2015, 1, 1), date(2015, 1, 3)
    )
    assert default_client.preview_calls == []

    client = FakeClient()
    report = _service(tmp_path / "enabled", client, include_preview=True).collect_range(
        date(2015, 1, 1), date(2015, 1, 3)
    )

    expected = [(match_id, dataset.code) for match_id in (62373, 62374) for dataset in PREVIEW_DATASETS]
    assert client.preview_calls == expected
    assert report.completed_preview == 14
    assert report.empty_preview == 0
    assert report.failed_preview == 0
    assert report.preview_by_dataset == tuple((dataset.code, (2, 0, 0)) for dataset in PREVIEW_DATASETS)
    assert client.calls[1:9] == [
        "bonus:62373",
        *[f"preview:62373:{dataset.code}" for dataset in PREVIEW_DATASETS],
    ]


def test_empty_and_failed_preview_do_not_stop_other_datasets_or_matches(tmp_path: Path) -> None:
    client = FakeClient(
        empty_preview={(62373, "match_player")},
        fail_preview={(62373, "injury_suspension"): SourceBusinessError("business_missing")},
    )

    report = _service(tmp_path, client, include_preview=True).collect_range(
        date(2015, 1, 1), date(2015, 1, 3)
    )
    checkpoint = CheckpointStore(tmp_path / "raw").load(2015)

    assert report.status == "completed_with_errors"
    assert report.completed_preview == 12
    assert report.empty_preview == 1
    assert report.failed_preview == 1
    assert get_preview_checkpoint(checkpoint, "match_player").empty_ids == (62373,)
    assert get_preview_checkpoint(checkpoint, "injury_suspension").failed_ids == (62373,)
    assert (62374, "injury_suspension") in client.preview_calls


def test_resume_replays_cached_preview_raw_without_network(tmp_path: Path) -> None:
    raw = RawResponseStore(tmp_path / "raw")
    _service(tmp_path, FakeClient()).collect_range(date(2015, 1, 1), date(2015, 1, 3))
    for match_id in (62373, 62374):
        for dataset in PREVIEW_DATASETS:
            raw.write(
                "previews",
                2015,
                f"{match_id}/{dataset.code}",
                _http({"value": {"matchId": match_id}}, f"cached-{match_id}-{dataset.code}"),
            )

    client = FakeClient()
    report = _service(tmp_path, client, include_preview=True).collect_range(
        date(2015, 1, 1), date(2015, 1, 3), resume=True
    )

    assert client.preview_calls == []
    assert report.completed_preview == 14
    assert len(CheckpointStore(tmp_path / "raw").load(2015).preview_datasets) == 7


def test_preview_http_567_stops_without_marking_later_datasets_failed(tmp_path: Path) -> None:
    client = FakeClient(
        fail_preview={(62373, "match_tables"): BlockedBySourceError("http_567")}
    )

    report = _service(tmp_path, client, include_preview=True).collect_range(
        date(2015, 1, 1), date(2015, 1, 3)
    )
    checkpoint = CheckpointStore(tmp_path / "raw").load(2015)

    assert report.status == "blocked"
    assert report.stopped_reason == "http_567"
    assert report.completed_preview == 2
    assert client.preview_calls == [(62373, "match_feature"), (62373, "result_history"), (62373, "match_tables")]
    assert get_preview_checkpoint(checkpoint, "match_feature").completed_ids == (62373,)
    assert get_preview_checkpoint(checkpoint, "result_history").completed_ids == (62373,)
    assert get_preview_checkpoint(checkpoint, "match_tables").completed_ids == ()


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
    assert args.include_preview is False

    preview_args = parse_args([
        "collect", "--start", "2015-01-01", "--end", "2015-01-03",
        "--include-preview",
    ])
    assert preview_args.include_preview is True


def test_cli_preview_dry_run_reports_extra_dataset_count(capsys) -> None:
    args = parse_args([
        "collect", "--start", "2015-01-01", "--end", "2015-01-03",
        "--include-preview", "--dry-run",
    ])

    assert _collect_single_range(args, object()) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["network_requests"] == 0
    assert output["preview_datasets"] == 7


def test_coverage_payload_merges_checkpoint_failures_with_database_counts() -> None:
    report = CoverageReport(
        year=2015,
        matches=10,
        matches_with_bonus=8,
        snapshots=20,
        outcomes=60,
        request_records=30,
        snapshots_by_market=(),
        completed_preview=2,
        empty_preview=1,
        preview_by_dataset=(("match_feature", (2, 1)),),
    )
    checkpoint = CollectionCheckpoint(
        year=2015,
        preview_datasets=(
            PreviewDatasetCheckpoint("match_feature", failed_ids=(123,)),
        ),
    )

    payload = _coverage_payload(report, checkpoint)

    assert payload["failed_preview"] == 1
    assert payload["preview_by_dataset"]["match_feature"] == {
        "completed": 2,
        "empty": 1,
        "failed": 1,
    }


def test_cli_parses_parallel_year_collection_controls() -> None:
    args = parse_args([
        "collect-years", "--start-year", "2016", "--end-year", "2026",
        "--workers", "3", "--delay-min", "3", "--delay-max", "5", "--resume",
    ])

    assert args.command == "collect-years"
    assert (args.start_year, args.end_year) == (2016, 2026)
    assert args.workers == 3
    assert args.resume is True


def test_collect_years_runs_years_in_parallel_and_keeps_result_order() -> None:
    active = 0
    maximum_active = 0
    guard = threading.Lock()

    def collect(year: int):
        nonlocal active, maximum_active
        with guard:
            active += 1
            maximum_active = max(maximum_active, active)
        time.sleep(0.02)
        with guard:
            active -= 1
        return year

    results = collect_years(range(2016, 2019), workers=3, collect=collect)

    assert results == [2016, 2017, 2018]
    assert maximum_active == 3


def test_synchronized_repository_serializes_database_writes() -> None:
    active = 0
    maximum_active = 0
    guard = threading.Lock()

    class RecordingRepository:
        def import_match_page(self, page, raw) -> None:
            nonlocal active, maximum_active
            with guard:
                active += 1
                maximum_active = max(maximum_active, active)
            time.sleep(0.02)
            with guard:
                active -= 1

    repository = SynchronizedSportteryRepository(RecordingRepository())
    threads = [
        threading.Thread(target=repository.import_match_page, args=(None, None))
        for _ in range(3)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert maximum_active == 1


def test_blocked_year_waits_and_resumes_from_checkpoint() -> None:
    resume_values: list[bool] = []
    waits: list[float] = []

    def collect(resume: bool) -> CollectionReport:
        resume_values.append(resume)
        return CollectionReport(
            status="blocked" if len(resume_values) == 1 else "completed",
            start_date=date(2016, 1, 1),
            end_date=date(2016, 12, 31),
            completed_pages=1,
            discovered_matches=2,
            duplicate_match_rows=0,
            completed_bonus=1,
            failed_bonus=0,
            stopped_reason="http_567" if len(resume_values) == 1 else None,
        )

    result = collect_with_blocked_retries(
        collect,
        initial_resume=False,
        retries=2,
        base_wait=60,
        sleep=waits.append,
    )

    assert result.status == "completed"
    assert resume_values == [False, True]
    assert waits == [60]
