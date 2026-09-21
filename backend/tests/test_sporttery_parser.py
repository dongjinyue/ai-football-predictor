"""中国竞彩比赛和固定奖金 JSON 的纯解析测试。"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from app.sporttery.parser import SportteryParseError, parse_fixed_bonus, parse_match_page


FIXTURES = Path(__file__).parent / "fixtures"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_parse_match_page_preserves_pagination_identity_and_results() -> None:
    page = parse_match_page(_fixture("sporttery_match_page.json"))

    assert (page.page_no, page.page_size, page.pages, page.total) == (1, 30, 2, 44)
    assert len(page.matches) == 2
    match = page.matches[0]
    assert match.match_id == 62373
    assert match.match_date == date(2015, 1, 3)
    assert (match.league_id, match.league_name, match.league_abbreviation) == (
        25,
        "英格兰超级联赛",
        "英超",
    )
    assert (match.home_team_id, match.home_team, match.away_team_id, match.away_team) == (
        1001,
        "主队甲",
        1002,
        "客队乙",
    )
    assert (match.half_time_home_score, match.half_time_away_score) == (1, 0)
    assert (match.home_score, match.away_score, match.result) == (2, 1, "home")


def test_parse_fixed_bonus_maps_all_five_markets_and_shanghai_time() -> None:
    record = parse_fixed_bonus(_fixture("sporttery_fixed_bonus.json"))

    assert record.match_id == 62373
    assert record.is_cancelled is False
    assert record.rejected_snapshots == 0
    assert {snapshot.market_type for snapshot in record.snapshots} == {
        "match_result",
        "handicap_result",
        "total_goals",
        "correct_score",
        "half_full",
    }
    had = next(item for item in record.snapshots if item.market_type == "match_result")
    assert had.captured_at == datetime(2015, 1, 2, 1, 30, tzinfo=timezone.utc)
    assert had.line is None
    assert had.outcomes == (("home", 1.8), ("draw", 3.2), ("away", 4.2))
    hhad = next(item for item in record.snapshots if item.market_type == "handicap_result")
    assert hhad.line == -1.0
    goals = next(item for item in record.snapshots if item.market_type == "total_goals")
    assert goals.outcomes[-1] == ("7_plus", 16.0)
    scores = next(item for item in record.snapshots if item.market_type == "correct_score")
    assert len(scores.outcomes) == 31
    assert ("other_home", 20.0) in scores.outcomes
    half_full = next(item for item in record.snapshots if item.market_type == "half_full")
    assert ("draw_away", 10.0) in half_full.outcomes
    assert record.single_pools == (("HAD", True), ("TTG", False))


def test_empty_market_list_is_valid_and_produces_no_snapshot() -> None:
    payload = _fixture("sporttery_fixed_bonus.json")
    payload["value"]["oddsHistory"]["hadList"] = []

    record = parse_fixed_bonus(payload)

    assert "match_result" not in {item.market_type for item in record.snapshots}
    assert record.rejected_snapshots == 0


@pytest.mark.parametrize("invalid_odds", ["0", "-1", "nan", "missing"])
def test_invalid_or_incomplete_market_snapshot_is_rejected(invalid_odds: str) -> None:
    payload = deepcopy(_fixture("sporttery_fixed_bonus.json"))
    snapshot = payload["value"]["oddsHistory"]["ttgList"][0]
    if invalid_odds == "missing":
        snapshot.pop("s0")
    else:
        snapshot["s0"] = invalid_odds

    record = parse_fixed_bonus(payload)

    assert "total_goals" not in {item.market_type for item in record.snapshots}
    assert record.rejected_snapshots == 1


def test_invalid_match_identity_rejects_the_whole_payload() -> None:
    payload = _fixture("sporttery_match_page.json")
    payload["value"]["matchResult"][0]["matchId"] = 0

    with pytest.raises(SportteryParseError, match="invalid_match_id"):
        parse_match_page(payload)


def test_same_team_match_is_skipped_without_losing_the_rest_of_the_page() -> None:
    """官方偶发的主客队相同记录不可训练，但不应阻断同页正常比赛。"""
    payload = _fixture("sporttery_match_page.json")
    invalid = payload["value"]["matchResult"][0]
    invalid["awayTeamId"] = invalid["homeTeamId"]
    invalid["awayTeam"] = invalid["homeTeam"]

    parsed = parse_match_page(payload)

    assert [match.match_id for match in parsed.matches] == [62374]
    assert parsed.rejected_matches == 1


def test_refunded_invalid_match_keeps_identity_without_training_label() -> None:
    """旧数据中的“无效场次”应保留审计身份，但不能伪造比分和赛果。"""
    payload = _fixture("sporttery_match_page.json")
    match = payload["value"]["matchResult"][0]
    match.update({
        "sectionsNo1": "",
        "sectionsNo999": "无效场次",
        "winFlag": "",
        "poolStatus": "Refund",
    })

    parsed = parse_match_page(payload).matches[0]

    assert (parsed.home_score, parsed.away_score, parsed.result) == (None, None, None)
    assert parsed.pool_status == "Refund"


def test_legacy_unmapped_league_id_zero_is_preserved() -> None:
    """旧接口以 leagueId=0 表示未映射联赛，不能因此丢弃有效比赛和奖金。"""
    page_payload = _fixture("sporttery_match_page.json")
    page_payload["value"]["matchResult"][0]["leagueId"] = 0
    bonus_payload = _fixture("sporttery_fixed_bonus.json")
    bonus_payload["value"]["oddsHistory"]["leagueId"] = 0

    match = parse_match_page(page_payload).matches[0]
    bonus = parse_fixed_bonus(bonus_payload)

    assert match.league_id == 0
    assert bonus.league_id == 0


@pytest.mark.parametrize("marker", ["无效场次", "取消"])
def test_official_invalid_result_markers_do_not_create_labels(marker: str) -> None:
    """官方无效或取消标记没有数值比分，必须排除训练标签但保留记录。"""
    payload = _fixture("sporttery_match_page.json")
    match = payload["value"]["matchResult"][0]
    match.update({
        "sectionsNo1": "",
        "sectionsNo999": marker,
        "winFlag": "",
        # 2015 旧记录偶发遗漏 Refund 状态，结果标记本身仍然明确表示无有效赛果。
        "poolStatus": "",
    })

    parsed = parse_match_page(payload).matches[0]

    assert (parsed.home_score, parsed.away_score, parsed.result) == (None, None, None)


def test_refunded_match_ignores_negative_half_time_sentinel() -> None:
    """退款场次会用 -1:-1 表示无半场比分，该哨兵值不能阻断整页导入。"""
    payload = _fixture("sporttery_match_page.json")
    match = payload["value"]["matchResult"][0]
    match.update({
        "sectionsNo1": "-1:-1",
        "sectionsNo999": "无效场次",
        "winFlag": "",
        "poolStatus": "Refund",
    })

    parsed = parse_match_page(payload).matches[0]

    assert (parsed.half_time_home_score, parsed.half_time_away_score) == (None, None)
    assert (parsed.home_score, parsed.away_score, parsed.result) == (None, None, None)
