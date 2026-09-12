"""导入协调器的离线行为测试：所有边界依赖均使用明确的 fake。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.imports.downloader import DownloadError, DownloadedFile
from app.imports.models import FileImportResult, ImportRunResult, ParsedFile, SourceFile
from app.imports.repository import RepositoryError


def _source_file(code: str) -> SourceFile:
    return SourceFile(
        source="football_data",
        competition_code=code,
        competition_name="English Premier League",
        country_code="ENG",
        season="2324",
        url=f"https://example.test/{code}.csv",
    )


@dataclass
class _FakeDownloader:
    failures: dict[str, Exception]

    def download(self, request: SourceFile) -> DownloadedFile:
        if error := self.failures.get(request.competition_code):
            raise error
        content = b"Date,HomeTeam,AwayTeam,FTHG,FTAG\n01/01/24,Home,Away,1,0\n"
        return DownloadedFile(
            path=Path("raw") / request.competition_code / "matches.csv",
            content=content,
            sha256="safe-checksum",
            downloaded_at=datetime(2026, 9, 10, tzinfo=timezone.utc),
            from_cache=False,
        )


class _FakeRepository:
    """用审计记录计算结果，模拟真实仓储而非让服务层自行计数。"""

    def __init__(self, import_failures: set[str] = set()) -> None:
        self.import_failures = import_failures
        self.files: dict[str, tuple[SourceFile, str, int, int, tuple[str, ...]]] = {}
        self.file_counter = 0
        self.run_id = "run-1"
        self.requested_files = 0

    def start_run(self, source: str, requested_files: int) -> str:
        assert source == "football_data"
        self.requested_files = requested_files
        return self.run_id

    def start_file(
        self,
        run_id: str,
        source_file: SourceFile,
        *,
        local_path: str | None = None,
        sha256: str | None = None,
    ) -> str:
        assert run_id == self.run_id
        self.file_counter += 1
        file_id = f"file-{self.file_counter}"
        assert (local_path is None) == (sha256 is None)
        self.files[file_id] = (source_file, "pending", 0, 0, ())
        return file_id

    def import_parsed_file(
        self, file_id: str, source_file: SourceFile, parsed_file: ParsedFile
    ) -> FileImportResult:
        if source_file.competition_code in self.import_failures:
            raise RepositoryError("database_error")
        imported_matches = len(parsed_file.matches)
        self.files[file_id] = (source_file, "completed", imported_matches, parsed_file.skipped_rows, parsed_file.errors)
        return FileImportResult(file_id, source_file, "completed", imported_matches, parsed_file.skipped_rows, parsed_file.errors)

    def fail_file(self, file_id: str, error_code: str) -> FileImportResult:
        source_file, _, _, _, _ = self.files[file_id]
        self.files[file_id] = (source_file, "failed", 0, 0, (error_code,))
        return FileImportResult(file_id, source_file, "failed", 0, 0, (error_code,))

    def finish_run(self, run_id: str) -> ImportRunResult:
        assert run_id == self.run_id
        completed = [item for item in self.files.values() if item[1] == "completed"]
        failed = [item for item in self.files.values() if item[1] == "failed"]
        errors = tuple(error for _, _, _, _, file_errors in failed for error in file_errors)
        status = "completed" if not failed else "completed_with_errors" if completed else "failed"
        return ImportRunResult(
            self.run_id,
            status,
            self.requested_files,
            len(completed),
            len(failed),
            sum(item[2] for item in completed),
            sum(item[3] for item in completed),
            errors,
        )


def _parser(_: SourceFile, __: bytes) -> ParsedFile:
    return ParsedFile(matches=(), skipped_rows=0, errors=())


def test_continues_after_middle_file_failure_and_returns_repository_summary() -> None:
    """若删除逐文件异常隔离，第三个文件不会完成，测试将失败。"""
    from app.imports.service import ImportService

    repository = _FakeRepository()
    service = ImportService(_FakeDownloader({"E1": DownloadError("timeout")}), _parser, repository)

    result = service.run((_source_file("E0"), _source_file("E1"), _source_file("E2")))

    assert result == ImportRunResult("run-1", "completed_with_errors", 3, 2, 1, 0, 0, ("timeout",))
    assert [item[1] for item in repository.files.values()] == ["completed", "failed", "completed"]


def test_all_success_uses_repository_authoritative_totals() -> None:
    """若服务自行推导状态或汇总而非返回 finish_run 结果，此测试会失败。"""
    from app.imports.service import ImportService

    repository = _FakeRepository()
    result = ImportService(_FakeDownloader({}), _parser, repository).run((_source_file("E0"), _source_file("E1")))

    assert result == ImportRunResult("run-1", "completed", 2, 2, 0, 0, 0, ())


def test_all_failures_return_failed_with_stable_codes() -> None:
    """若失败被泄露为异常文本或错误状态被算成部分成功，此测试会失败。"""
    from app.imports.service import ImportService

    repository = _FakeRepository()
    result = ImportService(
        _FakeDownloader({"E0": DownloadError("timeout"), "E1": DownloadError("http_503")} ),
        _parser,
        repository,
    ).run((_source_file("E0"), _source_file("E1")))

    assert result == ImportRunResult("run-1", "failed", 2, 0, 2, 0, 0, ("timeout", "http_503"))


def test_empty_request_creates_and_finishes_a_stable_empty_run() -> None:
    """若空请求跳过运行审计或留下 running 状态，此测试会失败。"""
    from app.imports.service import ImportService

    result = ImportService(_FakeDownloader({}), _parser, _FakeRepository()).run(())

    assert result == ImportRunResult("run-1", "completed", 0, 0, 0, 0, 0, ())


def test_unknown_exception_is_logged_and_exposed_only_as_unexpected_error(caplog: pytest.LogCaptureFixture) -> None:
    """若把未知异常文本或本地路径写入公共结果，此测试会失败。"""
    from app.imports.service import ImportService

    secret_path = "C:\\Users\\private\\broken.csv"
    repository = _FakeRepository()
    service = ImportService(_FakeDownloader({"E0": RuntimeError(f"broken {secret_path}")}), _parser, repository)

    result = service.run((_source_file("E0"),))

    assert result.errors == ("unexpected_error",)
    assert secret_path not in ",".join(result.errors)
    assert "unexpected_error" in caplog.text
    assert secret_path in caplog.text
