"""多文件历史导入协调器：隔离单文件失败并返回仓储审计汇总。"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Protocol

from app.imports.downloader import DownloadError
from app.imports.models import ImportRunResult, ParsedFile, SourceFile
from app.imports.parser import SourceFormatError
from app.imports.repository import RepositoryError


logger = logging.getLogger(__name__)


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
        *,
        local_path: str | None = None,
        sha256: str | None = None,
    ) -> str: ...

    def import_parsed_file(self, file_id: str, source_file: SourceFile, parsed_file: ParsedFile): ...

    def fail_file(self, file_id: str, error_code: str): ...

    def finish_run(self, run_id: str) -> ImportRunResult: ...


Parser = Callable[[SourceFile, bytes], ParsedFile]
_SAFE_PIPELINE_ERRORS = (DownloadError, SourceFormatError, RepositoryError)


class ImportService:
    """按顺序协调下载、解析和事务导入，确保单文件失败不影响后续文件。"""

    def __init__(self, downloader: _Downloader, parser: Parser, repository: _Repository) -> None:
        self._downloader = downloader
        self._parser = parser
        self._repository = repository

    def run(self, requests: tuple[SourceFile, ...]) -> ImportRunResult:
        """运行一次导入，最终结果完全以仓储写入的审计状态为准。"""
        source = requests[0].source if requests else "football_data"
        run_id = self._repository.start_run(source=source, requested_files=len(requests))

        for request in requests:
            file_id: str | None = None
            try:
                # 下载元数据仅登记在 import_files；解析器只接收原始内容，故不会
                # 将下载时刻误传为历史市场 captured_at 或 available_at。
                downloaded = self._downloader.download(request)
                file_id = self._repository.start_file(
                    run_id,
                    request,
                    local_path=str(downloaded.path),
                    sha256=downloaded.sha256,
                )
                parsed = self._parser(request, downloaded.content)
                self._repository.import_parsed_file(file_id, request, parsed)
            except _SAFE_PIPELINE_ERRORS as error:
                self._fail_file(run_id, request, file_id, error.code)
            except Exception:
                # 完整异常只留在服务端日志；审计/API 结果只能使用稳定安全码。
                logger.exception(
                    "历史导入出现未预期异常：unexpected_error",
                    extra={"source_url": request.url},
                )
                self._fail_file(run_id, request, file_id, "unexpected_error")

        return self._repository.finish_run(run_id)

    def _fail_file(
        self,
        run_id: str,
        request: SourceFile,
        file_id: str | None,
        error_code: str,
    ) -> None:
        """下载尚未成功时仍创建失败审计，保证 finish_run 能权威地完成汇总。"""
        audit_file_id = file_id or self._repository.start_file(run_id, request)
        self._repository.fail_file(audit_file_id, error_code)
