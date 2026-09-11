from fastapi.testclient import TestClient

from app.main import app


def test_health_endpoint_reports_api_is_ready() -> None:
    response = TestClient(app).get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "ai-football-predictor-api",
    }
