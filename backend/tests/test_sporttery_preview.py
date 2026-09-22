from __future__ import annotations

import pytest

from app.sporttery.preview import PREVIEW_DATASETS, classify_preview_payload


def test_preview_catalog_contains_all_official_datasets() -> None:
    assert [item.code for item in PREVIEW_DATASETS] == [
        "match_feature",
        "result_history",
        "match_tables",
        "match_result",
        "future_matches",
        "match_player",
        "injury_suspension",
    ]
    tables = next(item for item in PREVIEW_DATASETS if item.code == "match_tables")
    assert tables.parameters(2041615) == {"gmMatchId": 2041615}


def test_preview_payload_classifies_source_empty_response() -> None:
    assert classify_preview_payload(
        {"success": True, "errorCode": "0", "emptyFlag": True, "value": None}
    ) == "empty"
    assert classify_preview_payload(
        {"success": True, "errorCode": "0", "emptyFlag": False, "value": {"home": {}}}
    ) == "completed"


def test_preview_payload_rejects_unknown_value_shape() -> None:
    with pytest.raises(Exception, match="invalid_preview_value_shape"):
        classify_preview_payload(
            {"success": True, "errorCode": "0", "emptyFlag": False, "value": "unexpected"}
        )
