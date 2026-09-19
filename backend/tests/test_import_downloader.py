"""Football-Data 原始文件下载与缓存的离线测试。"""

from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import httpx
import pytest

from app.imports.downloader import (
    DownloadError,
    DownloadValidationError,
    FootballDataDownloader,
)
from app.imports.models import SourceFile


CSV_BYTES = (
    b"Date,HomeTeam,AwayTeam,FTHG,FTAG,AvgH,AvgD,AvgA\n"
    b"10/08/2024,Alpha FC,Beta FC,1,0,2.1,3.2,4.0\n"
)


def test_concurrent_downloads_use_independent_temporary_files(tmp_path, source_file, monkeypatch):
    """两个下载同时完成校验时，不能竞争同一个 .part 文件。"""
    downloader = FootballDataDownloader(_client(httpx.MockTransport(
        lambda request: httpx.Response(200, headers={"content-type": "text/csv"}, content=CSV_BYTES)
    )), tmp_path)
    staged_files = []
    barrier = Barrier(2, action=lambda: staged_files.extend(tmp_path.rglob("*.part")))
    validate = downloader._validate_content

    def synchronized_validate(content, content_type):
        validate(content, content_type)
        barrier.wait(timeout=10)

    monkeypatch.setattr(downloader, "_validate_content", synchronized_validate)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(downloader.download, source_file) for _ in range(2)]
        results = [future.result(timeout=15) for future in futures]
    assert all(item.content == CSV_BYTES for item in results)
    assert len(staged_files) == 2
    assert results[0].path.read_bytes() == CSV_BYTES
    assert list(tmp_path.rglob("*.part")) == []


@pytest.fixture
def source_file() -> SourceFile:
    return SourceFile(
        source="football_data",
        competition_code="E0",
        competition_name="Premier League",
        country_code="ENG",
        season="2425",
        url="https://example.test/mmz4281/2425/E0.csv",
    )


def _client(handler: httpx.MockTransport) -> httpx.Client:
    return httpx.Client(transport=handler)


def test_download_writes_deterministic_cache_and_returns_byte_hash(
    tmp_path: Path, source_file: SourceFile
) -> None:
    """若改变保存路径或哈希对象，此测试应失败。"""
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, headers={"content-type": "text/csv"}, content=CSV_BYTES
        )
    )

    downloaded = FootballDataDownloader(_client(transport), tmp_path).download(source_file)

    assert downloaded.path == tmp_path / "E0" / "2425" / "matches.csv"
    assert downloaded.path.read_bytes() == CSV_BYTES
    assert downloaded.content == CSV_BYTES
    assert downloaded.sha256 == sha256(CSV_BYTES).hexdigest()
    assert downloaded.downloaded_at.tzinfo is not None
    assert downloaded.from_cache is False


def test_second_download_uses_validated_cache_without_http_request(
    tmp_path: Path, source_file: SourceFile
) -> None:
    """若移除缓存短路分支或跳过缓存校验，此测试应失败。"""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, headers={"content-type": "text/csv"}, content=CSV_BYTES)

    downloader = FootballDataDownloader(_client(httpx.MockTransport(handler)), tmp_path)
    downloader.download(source_file)
    cached = downloader.download(source_file)

    assert len(requests) == 1
    assert cached.content == CSV_BYTES
    assert cached.from_cache is True


def test_retries_retryable_server_response_up_to_configured_boundary(
    tmp_path: Path, source_file: SourceFile
) -> None:
    """若少重试一次、对 503 不重试或超过边界仍请求，此测试应失败。"""
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            return httpx.Response(503, content=b"temporarily unavailable")
        return httpx.Response(200, headers={"content-type": "text/csv"}, content=CSV_BYTES)

    downloaded = FootballDataDownloader(
        _client(httpx.MockTransport(handler)), tmp_path, max_attempts=3
    ).download(source_file)

    assert attempts == 3
    assert downloaded.content == CSV_BYTES


def test_raises_stable_error_after_last_retryable_response(
    tmp_path: Path, source_file: SourceFile
) -> None:
    """若重试次数超过 max_attempts 或最终错误代码不稳定，此测试应失败。"""
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(429, content=b"slow down")

    with pytest.raises(DownloadError, match="http_429") as error:
        FootballDataDownloader(
            _client(httpx.MockTransport(handler)), tmp_path, max_attempts=2
        ).download(source_file)

    assert attempts == 2
    assert error.value.code == "http_429"


@pytest.mark.parametrize("error", [httpx.ReadTimeout("read timeout"), httpx.ConnectError("offline")])
def test_retries_transient_transport_errors(
    tmp_path: Path, source_file: SourceFile, error: httpx.HTTPError
) -> None:
    """若超时或连接错误不重试至边界，此测试应失败。"""
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise error
        return httpx.Response(200, headers={"content-type": "text/csv"}, content=CSV_BYTES)

    client = _client(httpx.MockTransport(handler))
    downloaded = FootballDataDownloader(client, tmp_path, max_attempts=2).download(source_file)

    assert attempts == 2
    assert downloaded.content == CSV_BYTES
    assert client.timeout.connect == 10.0
    assert client.timeout.read == 30.0


def test_does_not_retry_non_retryable_client_response(
    tmp_path: Path, source_file: SourceFile
) -> None:
    """若将普通 4xx 误判为暂时性错误，此测试应失败。"""
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(404, content=b"not found")

    with pytest.raises(DownloadError, match="http_404"):
        FootballDataDownloader(_client(httpx.MockTransport(handler)), tmp_path).download(
            source_file
        )

    assert attempts == 1


@pytest.mark.parametrize(
    ("content", "headers", "code"),
    [
        (b"<html><body>blocked</body></html>", {"content-type": "text/html"}, "html_content"),
        (b"", {"content-type": "text/csv"}, "empty_content"),
        (b"Date,HomeTeam,AwayTeam\n", {"content-type": "text/csv"}, "missing_required_headers"),
    ],
)
def test_rejects_invalid_download_content_and_cleans_temporary_file(
    tmp_path: Path,
    source_file: SourceFile,
    content: bytes,
    headers: dict[str, str],
    code: str,
) -> None:
    """若接受错误页、空文件或不完整 CSV，或遗留 .part 文件，此测试应失败。"""
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, headers=headers, content=content)
    )
    final_path = tmp_path / "E0" / "2425" / "matches.csv"

    with pytest.raises(DownloadValidationError, match=code):
        FootballDataDownloader(_client(transport), tmp_path).download(source_file)

    assert not final_path.exists()
    assert not final_path.with_name("matches.csv.part").exists()


def test_rejects_invalid_cached_content_without_requesting_network(
    tmp_path: Path, source_file: SourceFile
) -> None:
    """若缓存文件未校验便返回，此测试应失败。"""
    cached_path = tmp_path / "E0" / "2425" / "matches.csv"
    cached_path.parent.mkdir(parents=True)
    cached_path.write_bytes(b"<html>stale error page</html>")
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(200, headers={"content-type": "text/csv"}, content=CSV_BYTES)

    with pytest.raises(DownloadValidationError, match="html_content"):
        FootballDataDownloader(_client(httpx.MockTransport(handler)), tmp_path).download(
            source_file
        )

    assert requests == 0


def test_accepts_combined_source_headers(tmp_path: Path, source_file: SourceFile) -> None:
    """new/联赛.csv 的合并格式也必须通过下载阶段的表头校验。"""
    content = (
        b"\xef\xbb\xbfCountry,League,Season,Date,Time,Home,Away,HG,AG,Res,AvgCH,AvgCD,AvgCA\n"
        b"Argentina,Liga,2012,01/05/12,15:00,Home,Away,1,0,H,2,3,4\n"
    )
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, headers={"content-type": "text/csv"}, content=content)
    )

    downloaded = FootballDataDownloader(_client(transport), tmp_path).download(source_file)

    assert downloaded.content == content


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("competition_code", ".."),
        ("competition_code", "../escaped"),
        ("competition_code", "/absolute"),
        ("competition_code", "nested/path"),
        ("competition_code", r"nested\path"),
        ("season", ".."),
        ("season", r"C:\escaped"),
    ],
)
def test_rejects_unsafe_cache_path_identifier_before_network_or_write(
    tmp_path: Path, source_file: SourceFile, field: str, value: str
) -> None:
    """若允许路径分隔符、父目录或绝对标识符逃逸 raw_root，此测试应失败。"""
    request = replace(source_file, **{field: value})
    raw_root = tmp_path / "raw"
    requests = 0

    def handler(http_request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        raise AssertionError("unsafe identifier must be rejected before HTTP")

    with pytest.raises(DownloadValidationError, match="invalid_cache_path"):
        FootballDataDownloader(_client(httpx.MockTransport(handler)), raw_root).download(
            request
        )

    assert requests == 0
    assert not list(tmp_path.rglob("matches.csv"))
