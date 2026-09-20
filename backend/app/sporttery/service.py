"""协调中国竞彩列表、固定奖金、原始证据、检查点和数据库写入。"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date, timedelta

from app.sporttery.client import (
    BlockedBySourceError,
    SourceBusinessError,
    SportteryClient,
    SportterySourceError,
)
from app.sporttery.parser import SportteryParseError, parse_fixed_bonus, parse_match_page
from app.sporttery.repository import SportteryRepository
from app.sporttery.storage import (
    CheckpointStore,
    CollectionCheckpoint,
    RawResponseStore,
    StorageError,
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


class SportteryCollectionService:
    """单线程、有限速、每项完成即落检查点的采集协调器。"""

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
    ) -> None:
        if delay_min < 0 or delay_max < delay_min:
            raise ValueError("invalid_delay_range")
        self.client = client
        self.raw_store = raw_store
        self.checkpoint_store = checkpoint_store
        self.repository = repository
        self.delay_min = delay_min
        self.delay_max = delay_max
        self.sleep = sleep
        self.choose_delay = choose_delay
        self.progress = progress or (lambda event: None)
        self._network_requests = 0

    def collect_range(
        self,
        start_date: date,
        end_date: date,
        window_days: int = 7,
        *,
        resume: bool = False,
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
                    if page_key not in checkpoint.completed_pages:
                        self.repository.import_match_page(page, stored)
                        checkpoint = replace(
                            checkpoint,
                            completed_pages=(*checkpoint.completed_pages, page_key),
                            match_ids=(*checkpoint.match_ids, *(item.match_id for item in page.matches)),
                        )
                        self.checkpoint_store.save(checkpoint)
                    for match in page.matches:
                        if match.match_id in seen:
                            duplicate_rows += 1
                        seen.add(match.match_id)
                    self.progress({"event": "list_page", "key": page_key, "pages": pages})
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
        completed = set(checkpoint.completed_bonus_ids)
        failed = set(checkpoint.failed_bonus_ids)
        for match_id in checkpoint.match_ids:
            if match_id in completed:
                continue
            try:
                stored = self.raw_store.load("fixed_bonus", start_date.year, str(match_id))
                if stored is None:
                    self._pace()
                    payload = self.client.fetch_fixed_bonus(match_id)
                    stored = self.raw_store.write(
                        "fixed_bonus", start_date.year, str(match_id), payload
                    )
                record = parse_fixed_bonus(stored.data)
                self.repository.import_fixed_bonus(record, stored)
                completed.add(match_id)
                failed.discard(match_id)
                checkpoint = replace(
                    checkpoint,
                    completed_bonus_ids=tuple(sorted(completed)),
                    failed_bonus_ids=tuple(sorted(failed)),
                )
                self.checkpoint_store.save(checkpoint)
                self.progress({"event": "fixed_bonus", "match_id": match_id, "status": "completed"})
            except BlockedBySourceError as error:
                return self._stopped_report(
                    checkpoint, start_date, end_date, duplicate_rows, "blocked", error.code
                )
            except (SourceBusinessError, SportterySourceError, SportteryParseError) as error:
                failed.add(match_id)
                checkpoint = replace(checkpoint, failed_bonus_ids=tuple(sorted(failed)))
                self.checkpoint_store.save(checkpoint)
                code = error.code if isinstance(error, SportterySourceError) else f"parse_{error}"
                self.progress({"event": "fixed_bonus", "match_id": match_id, "status": "failed", "code": code})

        status = "completed_with_errors" if failed else "completed"
        return _report(checkpoint, start_date, end_date, duplicate_rows, status, None)

    def _pace(self) -> None:
        if self._network_requests:
            self.sleep(self.choose_delay(self.delay_min, self.delay_max))
        self._network_requests += 1

    def _stopped_report(
        self,
        checkpoint: CollectionCheckpoint,
        start_date: date,
        end_date: date,
        duplicate_rows: int,
        status: str,
        reason: str,
    ) -> CollectionReport:
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
    )


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
    )
