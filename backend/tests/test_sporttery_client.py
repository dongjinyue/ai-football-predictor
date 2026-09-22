"""中国竞彩官方接口客户端的离线契约测试。"""

from __future__ import annotations

from datetime import date

import httpx
import pytest

from app.sporttery.client import (
    BlockedBySourceError,
    RetryableSourceError,
    SourceBusinessError,
    SportteryClient,
)
from app.sporttery.preview import PREVIEW_DATASETS


SUCCESS = {
    "success": True,
    "errorCode": "0",
    "errorMessage": "处理成功",
    "value": {"pages": 1, "matchResult": []},
}


def _http_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_match_page_uses_official_parameters_and_browser_headers() -> None:
    """修改官方参数名或移除可识别请求头时，本测试应失败。"""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=SUCCESS)

    client = SportteryClient(_http_client(handler), sleep=lambda _: None)
    payload = client.fetch_match_page(date(2015, 1, 1), date(2015, 1, 3), 2, 30)

    request = requests[0]
    assert request.url.path.endswith("/getUniformMatchResultV1.qry")
    assert dict(request.url.params) == {
        "matchBeginDate": "2015-01-01",
        "matchEndDate": "2015-01-03",
        "leagueId": "",
        "pageSize": "30",
        "pageNo": "2",
        "isFix": "0",
        "matchPage": "1",
        "pcOrWap": "1",
    }
    assert request.headers["user-agent"].startswith("Mozilla/5.0")
    assert request.headers["accept"] == "application/json, text/plain, */*"
    assert request.headers["referer"] == "https://www.lottery.gov.cn/jc/zqsgkj/"
    assert payload.data == SUCCESS
    assert payload.status_code == 200
    assert payload.fetched_at.tzinfo is not None


def test_fixed_bonus_uses_match_id_and_client_code() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=SUCCESS)

    SportteryClient(_http_client(handler), sleep=lambda _: None).fetch_fixed_bonus(62373)

    assert seen[0].url.path.endswith("/getFixedBonusV1.qry")
    assert dict(seen[0].url.params) == {"clientCode": "3001", "matchId": "62373"}


def test_preview_requests_use_official_endpoint_parameters() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={
            "success": True,
            "errorCode": "0",
            "emptyFlag": False,
            "value": {"home": {}},
        })

    client = SportteryClient(_http_client(handler), sleep=lambda _: None)
    for dataset in PREVIEW_DATASETS:
        client.fetch_preview(dataset, 2041615)

    assert [(request.url.path.rsplit("/", 1)[-1], dict(request.url.params)) for request in seen] == [
        ("getMatchFeatureV1.qry", {"termLimits": "10", "sportteryMatchId": "2041615"}),
        ("getResultHistoryV1.qry", {
            "sportteryMatchId": "2041615", "termLimits": "10",
            "tournamentFlag": "0", "homeAwayFlag": "0",
        }),
        ("getMatchTablesV2.qry", {"gmMatchId": "2041615"}),
        ("getMatchResultV1.qry", {
            "sportteryMatchId": "2041615", "termLimits": "10",
            "tournamentFlag": "0", "homeAwayFlag": "0",
        }),
        ("getFutureMatchesV1.qry", {"sportteryMatchId": "2041615", "termLimits": "4"}),
        ("getMatchPlayerV1.qry", {"sportteryMatchId": "2041615", "termLimits": "3"}),
        ("getInjurySuspensionV1.qry", {"sportteryMatchId": "2041615"}),
    ]


def test_preview_accepts_successful_empty_value() -> None:
    client = SportteryClient(
        _http_client(lambda request: httpx.Response(200, json={
            "success": True,
            "errorCode": "0",
            "emptyFlag": True,
            "value": None,
        })),
        sleep=lambda _: None,
    )

    payload = client.fetch_preview(PREVIEW_DATASETS[0], 2041615)

    assert payload.data["emptyFlag"] is True


def test_preview_rejects_non_positive_match_id() -> None:
    with pytest.raises(ValueError, match="invalid_match_id"):
        SportteryClient(sleep=lambda _: None).fetch_preview(PREVIEW_DATASETS[0], 0)


def test_http_567_stops_immediately_without_retrying() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(567, text="blocked")

    with pytest.raises(BlockedBySourceError, match="http_567"):
        SportteryClient(_http_client(handler), sleep=lambda _: None).fetch_fixed_bonus(62373)

    assert attempts == 1


@pytest.mark.parametrize("status_code", [429, 500, 503])
def test_retryable_status_uses_bounded_exponential_backoff(status_code: int) -> None:
    attempts = 0
    waits: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(status_code, text="temporary")

    with pytest.raises(RetryableSourceError, match=f"http_{status_code}"):
        SportteryClient(
            _http_client(handler), max_attempts=3, sleep=waits.append
        ).fetch_fixed_bonus(62373)

    assert attempts == 3
    assert waits == [1.0, 2.0]


def test_timeout_is_retried_and_last_error_is_stable() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(RetryableSourceError, match="timeout"):
        SportteryClient(
            _http_client(handler), max_attempts=2, sleep=lambda _: None
        ).fetch_fixed_bonus(62373)

    assert attempts == 2


def test_http_200_business_error_is_not_treated_as_success() -> None:
    response = {"success": False, "errorCode": "E100", "errorMessage": "参数错误"}
    with pytest.raises(SourceBusinessError, match="business_E100"):
        SportteryClient(
            _http_client(lambda request: httpx.Response(200, json=response)),
            sleep=lambda _: None,
        ).fetch_fixed_bonus(62373)


def test_non_object_json_is_rejected() -> None:
    with pytest.raises(SourceBusinessError, match="invalid_json_shape"):
        SportteryClient(
            _http_client(lambda request: httpx.Response(200, json=[])),
            sleep=lambda _: None,
        ).fetch_fixed_bonus(62373)
