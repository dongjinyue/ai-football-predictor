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
        "schema_version": 6,
        "table_count": 9,
    }


def test_data_api_allows_the_local_vite_development_origin(tmp_path: Path) -> None:
    """前端开发服务器必须能读取本机历史比赛数据 API。"""
    database_path = tmp_path / "api-cors-test.duckdb"

    with TestClient(create_app(database_path)) as client:
        response = client.get(
            "/api/data/summary",
            headers={"Origin": "http://127.0.0.1:4173"},
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:4173"


def test_database_status_starts_with_a_socks_proxy_environment(
    tmp_path: Path, monkeypatch
) -> None:
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.setenv(name, "socks5h://127.0.0.1:7897")

    with TestClient(create_app(tmp_path / "proxy-test.duckdb")) as client:
        response = client.get("/api/database/status")

    assert response.status_code == 200
