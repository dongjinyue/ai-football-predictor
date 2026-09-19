"""多文件历史导入协调器：隔离单文件失败并返回仓储审计汇总。"""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Protocol
from threading import Lock

from app.imports.downloader import DownloadError
from app.imports.models import ImportProgress, ImportRunResult, ParsedFile, SourceFile
from app.imports.parser import SourceFormatError
from app.imports.repository import RepositoryError


logger = logging.getLogger(__name__)
# 本机单进程应用共享一把写入锁；不同服务实例也不能重叠导入。
_IMPORT_LOCK = Lock()


class _Downloader(Protocol):
    """协调器实际需要的下载器最小能力，便于离线 fake 注入。"""

    def download(self, request: SourceFile): ...


class _Repository(Protocol):
    """协调器只依赖审计与单文件导入接口，不自行维护统计。"""

    def start_run(self, source: str, requested_files: int) -> str: ...

    def start_file(
        self,
        run_id: str,
        source_file: SourceFile,
    ) -> str: ...

    def record_download(
        self, file_id: str, *, local_path: str, sha256: str, downloaded_at
    ) -> None: ...

    def import_parsed_file(self, file_id: str, source_file: SourceFile, parsed_file: ParsedFile): ...

    def fail_file(self, file_id: str, error_code: str): ...

    def finish_run(self, run_id: str) -> ImportRunResult: ...


Parser = Callable[[SourceFile, bytes], ParsedFile]
ProgressCallback = Callable[[ImportProgress], None]
_SAFE_PIPELINE_ERRORS = (DownloadError, SourceFormatError, RepositoryError)


class ImportServiceError(RuntimeError):
    """服务层输入校验的稳定安全错误，尚未产生运行审计时使用。"""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class ImportService:
    """并发下载与解析、串行写入数据库，确保单文件失败不影响后续文件。"""

    def __init__(
        self,
        downloader: _Downloader,
        parser: Parser,
        repository: _Repository,
        download_workers: int = 8,
    ) -> None:
        if download_workers < 1:
            raise ValueError("download_workers_must_be_positive")
        self._downloader = downloader
        self._parser = parser
        self._repository = repository
        self._download_workers = download_workers

    def run(
        self,
        requests: tuple[SourceFile, ...],
        progress: ProgressCallback | None = None,
    ) -> ImportRunResult:
        """运行一次导入，最终结果完全以仓储写入的审计状态为准。"""
        if not _IMPORT_LOCK.acquire(blocking=False):
            raise ImportServiceError("import_in_progress")
        try:
            return self._run_locked(requests, progress)
        finally:
            _IMPORT_LOCK.release()

    def _run_locked(
        self,
        requests: tuple[SourceFile, ...],
        progress: ProgressCallback | None,
    ) -> ImportRunResult:
        """持有写入锁后才创建审计，拒绝的重复提交不会留下半条运行。"""
        if len({request.source for request in requests}) > 1:
            # 一次运行只能归属于一个来源，避免后续审计与 API 摘要误导调用方。
            raise ImportServiceError("mixed_sources")
        source = requests[0].source if requests else "football_data"
        run_id = self._repository.start_run(source=source, requested_files=len(requests))
        completed_files = 0
        failed_files = 0
        imported_matches = 0
        skipped_rows = 0

        # 先为全部文件建立 pending 审计，再并发下载和解析。主线程按请求顺序
        # 写入 DuckDB，避免多个线程争抢同一个写事务，同时把网络等待重叠起来。
        file_entries = tuple(
            (request, self._repository.start_file(run_id, request))
            for request in requests
        )
        if file_entries:
            with ThreadPoolExecutor(
                max_workers=min(self._download_workers, len(file_entries)),
                thread_name_prefix="history-download",
            ) as executor:
                futures = tuple(
                    executor.submit(self._download_and_parse, request)
                    for request, _ in file_entries
                )
                for (request, file_id), future in zip(file_entries, futures, strict=True):
                    try:
                        # 下载元数据仅登记在 import_files；解析器只接收原始内容，故不会
                        # 将下载时刻误传为历史市场 captured_at 或 available_at。
                        downloaded, parsed = future.result()
                        self._repository.record_download(
                            file_id,
                            local_path=str(downloaded.path),
                            sha256=downloaded.sha256,
                            downloaded_at=downloaded.downloaded_at,
                        )
                        file_result = self._repository.import_parsed_file(file_id, request, parsed)
                        completed_files += 1
                        imported_matches += file_result.imported_matches
                        skipped_rows += file_result.skipped_rows
                    except _SAFE_PIPELINE_ERRORS as error:
                        self._repository.fail_file(file_id, error.code)
                        failed_files += 1
                    except Exception:
                        # 完整异常只留在服务端日志；审计/API 结果只能使用稳定安全码。
                        logger.exception(
                            "历史导入出现未预期异常：unexpected_error",
                            extra={"source_url": request.url},
                        )
                        self._repository.fail_file(file_id, "unexpected_error")
                        failed_files += 1

                    _notify_progress(
                        progress,
                        ImportProgress(
                            completed_files=completed_files,
                            failed_files=failed_files,
                            imported_matches=imported_matches,
                            skipped_rows=skipped_rows,
                            current_competition_code=request.competition_code,
                            current_season=request.season,
                        ),
                    )

        return self._repository.finish_run(run_id)

    def _download_and_parse(self, request: SourceFile):
        """在线程池中完成网络读取和纯解析，不触碰数据库。"""
        downloaded = self._downloader.download(request)
        return downloaded, self._parser(request, downloaded.content)


def _notify_progress(progress: ProgressCallback | None, update: ImportProgress) -> None:
    """进度回调属于展示层，回调故障不能破坏已经可提交的导入事务。"""
    if progress is None:
        return
    try:
        progress(update)
    except Exception:
        logger.exception("历史导入进度回调失败")
