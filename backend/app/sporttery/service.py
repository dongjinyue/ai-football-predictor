"""协调中国竞彩列表、固定奖金、原始证据、检查点和数据库写入。"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import date, timedelta
from threading import Lock

from app.sporttery.client import (
    BlockedBySourceError,
    SourceBusinessError,
    SportteryClient,
    SportterySourceError,
)
from app.sporttery.parser import SportteryParseError, parse_fixed_bonus, parse_match_page
from app.sporttery.preview import (
    PREVIEW_DATASETS,
    classify_preview_payload,
)
from app.sporttery.repository import SportteryRepository
from app.sporttery.storage import (
    CheckpointStore,
    CollectionCheckpoint,
    PreviewDatasetCheckpoint,
    RawResponseStore,
    StorageError,
    get_preview_checkpoint,
    replace_preview_checkpoint,
)


@dataclass(frozen=True)
class CollectionReport:
    """一次采集任务结束或安全停止时的可审计摘要。"""

    status: str
    start_date: date
    end_date: date
    completed_pages: int
    discovered_matches: int
    duplicate_match_rows: int
    completed_bonus: int
    failed_bonus: int
    stopped_reason: str | None
    completed_preview: int = 0
    empty_preview: int = 0
    failed_preview: int = 0
    preview_by_dataset: tuple[tuple[str, tuple[int, int, int]], ...] = ()


class RequestStartPacer:
    """在所有采集线程之间共享的请求起始间隔控制器。"""

    def __init__(
        self,
        delay_min: float,
        delay_max: float,
        *,
        sleep: Callable[[float], None] = time.sleep,
        choose_delay: Callable[[float, float], float] = random.uniform,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if delay_min < 0 or delay_max < delay_min:
            raise ValueError("invalid_delay_range")
        self.delay_min = delay_min
        self.delay_max = delay_max
        self.sleep = sleep
        self.choose_delay = choose_delay
        self.monotonic = monotonic
        self._next_start = 0.0
        self._lock = Lock()

    def wait(self) -> None:
        """只等待到下一个请求起始时刻，不把本地解析和入库耗时叠加进去。"""
        with self._lock:
            now = self.monotonic()
            wait_seconds = max(0.0, self._next_start - now)
            if wait_seconds:
                self.sleep(wait_seconds)
            self._next_start = self.monotonic() + self.choose_delay(
                self.delay_min, self.delay_max
            )


def collect_years(
    years,
    *,
    workers: int,
    collect: Callable[[int], object],
) -> list[object]:
    """并行执行互不重叠的年份任务，并按年份顺序返回结果。"""
    year_list = list(years)
    if workers < 1:
        raise ValueError("workers_must_be_positive")
    with ThreadPoolExecutor(max_workers=workers) as executor:
        return list(executor.map(collect, year_list))


def collect_with_blocked_retries(
    collect: Callable[[bool], CollectionReport],
    *,
    initial_resume: bool,
    retries: int,
    base_wait: float,
    sleep: Callable[[float], None] = time.sleep,
) -> CollectionReport:
    """来源返回 567 时指数等待，并从该年份检查点继续。"""
    if retries < 0 or base_wait < 0:
        raise ValueError("invalid_blocked_retry_policy")
    result = collect(initial_resume)
    for attempt in range(retries):
        if result.status != "blocked" or result.stopped_reason != "http_567":
            return result
        wait_seconds = min(base_wait * (2 ** attempt), 900.0)
        sleep(wait_seconds)
        result = collect(True)
    return result


class SportteryCollectionService:
    """负责单场数据采集、请求节流、批量入库和断点恢复的协调器。"""

    def __init__(
        self,
        *,
        client: SportteryClient,
        raw_store: RawResponseStore,
        checkpoint_store: CheckpointStore,
        repository: SportteryRepository,
        delay_min: float = 3.0,
        delay_max: float = 5.0,
        sleep: Callable[[float], None] = time.sleep,
        choose_delay: Callable[[float, float], float] = random.uniform,
        progress: Callable[[dict[str, object]], None] | None = None,
        include_preview: bool = False,
        request_pacer: RequestStartPacer | None = None,
    ) -> None:
        if delay_min < 0 or delay_max < delay_min:
            raise ValueError("invalid_delay_range")
        self.client = client
        self.raw_store = raw_store
        self.checkpoint_store = checkpoint_store
        self.repository = repository
        self.pacer = request_pacer or RequestStartPacer(
            delay_min, delay_max, sleep=sleep, choose_delay=choose_delay
        )
        self.progress = progress or (lambda event: None)
        self.include_preview = include_preview

    def collect_range(
        self,
        start_date: date,
        end_date: date,
        window_days: int = 7,
        *,
        resume: bool = False,
        replay_imports: bool = False,
    ) -> CollectionReport:
        if end_date < start_date:
            raise ValueError("end_before_start")
        if start_date.year != end_date.year:
            raise ValueError("range_must_stay_in_one_year")
        if window_days < 1:
            raise ValueError("window_days_must_be_positive")

        checkpoint = self.checkpoint_store.load(start_date.year)
        if not resume and _has_progress(checkpoint):
            raise ValueError("existing_checkpoint_use_resume")
        checkpoint = replace(checkpoint, stopped_reason=None)
        seen = set(checkpoint.match_ids)
        processed_bonus_ids: set[int] = set()
        duplicate_rows = 0

        for begin, end in _date_windows(start_date, end_date, window_days):
            page_no = 1
            pages = 1
            while page_no <= pages:
                page_key = f"{begin.isoformat()}_{end.isoformat()}/page-{page_no}"
                try:
                    if page_key in checkpoint.completed_pages:
                        stored = self.raw_store.load("match_lists", start_date.year, page_key)
                        if stored is None:
                            raise StorageError("checkpoint_raw_missing")
                    else:
                        # 原始文件可能已落盘而进程在写检查点前退出；先复用证据，避免重复请求。
                        stored = self.raw_store.load("match_lists", start_date.year, page_key)
                        if stored is None:
                            self._pace()
                            payload = self.client.fetch_match_page(begin, end, page_no, 30)
                            stored = self.raw_store.write(
                                "match_lists", start_date.year, page_key, payload
                            )
                    page = parse_match_page(stored.data)
                    pages = page.pages
                    # 重放模式用于数据库映射迁移；平时跳过已提交的列表页内容。
                    if replay_imports:
                        self.repository.import_match_page(
                            page, stored, replay_imports=True
                        )
                    else:
                        self.repository.import_match_page(page, stored)
                    if page_key not in checkpoint.completed_pages:
                        checkpoint = replace(
                            checkpoint,
                            completed_pages=(*checkpoint.completed_pages, page_key),
                            match_ids=(*checkpoint.match_ids, *(item.match_id for item in page.matches)),
                        )
                        self.checkpoint_store.save(checkpoint)
                    completed_candidates = set()
                    if resume and not replay_imports:
                        candidates = _checkpoint_completed_detail_ids(
                            checkpoint,
                            [match.match_id for match in page.matches],
                            include_preview=self.include_preview,
                        )
                        verify_imports = getattr(
                            self.repository, "fully_imported_match_ids", None
                        )
                        if callable(verify_imports) and candidates:
                            completed_candidates = verify_imports(
                                list(candidates), include_preview=self.include_preview
                            )
                    for match in page.matches:
                        if match.match_id in seen:
                            duplicate_rows += 1
                        seen.add(match.match_id)
                        if match.match_id in completed_candidates:
                            processed_bonus_ids.add(match.match_id)
                            continue
                        if match.match_id not in processed_bonus_ids:
                            checkpoint = self._collect_match_details(
                                checkpoint,
                                match.match_id,
                                start_date.year,
                                replay_imports=replay_imports,
                            )
                            processed_bonus_ids.add(match.match_id)
                    self.progress({
                        "event": "list_page",
                        "key": page_key,
                        "pages": pages,
                        "rejected_matches": page.rejected_matches,
                    })
                    page_no += 1
                except SportterySourceError as error:
                    return self._stopped_report(
                        checkpoint, start_date, end_date, duplicate_rows,
                        "blocked" if isinstance(error, BlockedBySourceError) else "failed",
                        error.code,
                    )
                except SportteryParseError as error:
                    return self._stopped_report(
                        checkpoint, start_date, end_date, duplicate_rows,
                        "failed", f"parse_{error}",
                    )

        # 列表阶段可能由多页重复返回同场；检查点保存排序后的唯一 ID。
        checkpoint = replace(checkpoint, match_ids=tuple(sorted(seen)))
        self.checkpoint_store.save(checkpoint)
        for match_id in checkpoint.match_ids:
            if match_id not in processed_bonus_ids:
                try:
                    checkpoint = self._collect_match_details(
                        checkpoint,
                        match_id,
                        start_date.year,
                        replay_imports=replay_imports,
                    )
                except BlockedBySourceError as error:
                    return self._stopped_report(
                        checkpoint, start_date, end_date, duplicate_rows, "blocked", error.code
                    )

        status = (
            "completed_with_errors"
            if checkpoint.failed_bonus_ids or _failed_preview_count(checkpoint)
            else "completed"
        )
        return _report(checkpoint, start_date, end_date, duplicate_rows, status, None)

    def _collect_match_details(
        self,
        checkpoint: CollectionCheckpoint,
        match_id: int,
        year: int,
        *,
        replay_imports: bool,
    ) -> CollectionCheckpoint:
        """采集单场数据，统一入库并在比赛边界保存一次检查点。"""
        fixed_bonus = None
        previews = []
        events: list[dict[str, object]] = []
        blocked_error: BlockedBySourceError | None = None

        completed_bonus = set(checkpoint.completed_bonus_ids)
        failed_bonus = set(checkpoint.failed_bonus_ids)
        try:
            stored = self.raw_store.load("fixed_bonus", year, str(match_id))
            if stored is None:
                self._pace()
                payload = self.client.fetch_fixed_bonus(match_id)
                stored = self.raw_store.write("fixed_bonus", year, str(match_id), payload)
            fixed_bonus = (parse_fixed_bonus(stored.data), stored)
            completed_bonus.add(match_id)
            failed_bonus.discard(match_id)
            events.append({"event": "fixed_bonus", "match_id": match_id, "status": "completed"})
        except BlockedBySourceError as error:
            blocked_error = error
        except (SourceBusinessError, SportterySourceError, SportteryParseError) as error:
            completed_bonus.discard(match_id)
            failed_bonus.add(match_id)
            code = error.code if isinstance(error, SportterySourceError) else f"parse_{error}"
            events.append({
                "event": "fixed_bonus", "match_id": match_id,
                "status": "failed", "code": code,
            })
        checkpoint = replace(
            checkpoint,
            completed_bonus_ids=tuple(completed_bonus),
            failed_bonus_ids=tuple(failed_bonus),
        )

        if self.include_preview and blocked_error is None:
            for dataset in PREVIEW_DATASETS:
                state = get_preview_checkpoint(checkpoint, dataset.code)
                completed = set(state.completed_ids)
                empty = set(state.empty_ids)
                failed = set(state.failed_ids)
                try:
                    stored = self.raw_store.load(
                        "previews", year, f"{match_id}/{dataset.code}"
                    )
                    if stored is None:
                        self._pace()
                        payload = self.client.fetch_preview(dataset, match_id)
                        stored = self.raw_store.write(
                            "previews", year, f"{match_id}/{dataset.code}", payload
                        )
                    status = classify_preview_payload(stored.data)
                    previews.append((match_id, dataset.code, status, stored))
                    completed.discard(match_id)
                    empty.discard(match_id)
                    failed.discard(match_id)
                    (completed if status == "completed" else empty).add(match_id)
                    events.append({
                        "event": "preview",
                        "match_id": match_id,
                        "dataset": dataset.code,
                        "status": status,
                    })
                except BlockedBySourceError as error:
                    blocked_error = error
                    break
                except (SourceBusinessError, SportterySourceError, SportteryParseError) as error:
                    completed.discard(match_id)
                    empty.discard(match_id)
                    failed.add(match_id)
                    code = error.code if isinstance(error, SportterySourceError) else f"parse_{error}"
                    events.append({
                        "event": "preview",
                        "match_id": match_id,
                        "dataset": dataset.code,
                        "status": "failed",
                        "code": code,
                    })
                checkpoint = replace_preview_checkpoint(
                    checkpoint,
                    PreviewDatasetCheckpoint(
                        dataset=dataset.code,
                        completed_ids=tuple(completed),
                        empty_ids=tuple(empty),
                        failed_ids=tuple(failed),
                    ),
                )

        batch_import = getattr(self.repository, "import_match_details", None)
        if callable(batch_import):
            batch_import(fixed_bonus, previews, replay_imports=replay_imports)
        else:
            # 兼容旧的仓储替身；正式仓储使用单事务批量写入。
            if fixed_bonus is not None:
                batch_import = getattr(self.repository, "import_fixed_bonus")
                batch_import(*fixed_bonus)
            for preview in previews:
                self.repository.import_preview_source(*preview)

        self.checkpoint_store.save(checkpoint)
        for event in events:
            self.progress(event)
        if blocked_error is not None:
            raise blocked_error
        return checkpoint

    def _pace(self) -> None:
        self.pacer.wait()

    def _stopped_report(
        self,
        checkpoint: CollectionCheckpoint,
        start_date: date,
        end_date: date,
        duplicate_rows: int,
        status: str,
        reason: str,
    ) -> CollectionReport:
        # 前瞻接口可能在内部已经完成若干数据集后才返回 HTTP 567；
        # 重新读取持久化检查点，避免丢掉刚刚成功的前瞻状态。
        checkpoint = self.checkpoint_store.load(start_date.year)
        checkpoint = replace(checkpoint, stopped_reason=reason)
        self.checkpoint_store.save(checkpoint)
        return _report(checkpoint, start_date, end_date, duplicate_rows, status, reason)


def _date_windows(start: date, end: date, window_days: int):
    current = start
    while current <= end:
        window_end = min(end, current + timedelta(days=window_days - 1))
        yield current, window_end
        current = window_end + timedelta(days=1)


def _has_progress(checkpoint: CollectionCheckpoint) -> bool:
    return bool(
        checkpoint.completed_pages
        or checkpoint.match_ids
        or checkpoint.completed_bonus_ids
        or checkpoint.failed_bonus_ids
        or any(
            state.completed_ids or state.empty_ids or state.failed_ids
            for state in checkpoint.preview_datasets
        )
    )


def _checkpoint_completed_detail_ids(
    checkpoint: CollectionCheckpoint,
    match_ids: list[int],
    *,
    include_preview: bool,
) -> set[int]:
    completed = set(match_ids) & set(checkpoint.completed_bonus_ids)
    if not include_preview:
        return completed
    states = {state.dataset: state for state in checkpoint.preview_datasets}
    for dataset in PREVIEW_DATASETS:
        state = states.get(dataset.code)
        if state is None:
            return set()
        completed &= set(state.completed_ids) | set(state.empty_ids)
    return completed


def _report(
    checkpoint: CollectionCheckpoint,
    start_date: date,
    end_date: date,
    duplicate_rows: int,
    status: str,
    reason: str | None,
) -> CollectionReport:
    return CollectionReport(
        status=status,
        start_date=start_date,
        end_date=end_date,
        completed_pages=len(checkpoint.completed_pages),
        discovered_matches=len(checkpoint.match_ids),
        duplicate_match_rows=duplicate_rows,
        completed_bonus=len(checkpoint.completed_bonus_ids),
        failed_bonus=len(checkpoint.failed_bonus_ids),
        stopped_reason=reason,
        completed_preview=_preview_count(checkpoint, "completed_ids"),
        empty_preview=_preview_count(checkpoint, "empty_ids"),
        failed_preview=_preview_count(checkpoint, "failed_ids"),
        preview_by_dataset=_preview_by_dataset(checkpoint),
    )


def _preview_count(checkpoint: CollectionCheckpoint, field: str) -> int:
    return sum(len(getattr(state, field)) for state in checkpoint.preview_datasets)


def _failed_preview_count(checkpoint: CollectionCheckpoint) -> int:
    return _preview_count(checkpoint, "failed_ids")


def _preview_by_dataset(
    checkpoint: CollectionCheckpoint,
) -> tuple[tuple[str, tuple[int, int, int]], ...]:
    states = {state.dataset: state for state in checkpoint.preview_datasets}
    return tuple(
        (
            dataset.code,
            (
                len(states.get(dataset.code, PreviewDatasetCheckpoint(dataset.code)).completed_ids),
                len(states.get(dataset.code, PreviewDatasetCheckpoint(dataset.code)).empty_ids),
                len(states.get(dataset.code, PreviewDatasetCheckpoint(dataset.code)).failed_ids),
            ),
        )
        for dataset in PREVIEW_DATASETS
    )
