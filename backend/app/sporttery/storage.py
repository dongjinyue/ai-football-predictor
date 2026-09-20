"""中国竞彩原始响应与断点检查点的本地持久化。"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.sporttery.models import HttpPayload


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
class CollectionCheckpoint:
    """一年采集任务可恢复的最小状态。"""

    year: int
    completed_pages: tuple[str, ...] = ()
    match_ids: tuple[int, ...] = ()
    completed_bonus_ids: tuple[int, ...] = ()
    failed_bonus_ids: tuple[int, ...] = ()
    stopped_reason: str | None = None


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
        return self._load(path, from_cache=False)

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
            return _normalized_checkpoint(
                CollectionCheckpoint(
                    year=year,
                    completed_pages=tuple(str(item) for item in data.get("completed_pages", ())),
                    match_ids=tuple(int(item) for item in data.get("match_ids", ())),
                    completed_bonus_ids=tuple(int(item) for item in data.get("completed_bonus_ids", ())),
                    failed_bonus_ids=tuple(int(item) for item in data.get("failed_bonus_ids", ())),
                    stopped_reason=data.get("stopped_reason"),
                )
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise StorageError("invalid_checkpoint") from error

    def save(self, checkpoint: CollectionCheckpoint) -> None:
        normalized = _normalized_checkpoint(checkpoint)
        path = self.root / "checkpoints" / f"{normalized.year}.json"
        document = asdict(normalized)
        _atomic_json_write(path, document)


def _normalized_checkpoint(checkpoint: CollectionCheckpoint) -> CollectionCheckpoint:
    return CollectionCheckpoint(
        year=checkpoint.year,
        completed_pages=tuple(sorted(set(checkpoint.completed_pages))),
        match_ids=tuple(sorted(set(checkpoint.match_ids))),
        completed_bonus_ids=tuple(sorted(set(checkpoint.completed_bonus_ids))),
        failed_bonus_ids=tuple(sorted(set(checkpoint.failed_bonus_ids))),
        stopped_reason=checkpoint.stopped_reason,
    )


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
        for attempt in range(5):
            try:
                part.replace(path)
                break
            except PermissionError:
                # Windows 索引器或杀毒软件可能短暂占用目标文件，退避后重试原子替换。
                if attempt == 4:
                    raise
                time.sleep(0.05 * (2**attempt))
    finally:
        if part.exists():
            part.unlink()
