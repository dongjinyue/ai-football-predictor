from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app


def test_database_status_reports_initialized_schema(tmp_path: Path) -> None:
    database_path = tmp_path / "api-test.duckdb"

    with TestClient(create_app(database_path)) as client:
        response = client.get("/api/database/status")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "engine": "duckdb",
        "schema_version": 1,
        "table_count": 6,
    }
