"""中国竞彩原始响应与断点检查点的本地持久化。"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, replace
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.sporttery.models import HttpPayload
from app.sporttery.preview import is_preview_dataset


class StorageError(RuntimeError):
    """原始证据或检查点不可信时使用的稳定错误。"""


@dataclass(frozen=True)
class StoredResponse:
    """已经校验并持久化的来源响应。"""

    path: Path
    sha256: str
    fetched_at: datetime
    request_url: str
    status_code: int
    data: dict[str, Any]
    from_cache: bool


@dataclass(frozen=True)
class PreviewDatasetCheckpoint:
    """一个前瞻数据集在年度采集任务中的独立状态。"""

    dataset: str
    completed_ids: tuple[int, ...] = ()
    empty_ids: tuple[int, ...] = ()
    failed_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class CollectionCheckpoint:
    """一年采集任务可恢复的最小状态。"""

    year: int
    completed_pages: tuple[str, ...] = ()
    match_ids: tuple[int, ...] = ()
    completed_bonus_ids: tuple[int, ...] = ()
    failed_bonus_ids: tuple[int, ...] = ()
    stopped_reason: str | None = None
    preview_datasets: tuple[PreviewDatasetCheckpoint, ...] = ()


class RawResponseStore:
    """按稳定路径保存不可变原始 JSON，并在复用前验证校验值。"""

    def __init__(self, root: Path) -> None:
        self.root = root

    def write(
        self,
        kind: str,
        year: int,
        key: str,
        payload: HttpPayload,
    ) -> StoredResponse:
        path = self._path(kind, year, key)
        if path.exists():
            return self._load(path, from_cache=True)

        digest = _data_digest(payload.data)
        document = {
            "schema_version": 1,
            "request_url": payload.request_url,
            "status_code": payload.status_code,
            "fetched_at": payload.fetched_at.isoformat(),
            "sha256": digest,
            "data": payload.data,
        }
        _atomic_json_write(path, document)
        # 写入内容和摘要刚刚由当前进程生成，无需立即重新读盘并计算第二遍摘要。
        return StoredResponse(
            path=path,
            sha256=digest,
            fetched_at=payload.fetched_at,
            request_url=payload.request_url,
            status_code=payload.status_code,
            data=payload.data,
            from_cache=False,
        )

    def load(self, kind: str, year: int, key: str) -> StoredResponse | None:
        path = self._path(kind, year, key)
        return self._load(path, from_cache=True) if path.exists() else None

    def _path(self, kind: str, year: int, key: str) -> Path:
        if not kind or Path(kind).name != kind or year < 2000 or year > 2100:
            raise StorageError("invalid_storage_key")
        relative = Path(key)
        if relative.is_absolute() or not key or any(part in {"", ".", ".."} for part in relative.parts):
            raise StorageError("invalid_storage_key")
        path = self.root / kind / str(year) / relative
        if path.suffix != ".json":
            path = path.with_suffix(".json")
        try:
            path.resolve().relative_to(self.root.resolve())
        except ValueError as error:
            raise StorageError("invalid_storage_key") from error
        return path

    @staticmethod
    def _load(path: Path, *, from_cache: bool) -> StoredResponse:
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
            data = document["data"]
            digest = document["sha256"]
            if not isinstance(data, dict) or digest != _data_digest(data):
                raise StorageError("raw_checksum_mismatch")
            fetched_at = datetime.fromisoformat(document["fetched_at"])
            if fetched_at.tzinfo is None:
                raise ValueError("naive fetched_at")
            return StoredResponse(
                path=path,
                sha256=digest,
                fetched_at=fetched_at,
                request_url=str(document["request_url"]),
                status_code=int(document["status_code"]),
                data=data,
                from_cache=from_cache,
            )
        except StorageError:
            raise
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise StorageError("invalid_raw_response") from error


class CheckpointStore:
    """使用原子替换保存任务进度，避免进程终止留下半个文件。"""

    def __init__(self, root: Path) -> None:
        self.root = root

    def load(self, year: int) -> CollectionCheckpoint:
        path = self.root / "checkpoints" / f"{year}.json"
        if not path.exists():
            return CollectionCheckpoint(year=year)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if int(data["year"]) != year:
                raise ValueError("year mismatch")
            raw_previews = data.get("preview_datasets", {})
            if raw_previews is None:
                raw_previews = {}
            if not isinstance(raw_previews, dict):
                raise ValueError("preview_datasets must be an object")
            preview_datasets = tuple(
                PreviewDatasetCheckpoint(
                    dataset=str(dataset),
                    completed_ids=tuple(int(item) for item in state.get("completed_ids", ())),
                    empty_ids=tuple(int(item) for item in state.get("empty_ids", ())),
                    failed_ids=tuple(int(item) for item in state.get("failed_ids", ())),
                )
                for dataset, state in raw_previews.items()
                if isinstance(state, dict)
            )
            if len(preview_datasets) != len(raw_previews):
                raise ValueError("invalid preview dataset state")
            return _normalized_checkpoint(
                CollectionCheckpoint(
                    year=year,
                    completed_pages=tuple(str(item) for item in data.get("completed_pages", ())),
                    match_ids=tuple(int(item) for item in data.get("match_ids", ())),
                    completed_bonus_ids=tuple(int(item) for item in data.get("completed_bonus_ids", ())),
                    failed_bonus_ids=tuple(int(item) for item in data.get("failed_bonus_ids", ())),
                    stopped_reason=data.get("stopped_reason"),
                    preview_datasets=preview_datasets,
                )
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise StorageError("invalid_checkpoint") from error

    def save(self, checkpoint: CollectionCheckpoint) -> None:
        normalized = _normalized_checkpoint(checkpoint)
        path = self.root / "checkpoints" / f"{normalized.year}.json"
        document = {
            "year": normalized.year,
            "completed_pages": list(normalized.completed_pages),
            "match_ids": list(normalized.match_ids),
            "completed_bonus_ids": list(normalized.completed_bonus_ids),
            "failed_bonus_ids": list(normalized.failed_bonus_ids),
            "stopped_reason": normalized.stopped_reason,
            "preview_datasets": {
                state.dataset: {
                    "completed_ids": list(state.completed_ids),
                    "empty_ids": list(state.empty_ids),
                    "failed_ids": list(state.failed_ids),
                }
                for state in normalized.preview_datasets
            },
        }
        _atomic_json_write(path, document)


def _normalized_checkpoint(checkpoint: CollectionCheckpoint) -> CollectionCheckpoint:
    preview_states = tuple(
        _normalized_preview_checkpoint(state)
        for state in sorted(checkpoint.preview_datasets, key=lambda item: item.dataset)
    )
    if len({state.dataset for state in preview_states}) != len(preview_states):
        raise StorageError("invalid_preview_checkpoint")
    return CollectionCheckpoint(
        year=checkpoint.year,
        completed_pages=tuple(sorted(set(checkpoint.completed_pages))),
        match_ids=tuple(sorted(set(checkpoint.match_ids))),
        completed_bonus_ids=tuple(sorted(set(checkpoint.completed_bonus_ids))),
        failed_bonus_ids=tuple(sorted(set(checkpoint.failed_bonus_ids))),
        stopped_reason=checkpoint.stopped_reason,
        preview_datasets=preview_states,
    )


def _normalized_preview_checkpoint(
    state: PreviewDatasetCheckpoint,
) -> PreviewDatasetCheckpoint:
    if not is_preview_dataset(state.dataset):
        raise StorageError("invalid_preview_checkpoint")
    completed = set(state.completed_ids)
    empty = set(state.empty_ids)
    failed = set(state.failed_ids)
    if not all(isinstance(item, int) and item > 0 for item in completed | empty | failed):
        raise StorageError("invalid_preview_checkpoint")
    if completed & empty or completed & failed or empty & failed:
        raise StorageError("invalid_preview_checkpoint")
    return PreviewDatasetCheckpoint(
        dataset=state.dataset,
        completed_ids=tuple(sorted(completed)),
        empty_ids=tuple(sorted(empty)),
        failed_ids=tuple(sorted(failed)),
    )


def get_preview_checkpoint(
    checkpoint: CollectionCheckpoint,
    dataset: str,
) -> PreviewDatasetCheckpoint:
    """读取一个数据集的状态；旧检查点没有它时返回空状态。"""
    if not is_preview_dataset(dataset):
        raise StorageError("invalid_preview_checkpoint")
    for state in checkpoint.preview_datasets:
        if state.dataset == dataset:
            return state
    return PreviewDatasetCheckpoint(dataset=dataset)


def replace_preview_checkpoint(
    checkpoint: CollectionCheckpoint,
    state: PreviewDatasetCheckpoint,
) -> CollectionCheckpoint:
    """只替换一个前瞻数据集状态，保留同年度其他进度。"""
    normalized = _normalized_preview_checkpoint(state)
    states = [item for item in checkpoint.preview_datasets if item.dataset != state.dataset]
    states.append(normalized)
    return _normalized_checkpoint(replace(checkpoint, preview_datasets=tuple(states)))


def _data_digest(data: dict[str, Any]) -> str:
    canonical = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(canonical).hexdigest()


def _atomic_json_write(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(f"{path.name}.{uuid4().hex}.part")
    try:
        part.write_text(
            json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        # Windows 扫描器、索引器或编辑器可能短暂持有目标文件；延长重试窗口，
        # 同时限制单次等待，避免真正异常时长时间假死。
        retries = 8
        for attempt in range(retries):
            try:
                part.replace(path)
                break
            except PermissionError:
                # Windows 索引器或杀毒软件可能短暂占用目标文件，退避后重试原子替换。
                if attempt == retries - 1:
                    raise
                time.sleep(min(0.1 * (2**attempt), 1.0))
    finally:
        if part.exists():
            part.unlink()
