from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.imports.models import ImportRequestScope, ImportRunAudit, ImportRunResult, MatchQuery
from app.imports.router import create_import_router
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

    def __init__(
        self,
        latest: ImportRunAudit | None = None,
        matches: object | None = None,
        error: Exception | None = None,
    ) -> None:
        self._latest = latest
        self._matches = matches or SimpleNamespace(
            page=1,
            total_items=0,
            total_pages=0,
            filters=SimpleNamespace(competitions=(), seasons=()),
            items=(),
        )
        self._error = error
        self.match_queries = []

    def latest_run(self) -> ImportRunAudit | None:
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

    def list_matches(self, query):
        self.match_queries.append(query)
        if self._error:
            raise self._error
        return self._matches


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


def test_import_router_factory_accepts_explicit_dependencies_without_app_state() -> None:
    """公开工厂契约允许直接注入依赖，三条路由均不能回退读取 app.state。"""
    service = FakeImportService()
    repository = FakeRepository()
    application = FastAPI()
    application.include_router(create_import_router(service, repository), prefix="/api/data")
    client = TestClient(application)

    imported = client.post(
        "/api/data/import",
        json={"competition_codes": ["E0"], "seasons": ["2324"]},
    )
    latest = client.get("/api/data/imports/latest")
    summary = client.get("/api/data/summary")

    assert imported.status_code == 200
    assert latest.json() == {"latest_run": None}
    assert summary.json()["matches"] == 2
    assert [(item.competition_code, item.season) for item in service.requests] == [("E0", "2324")]


def test_import_endpoint_empty_request_uses_default_catalog() -> None:
    service = FakeImportService()

    response = build_client(service).post("/api/data/import", json={})

    assert response.status_code == 200
    assert len(service.requests) == 38 * 5


@pytest.mark.parametrize("payload", [
    {"competition_code": ["E0"]},
    {"source": "other_source"},
    {"url": "https://example.test/untrusted.csv"},
])
def test_import_endpoint_rejects_unknown_fields_without_expanding_scope(payload) -> None:
    """范围字段拼错必须报错，不能悄悄扩大到默认全量下载。"""
    service = FakeImportService()
    response = build_client(service).post("/api/data/import", json=payload)
    assert response.status_code == 422
    assert service.requests == ()


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


@pytest.mark.parametrize("season", ["9900", "0001", "2627"])
def test_import_endpoint_rejects_split_year_seasons_outside_the_current_catalog(season: str) -> None:
    """不能仅根据 YYZZ 格式推断目录可用性，防止世纪歧义与未来范围。"""
    service = FakeImportService()

    response = build_client(service).post(
        "/api/data/import",
        json={"competition_codes": ["E0"], "seasons": [season]},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "unknown_season"}
    assert service.requests == ()


def test_import_endpoint_hides_unexpected_exception_details() -> None:
    response = build_client(FakeImportService(error=RuntimeError(r"C:\secret\raw.csv: boom"))).post(
        "/api/data/import",
        json={"competition_codes": ["E0"], "seasons": ["2324"]},
    )

    assert response.status_code == 500
    assert response.json() == {"detail": "internal_error"}


def test_import_endpoint_reports_overlap_as_conflict() -> None:
    from app.imports.service import ImportServiceError
    response = build_client(FakeImportService(error=ImportServiceError("import_in_progress"))).post(
        "/api/data/import", json={"competition_codes": ["E0"], "seasons": ["2324"]}
    )
    assert response.status_code == 409
    assert response.json() == {"detail": "import_in_progress"}


def test_latest_endpoint_returns_stable_null_when_no_run_exists() -> None:
    response = build_client(repository=FakeRepository()).get("/api/data/imports/latest")

    assert response.status_code == 200
    assert response.json() == {"latest_run": None}


def test_latest_endpoint_returns_audited_source_times_and_requested_scope() -> None:
    latest = ImportRunAudit(
        result=ImportRunResult("run-123", "completed", 1, 1, 0, 2, 0, ()),
        source="football_data",
        started_at=datetime(2026, 9, 12, 10, 0, tzinfo=timezone.utc),
        finished_at=datetime(2026, 9, 12, 10, 1, tzinfo=timezone.utc),
        requested_scope=(ImportRequestScope(competition_code="E0", season="2324"),),
    )

    response = build_client(repository=FakeRepository(latest)).get("/api/data/imports/latest")

    assert response.status_code == 200
    assert response.json() == {
        "latest_run": {
            "run_id": "run-123",
            "status": "completed",
            "source": "football_data",
            "started_at": "2026-09-12T10:00:00Z",
            "finished_at": "2026-09-12T10:01:00Z",
            "requested_files": 1,
            "requested_scope": [{"competition_code": "E0", "season": "2324"}],
            "completed_files": 1,
            "failed_files": 0,
            "imported_matches": 2,
            "skipped_rows": 0,
            "errors": [],
        }
    }


def test_summary_endpoint_returns_repository_counts_and_timestamps() -> None:
    response = build_client().get("/api/data/summary")

    assert response.status_code == 200
    assert response.json()["matches"] == 2
    assert response.json()["market_outcomes"] == 8


def test_matches_endpoint_returns_stable_page_and_trims_optional_filters() -> None:
    """路由向浏览器公开稳定字段，并将空白筛选规范为未筛选。"""
    page = SimpleNamespace(
        page=1,
        total_items=1,
        total_pages=1,
        filters=SimpleNamespace(competitions=("E0",), seasons=("2324",)),
        items=(
            SimpleNamespace(
                id="match-1",
                competition_code="E0",
                competition_name="English Premier League",
                season="2324",
                kickoff_at=datetime(2024, 5, 19, 15, tzinfo=timezone.utc),
                home_team="Arsenal",
                away_team="Everton",
                half_time_home_score=1,
                half_time_away_score=0,
                home_score=2,
                away_score=1,
                markets=(
                    SimpleNamespace(
                        market_type="match_result",
                        stage="closing",
                        line=None,
                        time_precision="kickoff_bound",
                        source="football_data",
                        provider="average",
                        captured_at=datetime(2024, 5, 19, 14, 55, tzinfo=timezone.utc),
                        available_at=datetime(2024, 5, 19, 15, tzinfo=timezone.utc),
                        outcomes=(("home", 1.5), ("draw", 3.6), ("away", 6.0)),
                    ),
                ),
            ),
        ),
    )
    repository = FakeRepository(matches=page)

    response = build_client(repository=repository).get(
        "/api/data/matches",
        params={
            "page": 1,
            "page_size": 20,
            "competition": " E0 ",
            "season": " 2324 ",
            "team": " Arsenal ",
        },
    )

    assert response.status_code == 200
    assert response.json()["items"][0] == {
        "id": "match-1",
        "competition_code": "E0",
        "competition_name": "English Premier League",
        "season": "2324",
        "kickoff_at": "2024-05-19T15:00:00Z",
        "home_team": "Arsenal",
        "away_team": "Everton",
        "half_time_home_score": 1,
        "half_time_away_score": 0,
        "home_score": 2,
        "away_score": 1,
        "markets": [
            {
                "market_type": "match_result",
                "stage": "closing",
                "line": None,
                "time_precision": "kickoff_bound",
                "source": "football_data",
                "provider": "average",
                "captured_at": "2024-05-19T14:55:00Z",
                "available_at": "2024-05-19T15:00:00Z",
                "outcomes": [
                    {"outcome_code": "home", "odds": 1.5},
                    {"outcome_code": "draw", "odds": 3.6},
                    {"outcome_code": "away", "odds": 6.0},
                ],
            }
        ],
    }
    assert repository.match_queries == [
        MatchQuery(page=1, page_size=20, competition="E0", season="2324", team="Arsenal")
    ]


@pytest.mark.parametrize("params", [{"page": 0}, {"page_size": 101}])
def test_matches_endpoint_rejects_invalid_pagination(params: dict[str, int]) -> None:
    """HTTP 边界在访问仓储前拒绝无效分页参数。"""
    repository = FakeRepository()

    response = build_client(repository=repository).get("/api/data/matches", params=params)

    assert response.status_code == 422
    assert repository.match_queries == []


def test_matches_endpoint_hides_unexpected_repository_error_details() -> None:
    """数据库异常只能记录在服务端，不能把本机路径发送给浏览器。"""
    response = build_client(
        repository=FakeRepository(error=RuntimeError(r"C:\\secret\\history.duckdb: unavailable"))
    ).get("/api/data/matches")

    assert response.status_code == 500
    assert response.json() == {"detail": "internal_error"}
    assert "C:\\secret\\history.duckdb" not in response.text


def test_create_app_defers_real_import_dependencies_until_lifespan(monkeypatch: pytest.MonkeyPatch) -> None:
    """仅构造应用不能创建默认数据库或 HTTP 客户端，便于导入模块与离线测试。"""
    import app.main as main

    repository_factory = Mock()
    client_factory = Mock()
    monkeypatch.setattr(main, "ImportRepository", repository_factory)
    monkeypatch.setattr(main.httpx, "Client", client_factory)

    main.create_app()

    repository_factory.assert_not_called()
    client_factory.assert_not_called()


def test_injected_fake_app_lifespan_has_no_default_database_or_client_side_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """完整进入 fake 应用生命周期也不能初始化默认依赖。"""
    import app.main as main

    initialize = Mock()
    client_factory = Mock()
    monkeypatch.setattr(main, "initialize_database", initialize)
    monkeypatch.setattr(main.httpx, "Client", client_factory)

    application = main.create_app(
        Path("unused.duckdb"),
        import_service=FakeImportService(),
        import_repository=FakeRepository(),
    )
    with TestClient(application):
        pass

    initialize.assert_not_called()
    client_factory.assert_not_called()


def test_lifespan_closes_client_when_initialization_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """启动失败也必须释放已创建的连接池。"""
    import app.main as main

    client = Mock()
    monkeypatch.setattr(main.httpx, "Client", Mock(return_value=client))
    monkeypatch.setattr(main, "initialize_database", Mock(side_effect=RuntimeError("database unavailable")))

    application = main.create_app()

    with pytest.raises(RuntimeError, match="database unavailable"):
        with TestClient(application):
            pass

    client.close.assert_called_once_with()
