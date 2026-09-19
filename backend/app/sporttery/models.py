"""中国竞彩采集器各层共享的不可变数据模型。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class HttpPayload:
    """一次通过 HTTP 和来源业务状态双重校验的 JSON 响应。"""

    data: dict[str, Any]
    status_code: int
    fetched_at: datetime
    request_url: str

