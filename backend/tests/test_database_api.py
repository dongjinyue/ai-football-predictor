from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1"])
@pytest.mark.parametrize("port", [4173, 4174, 5173, 5174])
def test_local_frontend_cors(tmp_path: Path, host: str, port: int) -> None:
    """本地开发和预览地址均可读取数据并发送导入预检请求。"""
    origin = f"http://{host}:{port}"
    with TestClient(create_app(tmp_path / "cors.duckdb")) as client:
        for endpoint in ("summary", "matches?page=1&page_size=10"):
            response = client.get(f"/api/data/{endpoint}", headers={"Origin": origin})
            assert response.status_code == 200
            assert response.headers.get("access-control-allow-origin") == origin
        response = client.options("/api/data/import", headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        })
        assert response.status_code == 200
        assert response.headers.get("access-control-allow-origin") == origin


def test_external_origin_is_not_allowed(tmp_path: Path) -> None:
    """本地来源配置不能意外放行外部网站。"""
    with TestClient(create_app(tmp_path / "external-cors.duckdb")) as client:
        response = client.get("/api/data/summary", headers={"Origin": "https://example.com"})
    assert "access-control-allow-origin" not in response.headers


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


def test_data_api_allows_the_active_local_vite_origin(tmp_path: Path) -> None:
    """当前使用的 4174 前端端口也必须通过跨域校验。"""
    database_path = tmp_path / "api-cors-active-origin-test.duckdb"

    with TestClient(create_app(database_path)) as client:
        response = client.get(
            "/api/data/summary",
            headers={"Origin": "http://127.0.0.1:4174"},
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:4174"


def test_database_status_starts_with_a_socks_proxy_environment(
    tmp_path: Path, monkeypatch
) -> None:
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.setenv(name, "socks5h://127.0.0.1:7897")

    with TestClient(create_app(tmp_path / "proxy-test.duckdb")) as client:
        response = client.get("/api/database/status")

    assert response.status_code == 200
