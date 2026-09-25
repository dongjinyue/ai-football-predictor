"""中国竞彩网历史比赛与固定奖金采集命令行入口。"""

from __future__ import annotations

import argparse
import json
import threading
import time
from dataclasses import asdict
from datetime import date
from typing import Sequence

from app.config import PROJECT_ROOT, load_settings
from app.sporttery.client import SportteryClient
from app.sporttery.preview import PREVIEW_DATASETS
from app.sporttery.repository import (
    CoverageReport,
    SportteryRepository,
    SynchronizedSportteryRepository,
)
from app.sporttery.service import (
    CollectionReport,
    RequestStartPacer,
    SportteryCollectionService,
    _date_windows,
    collect_with_blocked_retries,
    collect_years,
)
from app.sporttery.storage import CheckpointStore, CollectionCheckpoint, RawResponseStore


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="采集和审计中国竞彩网历史数据")
    subparsers = parser.add_subparsers(dest="command", required=True)

    collect = subparsers.add_parser("collect", help="采集一个自然年内的比赛与固定奖金")
    collect.add_argument("--start", required=True, type=_date_argument)
    collect.add_argument("--end", required=True, type=_date_argument)
    _add_collection_controls(collect)

    multiple = subparsers.add_parser(
        "collect-years", help="在一个进程内并行采集多个自然年"
    )
    multiple.add_argument("--start-year", required=True, type=int)
    multiple.add_argument("--end-year", required=True, type=int)
    multiple.add_argument("--workers", type=int, default=3)
    multiple.add_argument("--blocked-retries", type=int, default=5)
    multiple.add_argument("--blocked-wait", type=float, default=60.0)
    _add_collection_controls(multiple)

    report = subparsers.add_parser("report", help="输出指定年份的数据库覆盖率")
    report.add_argument("--year", required=True, type=int)

    args = parser.parse_args(argv)
    if args.command == "collect":
        if args.end < args.start or args.start.year != args.end.year:
            parser.error("开始和结束日期必须位于同一自然年，且结束日期不能早于开始日期")
        _validate_collection_controls(parser, args)
    elif args.command == "collect-years":
        current_year = date.today().year
        if not 2000 <= args.start_year <= args.end_year <= current_year:
            parser.error("年份范围必须位于 2000 到当前年份之间")
        if args.workers < 1:
            parser.error("workers 必须大于 0")
        if args.blocked_retries < 0 or args.blocked_wait < 0:
            parser.error("blocked-retries 和 blocked-wait 不能为负数")
        _validate_collection_controls(parser, args)
    elif not 2000 <= args.year <= 2100:
        parser.error("year 必须在 2000 到 2100 之间")
    return args


def _add_collection_controls(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--delay-min", type=float, default=3.0,
        help="相邻网络请求开始时间的最短间隔（秒）",
    )
    parser.add_argument(
        "--delay-max", type=float, default=5.0,
        help="相邻网络请求开始时间的最长随机间隔（秒）",
    )
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--replay-imports",
        action="store_true",
        help="不跳过数据库已确认的数据，用原始响应重放导入",
    )
    parser.add_argument(
        "--include-preview",
        action="store_true",
        help="同时采集 7 组赛事前瞻原始数据",
    )


def _validate_collection_controls(parser: argparse.ArgumentParser, args) -> None:
    if args.delay_min < 0 or args.delay_max < args.delay_min:
        parser.error("必须满足 0 <= delay-min <= delay-max")


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    settings = load_settings()
    repository = SportteryRepository(settings.database_path)
    if args.command == "report":
        raw_root = PROJECT_ROOT / "data" / "raw" / "sporttery"
        checkpoint = CheckpointStore(raw_root).load(args.year)
        print(json.dumps(
            _coverage_payload(repository.coverage_report(args.year), checkpoint),
            ensure_ascii=False,
            indent=2,
        ))
        return 0
    if args.command == "collect-years":
        return _collect_multiple_years(args, repository)
    return _collect_single_range(args, repository)


def _collect_single_range(args, repository: SportteryRepository) -> int:
    windows = list(_date_windows(args.start, args.end, 7))
    if args.dry_run:
        print(json.dumps({
            "start": args.start.isoformat(),
            "end": args.end.isoformat(),
            "windows": len(windows),
            "network_requests": 0,
            "preview_datasets": len(PREVIEW_DATASETS) if args.include_preview else 0,
        }, ensure_ascii=False, indent=2))
        return 0

    client = SportteryClient()
    service = _build_service(
        client, repository, args.delay_min, args.delay_max,
        lambda event: print(json.dumps(event, ensure_ascii=False), flush=True),
        include_preview=args.include_preview,
    )
    try:
        result = service.collect_range(
            args.start,
            args.end,
            resume=args.resume,
            replay_imports=args.replay_imports,
        )
    finally:
        client.client.close()
    print(json.dumps(asdict(result), ensure_ascii=False, indent=2, default=str))
    return _result_exit_code([result])


def _collect_multiple_years(
    args,
    repository: SportteryRepository,
) -> int:
    """并行下载不同年份；所有数据库写入由共享仓库锁串行保护。"""
    years = range(args.start_year, args.end_year + 1)
    today = date.today()
    if args.dry_run:
        print(json.dumps({
            "start_year": args.start_year,
            "end_year": args.end_year,
            "workers": args.workers,
            "years": len(years),
            "through": today.isoformat(),
            "network_requests": 0,
            "preview_datasets": len(PREVIEW_DATASETS) if args.include_preview else 0,
        }, ensure_ascii=False, indent=2))
        return 0

    synchronized_repository = SynchronizedSportteryRepository(repository)
    output_lock = threading.Lock()
    request_pacer = RequestStartPacer(args.delay_min, args.delay_max)

    def progress(year: int, event: dict[str, object]) -> None:
        with output_lock:
            print(json.dumps({"year": year, **event}, ensure_ascii=False), flush=True)

    def collect(year: int) -> CollectionReport:
        client = SportteryClient()
        end = today if year == today.year else date(year, 12, 31)
        service = _build_service(
            client,
            synchronized_repository,
            args.delay_min,
            args.delay_max,
            lambda event: progress(year, event),
            include_preview=args.include_preview,
            request_pacer=request_pacer,
        )
        try:
            def wait(seconds: float) -> None:
                progress(year, {"event": "rate_limit_wait", "seconds": seconds})
                time.sleep(seconds)

            return collect_with_blocked_retries(
                lambda resume: service.collect_range(
                    date(year, 1, 1),
                    end,
                    resume=resume,
                    replay_imports=args.replay_imports,
                ),
                initial_resume=args.resume,
                retries=args.blocked_retries,
                base_wait=args.blocked_wait,
                sleep=wait,
            )
        finally:
            client.client.close()

    results = collect_years(years, workers=args.workers, collect=collect)
    print(json.dumps([asdict(result) for result in results], ensure_ascii=False, indent=2, default=str))
    return _result_exit_code(results)


def _build_service(
    client,
    repository,
    delay_min,
    delay_max,
    progress,
    *,
    include_preview=False,
    request_pacer=None,
):
    raw_root = PROJECT_ROOT / "data" / "raw" / "sporttery"
    return SportteryCollectionService(
        client=client,
        raw_store=RawResponseStore(raw_root),
        checkpoint_store=CheckpointStore(raw_root),
        repository=repository,
        delay_min=delay_min,
        delay_max=delay_max,
        progress=progress,
        include_preview=include_preview,
        request_pacer=request_pacer,
    )


def _coverage_payload(
    report: CoverageReport, checkpoint: CollectionCheckpoint
) -> dict[str, object]:
    """合并数据库事实与检查点失败状态，避免报告漏掉尚未入库的失败项。"""
    payload = asdict(report)
    states = {state.dataset: state for state in checkpoint.preview_datasets}
    database_by_dataset = dict(report.preview_by_dataset)
    preview_by_dataset: dict[str, dict[str, int]] = {}
    for dataset in PREVIEW_DATASETS:
        completed, empty = database_by_dataset.get(dataset.code, (0, 0))
        state = states.get(dataset.code)
        preview_by_dataset[dataset.code] = {
            "completed": int(completed),
            "empty": int(empty),
            "failed": len(state.failed_ids) if state is not None else 0,
        }
    payload["completed_preview"] = report.completed_preview
    payload["empty_preview"] = report.empty_preview
    payload["failed_preview"] = sum(item["failed"] for item in preview_by_dataset.values())
    payload["preview_by_dataset"] = preview_by_dataset
    return payload


def _result_exit_code(results: Sequence[CollectionReport]) -> int:
    successful = {"completed", "completed_with_errors"}
    return 0 if all(result.status in successful for result in results) else 2


def _date_argument(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("日期必须使用 YYYY-MM-DD") from error


if __name__ == "__main__":
    raise SystemExit(main())
