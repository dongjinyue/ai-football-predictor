"""导入协调器的离线行为测试：所有边界依赖均使用明确的 fake。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock

import pytest

from app.imports.downloader import DownloadError, DownloadedFile
from app.imports.models import FileImportResult, ImportProgress, ImportRunResult, ParsedFile, SourceFile
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
    before_download: callable | None = None

    def download(self, request: SourceFile) -> DownloadedFile:
        if self.before_download is not None:
            self.before_download()
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
        self.start_run_calls: list[tuple[str, int]] = []
        self.download_audits: dict[str, tuple[str, str, datetime]] = {}

    def start_run(self, source: str, requested_files: int) -> str:
        assert source == "football_data"
        self.start_run_calls.append((source, requested_files))
        self.requested_files = requested_files
        return self.run_id

    def start_file(
        self,
        run_id: str,
        source_file: SourceFile,
    ) -> str:
        assert run_id == self.run_id
        self.file_counter += 1
        file_id = f"file-{self.file_counter}"
        self.files[file_id] = (source_file, "pending", 0, 0, ())
        return file_id

    def record_download(
        self, file_id: str, *, local_path: str, sha256: str, downloaded_at: datetime
    ) -> None:
        assert self.files[file_id][1] == "pending"
        self.download_audits[file_id] = (local_path, sha256, downloaded_at)

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


def test_overlapping_runs_are_rejected_and_lock_is_released() -> None:
    """两个服务实例的正常重复提交不能同时写入，结束后可以重试。"""
    from app.imports.service import ImportService, ImportServiceError

    entered, release = Event(), Event()

    def hold_download():
        entered.set()
        assert release.wait(10)

    first = ImportService(_FakeDownloader({}, hold_download), _parser, _FakeRepository())
    second_repository = _FakeRepository()
    second = ImportService(_FakeDownloader({}), _parser, second_repository)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(first.run, (_source_file("E0"),))
        assert entered.wait(10)
        try:
            with pytest.raises(ImportServiceError, match="import_in_progress"):
                second.run((_source_file("E0"),))
            assert second_repository.start_run_calls == []
        finally:
            release.set()
        assert future.result(timeout=10).status == "completed"
    assert second.run((_source_file("E0"),)).status == "completed"


def test_continues_after_middle_file_failure_and_returns_repository_summary() -> None:
    """若删除逐文件异常隔离，第三个文件不会完成，测试将失败。"""
    from app.imports.service import ImportService

    repository = _FakeRepository()
    service = ImportService(_FakeDownloader({"E1": DownloadError("timeout")}), _parser, repository)

    result = service.run((_source_file("E0"), _source_file("E1"), _source_file("E2")))

    assert result == ImportRunResult("run-1", "completed_with_errors", 3, 2, 1, 0, 0, ("timeout",))
    assert [item[1] for item in repository.files.values()] == ["completed", "failed", "completed"]


def test_starts_pending_file_before_download_and_persists_download_audit() -> None:
    """若下载在文件审计之前发生，下载器观察不到 pending 记录，测试将失败。"""
    from app.imports.service import ImportService

    repository = _FakeRepository()

    def assert_pending_audit_exists() -> None:
        assert [item[1] for item in repository.files.values()] == ["pending"]

    result = ImportService(
        _FakeDownloader({}, before_download=assert_pending_audit_exists), _parser, repository
    ).run((_source_file("E0"),))

    assert result.status == "completed"
    assert repository.download_audits == {
        "file-1": ("raw\\E0\\matches.csv", "safe-checksum", datetime(2026, 9, 10, tzinfo=timezone.utc))
    }


def test_mixed_sources_are_rejected_before_creating_a_run() -> None:
    """若不先验证来源，运行会被错误归属给第一个来源，测试将失败。"""
    from app.imports.service import ImportService, ImportServiceError

    repository = _FakeRepository()
    other_source = SourceFile("another_source", "E1", "Other", "ENG", "2324", "https://example.test/E1.csv")

    with pytest.raises(ImportServiceError, match="mixed_sources"):
        ImportService(_FakeDownloader({}), _parser, repository).run((_source_file("E0"), other_source))

    assert repository.start_run_calls == []


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


def test_progress_callback_receives_completed_file_counts() -> None:
    """页面进度必须在每个文件结束后更新，而不是等整批任务结束才有数据。"""
    from app.imports.service import ImportService

    progress: list[ImportProgress] = []
    result = ImportService(_FakeDownloader({}), _parser, _FakeRepository()).run(
        (_source_file("E0"), _source_file("E1")),
        progress=progress.append,
    )

    assert result.status == "completed"
    assert [item.completed_files for item in progress] == [1, 2]
    assert [item.current_competition_code for item in progress] == ["E0", "E1"]


def test_downloads_multiple_files_concurrently_before_serial_import() -> None:
    """批量导入应并发下载文件，同时保持后续数据库写入顺序。"""
    from app.imports.service import ImportService

    started = Event()
    release = Event()
    state = {"count": 0}
    lock = Lock()

    def before_download() -> None:
        with lock:
            state["count"] += 1
            if state["count"] == 2:
                started.set()
        assert release.wait(3)

    service = ImportService(_FakeDownloader({}, before_download), _parser, _FakeRepository())
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(service.run, (_source_file("E0"), _source_file("E1")))
        try:
            assert started.wait(1), "两个文件没有同时进入下载阶段"
        finally:
            release.set()
        assert future.result(timeout=5).status == "completed"
