from pathlib import Path

from fastapi.testclient import TestClient

from app.imports.models import ImportRunResult
from app.main import create_app


class FakeImportService:
    """离线服务替身：记录路由传入的已筛选请求，不进行网络访问。"""

    def __init__(self, result: ImportRunResult | None = None, error: Exception | None = None) -> None:
        self.result = result or ImportRunResult("run-123", "completed", 1, 1, 0, 2, 0, ())
        self.error = error
        self.requests = ()

    def run(self, requests):
        self.requests = requests
        if self.error:
            raise self.error
        return self.result


class FakeRepository:
    """为 API 提供稳定的只读摘要，避免测试接触真实 DuckDB。"""

    def __init__(self, latest: ImportRunResult | None = None) -> None:
        self._latest = latest

    def latest_run(self) -> ImportRunResult | None:
        return self._latest

    def data_summary(self) -> dict[str, object]:
        return {
            "competitions": 1,
            "teams": 2,
            "matches": 2,
            "market_snapshots": 3,
            "market_outcomes": 8,
            "latest_kickoff_at": "2024-05-19 15:00:00+00",
            "latest_successful_import_at": "2026-09-12 10:00:00+00",
        }


def build_client(service: FakeImportService | None = None, repository: FakeRepository | None = None) -> TestClient:
    return TestClient(
        create_app(
            Path("unused.duckdb"),
            import_service=service or FakeImportService(),
            import_repository=repository or FakeRepository(),
        )
    )


def test_import_endpoint_runs_exact_requested_competition_and_season() -> None:
    service = FakeImportService()

    response = build_client(service).post(
        "/api/data/import",
        json={"competition_codes": ["E0"], "seasons": ["2324"]},
    )

    assert response.status_code == 200
    assert response.json() == {
        "run_id": "run-123",
        "status": "completed",
        "requested_files": 1,
        "completed_files": 1,
        "failed_files": 0,
        "imported_matches": 2,
        "skipped_rows": 0,
        "errors": [],
    }
    assert [(item.competition_code, item.season) for item in service.requests] == [("E0", "2324")]


def test_import_endpoint_empty_request_uses_default_catalog() -> None:
    service = FakeImportService()

    response = build_client(service).post("/api/data/import", json={})

    assert response.status_code == 200
    assert len(service.requests) == 38 * 5


def test_import_endpoint_rejects_unknown_or_excessive_scope_without_running_service() -> None:
    service = FakeImportService()
    client = build_client(service)

    unknown = client.post("/api/data/import", json={"competition_codes": ["UNKNOWN"]})
    too_many = client.post(
        "/api/data/import",
        json={"competition_codes": ["E0"], "seasons": ["1920", "2021", "2122", "2223", "2324", "2425"]},
    )

    assert unknown.status_code == 422
    assert too_many.status_code == 422
    assert service.requests == ()


def test_import_endpoint_rejects_a_season_not_supported_by_competition_style() -> None:
    service = FakeImportService()

    response = build_client(service).post(
        "/api/data/import",
        json={"competition_codes": ["E0"], "seasons": ["2024"]},
    )

    assert response.status_code == 422
    assert service.requests == ()


def test_import_endpoint_hides_unexpected_exception_details() -> None:
    response = build_client(FakeImportService(error=RuntimeError(r"C:\secret\raw.csv: boom"))).post(
        "/api/data/import",
        json={"competition_codes": ["E0"], "seasons": ["2324"]},
    )

    assert response.status_code == 500
    assert response.json() == {"detail": "internal_error"}


def test_latest_endpoint_returns_stable_null_when_no_run_exists() -> None:
    response = build_client(repository=FakeRepository()).get("/api/data/imports/latest")

    assert response.status_code == 200
    assert response.json() == {"latest_run": None}


def test_summary_endpoint_returns_repository_counts_and_timestamps() -> None:
    response = build_client().get("/api/data/summary")

    assert response.status_code == 200
    assert response.json()["matches"] == 2
    assert response.json()["market_outcomes"] == 8
