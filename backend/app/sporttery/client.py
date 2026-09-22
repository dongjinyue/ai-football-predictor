"""中国竞彩官方接口的同步、限次重试客户端。"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import date, datetime, timezone
from typing import Any

import httpx

from app.sporttery.models import HttpPayload
from app.sporttery.preview import PreviewDataset


BASE_URL = "https://webapi.sporttery.cn/gateway/uniform/football"
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/140.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.lottery.gov.cn/jc/zqsgkj/",
}


class SportterySourceError(RuntimeError):
    """对上层暴露稳定错误代码，不泄露响应正文。"""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class BlockedBySourceError(SportterySourceError):
    """来源安全策略拒绝请求，任务应保存检查点并停止。"""


class RetryableSourceError(SportterySourceError):
    """有限重试后仍未恢复的临时网络或服务错误。"""


class SourceBusinessError(SportterySourceError):
    """HTTP 成功但来源业务状态或 JSON 结构不符合契约。"""


class SportteryClient:
    """封装比赛列表和固定奖金两个官方接口。"""

    def __init__(
        self,
        client: httpx.Client | None = None,
        *,
        max_attempts: int = 3,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts_must_be_positive")
        self.client = client or httpx.Client(trust_env=False)
        self.client.headers.update(DEFAULT_HEADERS)
        self.client.timeout = httpx.Timeout(30.0, connect=10.0, read=30.0)
        self.max_attempts = max_attempts
        self.sleep = sleep

    def fetch_match_page(
        self,
        begin: date,
        end: date,
        page_no: int,
        page_size: int = 30,
    ) -> HttpPayload:
        """按日期和来源返回的真实页码读取一页完赛比赛。"""
        if end < begin:
            raise ValueError("end_before_begin")
        if page_no < 1 or page_size < 1:
            raise ValueError("invalid_pagination")
        return self._get(
            "getUniformMatchResultV1.qry",
            {
                "matchBeginDate": begin.isoformat(),
                "matchEndDate": end.isoformat(),
                "leagueId": "",
                "pageSize": page_size,
                "pageNo": page_no,
                "isFix": 0,
                "matchPage": 1,
                "pcOrWap": 1,
            },
        )

    def fetch_fixed_bonus(self, match_id: int) -> HttpPayload:
        """读取一场比赛全部玩法的固定奖金历史。"""
        if match_id <= 0:
            raise ValueError("invalid_match_id")
        return self._get(
            "getFixedBonusV1.qry",
            {"clientCode": 3001, "matchId": match_id},
        )

    def fetch_preview(self, dataset: PreviewDataset, match_id: int) -> HttpPayload:
        """按统一的中国竞彩比赛编号读取一个赛事前瞻数据集。"""
        if match_id <= 0:
            raise ValueError("invalid_match_id")
        return self._get(
            dataset.endpoint,
            dataset.parameters(match_id),
            allow_empty_value=True,
        )

    def _get(
        self,
        endpoint: str,
        params: dict[str, Any],
        *,
        allow_empty_value: bool = False,
    ) -> HttpPayload:
        last_code = "request_failed"
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = self.client.get(f"{BASE_URL}/{endpoint}", params=params)
            except httpx.TimeoutException:
                last_code = "timeout"
                if attempt < self.max_attempts:
                    self.sleep(float(2 ** (attempt - 1)))
                    continue
                raise RetryableSourceError(last_code) from None
            except httpx.ConnectError:
                last_code = "connection_error"
                if attempt < self.max_attempts:
                    self.sleep(float(2 ** (attempt - 1)))
                    continue
                raise RetryableSourceError(last_code) from None

            if response.status_code == 567:
                raise BlockedBySourceError("http_567")
            if response.status_code == 429 or response.status_code >= 500:
                last_code = f"http_{response.status_code}"
                if attempt < self.max_attempts:
                    self.sleep(float(2 ** (attempt - 1)))
                    continue
                raise RetryableSourceError(last_code)
            if response.status_code != 200:
                raise SourceBusinessError(f"http_{response.status_code}")

            return self._validated_payload(response, allow_empty_value=allow_empty_value)

        raise RetryableSourceError(last_code)

    @staticmethod
    def _validated_payload(
        response: httpx.Response,
        *,
        allow_empty_value: bool = False,
    ) -> HttpPayload:
        try:
            data = response.json()
        except ValueError as error:
            raise SourceBusinessError("invalid_json") from error
        if not isinstance(data, dict):
            raise SourceBusinessError("invalid_json_shape")
        if data.get("success") is not True or str(data.get("errorCode")) != "0":
            code = str(data.get("errorCode") or "unknown")
            raise SourceBusinessError(f"business_{code}")
        value = data.get("value")
        if not isinstance(value, dict) and not (
            allow_empty_value and (value is None or isinstance(value, list))
        ):
            raise SourceBusinessError("invalid_value_shape")
        return HttpPayload(
            data=data,
            status_code=response.status_code,
            fetched_at=datetime.now(timezone.utc),
            request_url=str(response.request.url),
        )

