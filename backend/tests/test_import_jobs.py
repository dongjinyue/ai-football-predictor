from __future__ import annotations

from threading import Event
from time import monotonic, sleep

from app.imports.models import ImportProgress, ImportRunResult, SourceFile


def _source_file() -> SourceFile:
    return SourceFile(
        source="football_data",
        competition_code="E0",
        competition_name="English Premier League",
        country_code="ENG",
        season="2324",
        url="https://example.test/E0.csv",
    )


class _FakeService:
    def __init__(self) -> None:
        self.started = Event()

    def run(self, requests, progress=None):
        self.started.set()
        if progress is not None:
            progress(
                ImportProgress(
                    completed_files=1,
                    failed_files=0,
                    imported_matches=380,
                    skipped_rows=2,
                    current_competition_code="E0",
                    current_season="2324",
                )
            )
        return ImportRunResult("run-1", "completed", len(requests), 1, 0, 380, 2, ())


def _wait_for_terminal(manager, job_id: str):
    deadline = monotonic() + 5
    while monotonic() < deadline:
        snapshot = manager.get(job_id)
        if snapshot.status in {"completed", "completed_with_errors", "failed"}:
            return snapshot
        sleep(0.01)
    raise AssertionError("import job did not reach a terminal state")


def test_import_job_manager_returns_progress_and_final_result() -> None:
    from app.imports.jobs import ImportJobManager

    service = _FakeService()
    manager = ImportJobManager(service)
    try:
        queued = manager.submit((_source_file(),))
        assert queued.status in {"queued", "running"}
        assert service.started.wait(2)

        finished = _wait_for_terminal(manager, queued.job_id)

        assert finished.status == "completed"
        assert finished.run_id == "run-1"
        assert finished.requested_files == 1
        assert finished.completed_files == 1
        assert finished.imported_matches == 380
        assert finished.skipped_rows == 2
        assert finished.current_competition_code == "E0"
    finally:
        manager.shutdown()


def test_import_job_manager_returns_none_for_unknown_job() -> None:
    from app.imports.jobs import ImportJobManager

    manager = ImportJobManager(_FakeService())
    try:
        assert manager.get("missing") is None
    finally:
        manager.shutdown()
