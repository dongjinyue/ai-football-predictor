"""历史导入后台任务与线程安全进度快照。"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from threading import Lock
from typing import Literal
from uuid import uuid4

from app.imports.models import ImportProgress, ImportRunResult, SourceFile
from app.imports.service import ImportServiceError


logger = logging.getLogger(__name__)
ImportJobStatus = Literal[
    "queued",
    "running",
    "completed",
    "completed_with_errors",
    "failed",
]


@dataclass(frozen=True)
class ImportJobSnapshot:
    """可安全返回给浏览器的任务状态。"""

    job_id: str
    run_id: str | None
    status: ImportJobStatus
    requested_files: int
    completed_files: int
    failed_files: int
    imported_matches: int
    skipped_rows: int
    errors: tuple[str, ...]
    current_competition_code: str | None = None
    current_season: str | None = None


class ImportJobManager:
    """单进程导入任务队列；数据库写入仍由导入服务保持串行。"""

    def __init__(self, service, max_workers: int = 1) -> None:
        if max_workers != 1:
            raise ValueError("import_job_workers_must_be_one")
        self._service = service
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="history-import")
        self._lock = Lock()
        self._jobs: dict[str, ImportJobSnapshot] = {}

    def submit(self, requests: tuple[SourceFile, ...]) -> ImportJobSnapshot:
        job_id = str(uuid4())
        snapshot = ImportJobSnapshot(
            job_id=job_id,
            run_id=None,
            status="queued",
            requested_files=len(requests),
            completed_files=0,
            failed_files=0,
            imported_matches=0,
            skipped_rows=0,
            errors=(),
        )
        with self._lock:
            self._jobs[job_id] = snapshot
        self._executor.submit(self._run, job_id, requests)
        return snapshot

    def get(self, job_id: str) -> ImportJobSnapshot | None:
        with self._lock:
            return self._jobs.get(job_id)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=True, cancel_futures=False)

    def _run(self, job_id: str, requests: tuple[SourceFile, ...]) -> None:
        self._replace(job_id, status="running")

        def update_progress(progress: ImportProgress) -> None:
            self._replace(
                job_id,
                completed_files=progress.completed_files,
                failed_files=progress.failed_files,
                imported_matches=progress.imported_matches,
                skipped_rows=progress.skipped_rows,
                current_competition_code=progress.current_competition_code,
                current_season=progress.current_season,
            )

        try:
            result = self._service.run(requests, progress=update_progress)
        except ImportServiceError as error:
            self._replace(job_id, status="failed", errors=(error.code,))
        except Exception:
            logger.exception("历史导入后台任务失败")
            self._replace(job_id, status="failed", errors=("unexpected_error",))
        else:
            self._replace(job_id, **_result_fields(result))

    def _replace(self, job_id: str, **changes: object) -> None:
        with self._lock:
            current = self._jobs.get(job_id)
            if current is not None:
                self._jobs[job_id] = replace(current, **changes)


def _result_fields(result: ImportRunResult) -> dict[str, object]:
    return {
        "run_id": result.run_id,
        "status": result.status,
        "requested_files": result.requested_files,
        "completed_files": result.completed_files,
        "failed_files": result.failed_files,
        "imported_matches": result.imported_matches,
        "skipped_rows": result.skipped_rows,
        "errors": result.errors,
    }
