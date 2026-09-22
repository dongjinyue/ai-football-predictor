"""原始响应与检查点存储测试。"""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

import pytest

from app.sporttery.models import HttpPayload
from app.sporttery.storage import (
    CheckpointStore,
    CollectionCheckpoint,
    PreviewDatasetCheckpoint,
    RawResponseStore,
    StorageError,
    get_preview_checkpoint,
)


def _payload() -> HttpPayload:
    return HttpPayload(
        data={"success": True, "errorCode": "0", "value": {"pages": 1}},
        status_code=200,
        fetched_at=datetime(2015, 1, 3, 1, 2, 3, tzinfo=timezone.utc),
        request_url="https://example.test/list?pageNo=1",
    )


def test_raw_store_writes_canonical_payload_and_reuses_valid_cache(tmp_path) -> None:
    store = RawResponseStore(tmp_path)

    first = store.write("match_lists", 2015, "2015-01-01_2015-01-03/page-1", _payload())
    second = store.write("match_lists", 2015, "2015-01-01_2015-01-03/page-1", _payload())

    assert first.path == tmp_path / "match_lists" / "2015" / "2015-01-01_2015-01-03" / "page-1.json"
    stored = json.loads(first.path.read_text(encoding="utf-8"))
    canonical = json.dumps(_payload().data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    assert stored["sha256"] == sha256(canonical).hexdigest() == first.sha256
    assert stored["request_url"] == _payload().request_url
    assert stored["data"] == _payload().data
    assert first.from_cache is False
    assert second.from_cache is True
    assert list(tmp_path.rglob("*.part")) == []


def test_raw_store_rejects_corrupt_existing_file_without_overwriting(tmp_path) -> None:
    path = tmp_path / "fixed_bonus" / "2015" / "62373.json"
    path.parent.mkdir(parents=True)
    path.write_text('{"sha256":"wrong","data":{}}', encoding="utf-8")

    with pytest.raises(StorageError, match="raw_checksum_mismatch"):
        RawResponseStore(tmp_path).write("fixed_bonus", 2015, "62373", _payload())

    assert "wrong" in path.read_text(encoding="utf-8")


def test_raw_store_rejects_path_traversal(tmp_path) -> None:
    with pytest.raises(StorageError, match="invalid_storage_key"):
        RawResponseStore(tmp_path).write("fixed_bonus", 2015, "../secret", _payload())


def test_checkpoint_round_trip_is_atomic_and_sorted(tmp_path) -> None:
    store = CheckpointStore(tmp_path)
    checkpoint = CollectionCheckpoint(
        year=2015,
        completed_pages=("b", "a"),
        match_ids=(62374, 62373),
        completed_bonus_ids=(62373,),
        failed_bonus_ids=(),
        stopped_reason=None,
    )

    store.save(checkpoint)
    loaded = store.load(2015)

    assert loaded.completed_pages == ("a", "b")
    assert loaded.match_ids == (62373, 62374)
    assert loaded.completed_bonus_ids == (62373,)
    assert list(tmp_path.rglob("*.part")) == []


def test_atomic_write_retries_a_transient_windows_replace_denial(
    tmp_path, monkeypatch
) -> None:
    """索引器短暂占用目标文件时应重试，不能让全年任务退出。"""
    original_replace = Path.replace
    attempts = 0

    def flaky_replace(path: Path, target: Path):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise PermissionError("temporarily locked")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", flaky_replace)

    CheckpointStore(tmp_path).save(CollectionCheckpoint(year=2015))

    assert attempts == 2
    assert CheckpointStore(tmp_path).load(2015).year == 2015
    assert list(tmp_path.rglob("*.part")) == []


def test_atomic_write_survives_a_longer_windows_lock(tmp_path, monkeypatch) -> None:
    """Windows 扫描器占用数秒时，检查点写入也应继续重试而非丢失任务。"""
    original_replace = Path.replace
    attempts = 0

    def flaky_replace(path: Path, target: Path):
        nonlocal attempts
        attempts += 1
        if attempts <= 5:
            raise PermissionError("temporarily locked")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", flaky_replace)
    monkeypatch.setattr("app.sporttery.storage.time.sleep", lambda _: None)

    CheckpointStore(tmp_path).save(CollectionCheckpoint(year=2015))

    assert attempts == 6


def test_checkpoint_corruption_is_not_silently_reset(tmp_path) -> None:
    path = tmp_path / "checkpoints" / "2015.json"
    path.parent.mkdir(parents=True)
    path.write_text("not-json", encoding="utf-8")

    with pytest.raises(StorageError, match="invalid_checkpoint"):
        CheckpointStore(tmp_path).load(2015)


def test_preview_checkpoint_round_trip_sorts_ids_and_datasets(tmp_path) -> None:
    store = CheckpointStore(tmp_path)
    checkpoint = CollectionCheckpoint(
        year=2015,
        preview_datasets=(PreviewDatasetCheckpoint(
            dataset="match_feature",
            completed_ids=(2041615, 62373, 62373),
            empty_ids=(62374,),
            failed_ids=(62375,),
        ),),
    )

    store.save(checkpoint)
    loaded = store.load(2015)

    state = get_preview_checkpoint(loaded, "match_feature")
    assert state.completed_ids == (62373, 2041615)
    assert state.empty_ids == (62374,)
    assert state.failed_ids == (62375,)


def test_old_checkpoint_without_preview_data_loads_as_empty(tmp_path) -> None:
    path = tmp_path / "checkpoints" / "2015.json"
    path.parent.mkdir(parents=True)
    path.write_text('{"year":2015,"completed_bonus_ids":[62373]}', encoding="utf-8")

    loaded = CheckpointStore(tmp_path).load(2015)

    assert loaded.completed_bonus_ids == (62373,)
    assert loaded.preview_datasets == ()


def test_preview_checkpoint_rejects_unknown_dataset_and_overlapping_states(tmp_path) -> None:
    store = CheckpointStore(tmp_path)

    with pytest.raises(StorageError, match="invalid_preview_checkpoint"):
        store.save(CollectionCheckpoint(
            year=2015,
            preview_datasets=(PreviewDatasetCheckpoint(
                dataset="unknown",
                completed_ids=(62373,),
            ),),
        ))

    with pytest.raises(StorageError, match="invalid_preview_checkpoint"):
        store.save(CollectionCheckpoint(
            year=2015,
            preview_datasets=(PreviewDatasetCheckpoint(
                dataset="match_feature",
                completed_ids=(62373,),
                failed_ids=(62373,),
            ),),
        ))
