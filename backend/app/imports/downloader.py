"""Football-Data 原始 CSV 下载、校验与本地缓存。"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import httpx

from app.imports.models import SourceFile
from app.imports.parser import REQUIRED_HEADERS


class DownloadError(RuntimeError):
    """下载失败时向协调器提供的安全、稳定错误代码。"""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class DownloadValidationError(DownloadError):
    """响应或缓存不符合 Football-Data CSV 基本契约。"""


@dataclass(frozen=True)
class DownloadedFile:
    """下载完成的原始文件及其审计元数据。"""

    path: Path
    content: bytes
    sha256: str
    downloaded_at: datetime
    from_cache: bool


class FootballDataDownloader:
    """下载 Football-Data 文件，并复用已校验的本地原始缓存。"""

    def __init__(
        self,
        client: httpx.Client,
        raw_root: Path,
        max_attempts: int = 3,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts_must_be_positive")

        self.client = client
        self.raw_root = raw_root
        self.max_attempts = max_attempts
        # 下载器统一设置网络边界，避免某个调用方遗漏连接或读取超时。
        self.client.timeout = httpx.Timeout(30.0, connect=10.0, read=30.0)

    def download(self, request: SourceFile) -> DownloadedFile:
        """取得一个已校验文件；不会让下载时间影响历史赔率的时间语义。"""
        path = self._cache_path(request)
        if path.exists():
            content = path.read_bytes()
            self._validate_content(content, content_type=None)
            return DownloadedFile(
                path=path,
                content=content,
                sha256=sha256(content).hexdigest(),
                downloaded_at=datetime.fromtimestamp(path.stat().st_mtime, timezone.utc),
                from_cache=True,
            )

        content, content_type = self._request_content(request)
        return self._write_validated_cache(path, content, content_type)

    def _cache_path(self, request: SourceFile) -> Path:
        competition_code = self._safe_path_identifier(request.competition_code)
        season = self._safe_path_identifier(request.season)
        raw_root = self.raw_root.resolve()
        path = raw_root / competition_code / season / "matches.csv"
        try:
            # resolve 会展开已存在的符号链接；relative_to 确认最终路径没有逃出缓存根目录。
            path.resolve().relative_to(raw_root)
        except ValueError as error:
            raise DownloadValidationError("invalid_cache_path") from error
        return path

    @staticmethod
    def _safe_path_identifier(value: str) -> str:
        """仅接受一个不含路径语义的来源标识符，不能通过清洗改变其含义。"""
        if (
            not value
            or value in {".", ".."}
            or value != value.strip()
            or "/" in value
            or "\\" in value
            or ":" in value
            or "\x00" in value
            or Path(value).is_absolute()
        ):
            raise DownloadValidationError("invalid_cache_path")
        return value

    def _request_content(self, request: SourceFile) -> tuple[bytes, str | None]:
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = self.client.get(request.url)
            except httpx.TimeoutException as error:
                if attempt == self.max_attempts:
                    raise DownloadError("timeout") from error
                continue
            except httpx.ConnectError as error:
                if attempt == self.max_attempts:
                    raise DownloadError("connection_error") from error
                continue

            if response.status_code == 200:
                return response.content, response.headers.get("content-type")

            code = f"http_{response.status_code}"
            if response.status_code == 429 or response.status_code >= 500:
                if attempt == self.max_attempts:
                    raise DownloadError(code)
                continue
            raise DownloadError(code)

        # 循环内每种失败都会 return 或 raise；保留此处以保证类型检查完整。
        raise DownloadError("request_failed")

    def _write_validated_cache(
        self, path: Path, content: bytes, content_type: str | None
    ) -> DownloadedFile:
        path.parent.mkdir(parents=True, exist_ok=True)
        part_path = path.with_name(f"{path.name}.{uuid4().hex}.part")
        try:
            # 先写临时文件并从临时文件读回校验，校验通过前绝不替换正式缓存。
            part_path.write_bytes(content)
            stored_content = part_path.read_bytes()
            self._validate_content(stored_content, content_type=content_type)
            part_path.replace(path)
        except Exception:
            # 失败清理临时文件，避免下次运行误把不完整文件作为可用缓存。
            if part_path.exists():
                part_path.unlink()
            raise

        return DownloadedFile(
            path=path,
            content=stored_content,
            sha256=sha256(stored_content).hexdigest(),
            downloaded_at=datetime.now(timezone.utc),
            from_cache=False,
        )

    def _validate_content(self, content: bytes, content_type: str | None) -> None:
        if not content:
            raise DownloadValidationError("empty_content")

        normalized_type = (content_type or "").lower()
        if "html" in normalized_type or self._looks_like_html(content):
            raise DownloadValidationError("html_content")
        if normalized_type and not any(
            accepted in normalized_type
            for accepted in ("text/csv", "application/csv", "text/plain", "vnd.ms-excel")
        ):
            raise DownloadValidationError("invalid_content_type")

        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise DownloadValidationError("invalid_encoding") from error
        headers = set(csv.DictReader(io.StringIO(text)).fieldnames or ())
        if not REQUIRED_HEADERS <= headers:
            raise DownloadValidationError("missing_required_headers")

    @staticmethod
    def _looks_like_html(content: bytes) -> bool:
        prefix = content.lstrip()[:64].lower()
        return prefix.startswith(b"<html") or prefix.startswith(b"<!doctype html")
