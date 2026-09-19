"""中国竞彩历史采集与覆盖率报告命令行入口。"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Sequence

from app.config import PROJECT_ROOT, load_settings
from app.sporttery.client import SportteryClient
from app.sporttery.repository import SportteryRepository
from app.sporttery.service import SportteryCollectionService, _date_windows
from app.sporttery.storage import CheckpointStore, RawResponseStore


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="采集和审计中国竞彩历史数据")
    subparsers = parser.add_subparsers(dest="command", required=True)
    collect = subparsers.add_parser("collect", help="采集一个自然年内的比赛与固定奖金")
    collect.add_argument("--start", required=True, type=_date_argument)
    collect.add_argument("--end", required=True, type=_date_argument)
    collect.add_argument("--delay-min", type=float, default=3.0)
    collect.add_argument("--delay-max", type=float, default=5.0)
    collect.add_argument("--resume", action="store_true")
    collect.add_argument("--dry-run", action="store_true")
    report = subparsers.add_parser("report", help="输出指定年份的数据库覆盖率")
    report.add_argument("--year", required=True, type=int)
    args = parser.parse_args(argv)
    if args.command == "collect":
        if args.end < args.start or args.start.year != args.end.year:
            parser.error("开始和结束日期必须位于同一自然年，且结束日期不能早于开始日期")
        if args.delay_min < 0 or args.delay_max < args.delay_min:
            parser.error("延迟范围无效：必须满足 0 <= delay-min <= delay-max")
    elif not 2000 <= args.year <= 2100:
        parser.error("year 必须在 2000 到 2100 之间")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    settings = load_settings()
    repository = SportteryRepository(settings.database_path)
    if args.command == "report":
        print(json.dumps(asdict(repository.coverage_report(args.year)), ensure_ascii=False, indent=2))
        return 0

    windows = list(_date_windows(args.start, args.end, 7))
    if args.dry_run:
        print(json.dumps({
            "start": args.start.isoformat(),
            "end": args.end.isoformat(),
            "windows": len(windows),
            "network_requests": 0,
        }, ensure_ascii=False, indent=2))
        return 0

    raw_root = PROJECT_ROOT / "data" / "raw" / "sporttery"
    client = SportteryClient()
    service = SportteryCollectionService(
        client=client,
        raw_store=RawResponseStore(raw_root),
        checkpoint_store=CheckpointStore(raw_root),
        repository=repository,
        delay_min=args.delay_min,
        delay_max=args.delay_max,
        progress=lambda event: print(json.dumps(event, ensure_ascii=False), flush=True),
    )
    try:
        result = service.collect_range(args.start, args.end, resume=args.resume)
    finally:
        client.client.close()
    print(json.dumps(asdict(result), ensure_ascii=False, indent=2, default=str))
    return 0 if result.status in {"completed", "completed_with_errors"} else 2


def _date_argument(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("日期必须使用 YYYY-MM-DD") from error


if __name__ == "__main__":
    raise SystemExit(main())

