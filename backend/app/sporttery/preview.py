"""中国竞彩赛事前瞻接口目录与通用响应分类。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal


@dataclass(frozen=True)
class PreviewDataset:
    """一个前瞻数据集的官方接口和参数生成规则。"""

    code: str
    endpoint: str
    parameters: Callable[[int], dict[str, object]]


def _sporttery_match_id(match_id: int) -> dict[str, object]:
    return {"sportteryMatchId": match_id}


def _result_history(match_id: int) -> dict[str, object]:
    return {
        "sportteryMatchId": match_id,
        "termLimits": 10,
        "tournamentFlag": 0,
        "homeAwayFlag": 0,
    }


def _match_tables(match_id: int) -> dict[str, object]:
    return {"gmMatchId": match_id}


def _term_limited(match_id: int, term_limits: int) -> dict[str, object]:
    return {"sportteryMatchId": match_id, "termLimits": term_limits}


PREVIEW_DATASETS: tuple[PreviewDataset, ...] = (
    PreviewDataset(
        "match_feature", "getMatchFeatureV1.qry",
        lambda match_id: _term_limited(match_id, 10),
    ),
    PreviewDataset("result_history", "getResultHistoryV1.qry", _result_history),
    PreviewDataset("match_tables", "getMatchTablesV2.qry", _match_tables),
    PreviewDataset("match_result", "getMatchResultV1.qry", _result_history),
    PreviewDataset(
        "future_matches", "getFutureMatchesV1.qry",
        lambda match_id: _term_limited(match_id, 4),
    ),
    PreviewDataset(
        "match_player", "getMatchPlayerV1.qry",
        lambda match_id: _term_limited(match_id, 3),
    ),
    PreviewDataset(
        "injury_suspension", "getInjurySuspensionV1.qry", _sporttery_match_id,
    ),
)

_DATASET_CODES = frozenset(item.code for item in PREVIEW_DATASETS)


def classify_preview_payload(data: dict[str, Any]) -> Literal["completed", "empty"]:
    """判断前瞻响应是有数据还是来源明确返回空数据。"""
    value = data.get("value")
    if data.get("emptyFlag") is True or value is None or value == {} or value == []:
        return "empty"
    if not isinstance(value, dict):
        # 延迟导入避免 preview 目录和 HTTP 客户端相互导入。
        from app.sporttery.client import SourceBusinessError

        raise SourceBusinessError("invalid_preview_value_shape")
    return "completed"


def is_preview_dataset(code: str) -> bool:
    """校验数据集代码是否属于官方前瞻目录。"""
    return code in _DATASET_CODES
