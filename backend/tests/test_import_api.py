from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.imports.models import (
    ImportRequestScope,
    ImportRunAudit,
    ImportRunResult,
    MarketHistoryGroupView,
    MarketHistorySnapshotView,
    MatchMarketHistoryView,
    MatchQuery,
)
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
        market_history: MatchMarketHistoryView | None = None,
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
        self.market_history = market_history
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

    def get_match_market_history(self, match_id: str):
        if self._error:
            raise self._error
        return self.market_history


def _market_history_fixture(*, markets: tuple[MarketHistoryGroupView, ...] | None = None):
    snapshots = (
        MarketHistorySnapshotView(
            captured_at=datetime(2015, 1, 1, 0, tzinfo=timezone.utc),
            available_at=datetime(2015, 1, 1, 0, tzinfo=timezone.utc),
            outcomes=(("home", 2.1), ("draw", 3.1), ("away", 3.4)),
        ),
        MarketHistorySnapshotView(
            captured_at=datetime(2015, 1, 1, 2, tzinfo=timezone.utc),
            available_at=datetime(2015, 1, 1, 2, tzinfo=timezone.utc),
            outcomes=(("home", 2.0), ("draw", 3.2), ("away", 3.5)),
        ),
    )
    default_markets = (
        MarketHistoryGroupView(
            market_type="match_result",
            line=None,
            source="sporttery",
            provider="china_sports_lottery",
            stage="closing",
            time_precision="exact",
            outcome_codes=("home", "draw", "away"),
            snapshots=snapshots,
        ),
    )
    return MatchMarketHistoryView(
        id="sporttery:70001",
        competition_code="JC25",
        competition_name="英超",
        season="2015",
        kickoff_at=datetime(2015, 1, 2, 12, tzinfo=timezone.utc),
        kickoff_time_precision="date_only",
        home_team="主队",
        away_team="客队",
        half_time_home_score=0,
        half_time_away_score=0,
        home_score=1,
        away_score=0,
        markets=default_markets if markets is None else markets,
    )


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
    assert len(service.requests) == 22 * 5 + 16


def test_import_endpoint_keeps_combined_metadata_for_explicit_extra_league_request() -> None:
    service = FakeImportService()

    response = build_client(service).post(
        "/api/data/import",
        json={"competition_codes": ["BRA"], "seasons": ["2021-2025"]},
    )

    assert response.status_code == 200
    assert len(service.requests) == 1
    request = service.requests[0]
    assert request.source_scope == "combined"
    assert request.url.endswith("/new/BRA.csv")
    assert request.start_year == 2021
    assert request.end_year == 2025


def test_import_endpoint_accepts_historical_year_range_for_all_competitions() -> None:
    service = FakeImportService()

    response = build_client(service).post(
        "/api/data/import",
        json={"start_year": 2000, "end_year": 2020},
    )

    assert response.status_code == 200
    assert len(service.requests) == 22 * 20 + 16
    assert service.requests[0].season == "0001"
    assert service.requests[-1].season == "2000-2020"


def test_async_import_endpoint_submits_job_and_exposes_progress() -> None:
    from app.imports.jobs import ImportJobSnapshot

    service = FakeImportService()
    submitted: list[tuple] = []
    snapshot = ImportJobSnapshot(
        job_id="job-1",
        run_id=None,
        status="queued",
        requested_files=22 * 20 + 16,
        completed_files=0,
        failed_files=0,
        imported_matches=0,
        skipped_rows=0,
        errors=(),
    )

    class FakeJobManager:
        def submit(self, requests):
            submitted.append(requests)
            return snapshot

        def get(self, job_id):
            return snapshot if job_id == "job-1" else None

    application = FastAPI()
    application.include_router(
        create_import_router(service, FakeRepository(), FakeJobManager()),
        prefix="/api/data",
    )
    client = TestClient(application)

    created = client.post(
        "/api/data/import/jobs",
        json={"start_year": 2000, "end_year": 2020},
    )
    fetched = client.get("/api/data/import/jobs/job-1")

    assert created.status_code == 202
    assert created.json()["job_id"] == "job-1"
    assert created.json()["requested_files"] == 22 * 20 + 16
    assert fetched.status_code == 200
    assert fetched.json()["status"] == "queued"
    assert len(submitted) == 1
    assert len(submitted[0]) == 22 * 20 + 16


def test_import_catalog_endpoint_exposes_competitions_and_year_bounds() -> None:
    response = build_client().get("/api/data/import/catalog")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["competitions"]) == 38
    assert payload["start_year"] == 2000
    assert payload["end_year"] == 2020
    assert payload["competitions"][0] == {
        "code": "E0",
        "name": "English Premier League",
        "country_code": "ENG",
        "season_style": "split_year",
    }


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
        filters=SimpleNamespace(
            competitions=(SimpleNamespace(code="E0", name="英格兰超级联赛"),),
            seasons=("2324",),
        ),
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
                kickoff_time_precision="date_only",
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
            "start_date": "2024-05-01",
            "end_date": "2024-05-31",
        },
    )

    assert response.status_code == 200
    assert response.json()["items"][0] == {
        "id": "match-1",
        "competition_code": "E0",
        "competition_name": "English Premier League",
        "season": "2324",
        "kickoff_at": "2024-05-19T15:00:00Z",
        "kickoff_time_precision": "date_only",
        "home_team": "Arsenal",
        "away_team": "Everton",
        "half_time_home_score": 1,
        "half_time_away_score": 0,
        "half_time_result": "home",
        "home_score": 2,
        "away_score": 1,
        "full_time_result": "home",
        "total_goals": 3,
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
        MatchQuery(
            page=1, page_size=20, competition="E0", season="2324", team="Arsenal",
            start_date=date(2024, 5, 1), end_date=date(2024, 5, 31),
        )
    ]
    assert response.json()["filters"]["competitions"] == [
        {"code": "E0", "name": "英格兰超级联赛"}
    ]


def test_matches_endpoint_returns_unknown_derived_results_when_scores_are_missing() -> None:
    page = SimpleNamespace(
        page=1,
        total_items=1,
        total_pages=1,
        filters=SimpleNamespace(competitions=(), seasons=()),
        items=(
            SimpleNamespace(
                id="match-1",
                competition_code="E0",
                competition_name="English Premier League",
                season="2324",
                kickoff_at=datetime(2024, 5, 19, 15, tzinfo=timezone.utc),
                home_team="Arsenal",
                away_team="Everton",
                half_time_home_score=None,
                half_time_away_score=None,
                home_score=None,
                away_score=None,
                markets=(),
            ),
        ),
    )

    response = build_client(repository=FakeRepository(matches=page)).get("/api/data/matches")

    assert response.status_code == 200
    assert response.json()["items"][0]["half_time_result"] is None
    assert response.json()["items"][0]["full_time_result"] is None
    assert response.json()["items"][0]["total_goals"] is None


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


def test_match_market_history_endpoint_returns_full_timeline() -> None:
    repository = FakeRepository(market_history=_market_history_fixture())

    response = build_client(repository=repository).get(
        "/api/data/matches/sporttery%3A70001/market-history"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == "sporttery:70001"
    assert payload["markets"][0]["market_type"] == "match_result"
    assert payload["markets"][0]["outcome_codes"] == ["home", "draw", "away"]
    assert [row["captured_at"] for row in payload["markets"][0]["snapshots"]] == [
        "2015-01-01T00:00:00Z",
        "2015-01-01T02:00:00Z",
    ]


def test_match_market_history_endpoint_returns_known_match_without_markets() -> None:
    repository = FakeRepository(market_history=_market_history_fixture(markets=()))

    response = build_client(repository=repository).get(
        "/api/data/matches/sporttery%3A70001/market-history"
    )

    assert response.status_code == 200
    assert response.json()["markets"] == []


def test_match_market_history_endpoint_returns_404_for_unknown_match() -> None:
    response = build_client(repository=FakeRepository()).get(
        "/api/data/matches/missing/market-history"
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "match_not_found"}


def test_match_market_history_endpoint_hides_repository_error_details() -> None:
    response = build_client(repository=FakeRepository(error=RuntimeError("secret path"))).get(
        "/api/data/matches/sporttery%3A70001/market-history"
    )

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
