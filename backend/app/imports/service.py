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
    ) -> str: ...

    def record_download(
        self, file_id: str, *, local_path: str, sha256: str, downloaded_at
    ) -> None: ...

    def import_parsed_file(self, file_id: str, source_file: SourceFile, parsed_file: ParsedFile): ...

    def fail_file(self, file_id: str, error_code: str): ...

    def finish_run(self, run_id: str) -> ImportRunResult: ...


Parser = Callable[[SourceFile, bytes], ParsedFile]
_SAFE_PIPELINE_ERRORS = (DownloadError, SourceFormatError, RepositoryError)


class ImportServiceError(RuntimeError):
    """服务层输入校验的稳定安全错误，尚未产生运行审计时使用。"""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class ImportService:
    """按顺序协调下载、解析和事务导入，确保单文件失败不影响后续文件。"""

    def __init__(self, downloader: _Downloader, parser: Parser, repository: _Repository) -> None:
        self._downloader = downloader
        self._parser = parser
        self._repository = repository

    def run(self, requests: tuple[SourceFile, ...]) -> ImportRunResult:
        """运行一次导入，最终结果完全以仓储写入的审计状态为准。"""
        if len({request.source for request in requests}) > 1:
            # 一次运行只能归属于一个来源，避免后续审计与 API 摘要误导调用方。
            raise ImportServiceError("mixed_sources")
        source = requests[0].source if requests else "football_data"
        run_id = self._repository.start_run(source=source, requested_files=len(requests))

        for request in requests:
            # 即使进程在下载期间中断，pending 文件审计也已存在，可供恢复或诊断。
            file_id = self._repository.start_file(run_id, request)
            try:
                # 下载元数据仅登记在 import_files；解析器只接收原始内容，故不会
                # 将下载时刻误传为历史市场 captured_at 或 available_at。
                downloaded = self._downloader.download(request)
                self._repository.record_download(
                    file_id,
                    local_path=str(downloaded.path),
                    sha256=downloaded.sha256,
                    downloaded_at=downloaded.downloaded_at,
                )
                parsed = self._parser(request, downloaded.content)
                self._repository.import_parsed_file(file_id, request, parsed)
            except _SAFE_PIPELINE_ERRORS as error:
                self._repository.fail_file(file_id, error.code)
            except Exception:
                # 完整异常只留在服务端日志；审计/API 结果只能使用稳定安全码。
                logger.exception(
                    "历史导入出现未预期异常：unexpected_error",
                    extra={"source_url": request.url},
                )
                self._repository.fail_file(file_id, "unexpected_error")

        return self._repository.finish_run(run_id)
