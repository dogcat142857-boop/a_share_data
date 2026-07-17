#!/usr/bin/env python
"""增量/全量更新个股日线（baostock 前复权）。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from a_share.pipeline import update_daily


def main() -> None:
    parser = argparse.ArgumentParser(description="更新 A 股个股日线（baostock）")
    parser.add_argument("-c", "--code", action="append", help="股票代码，可多次指定")
    parser.add_argument("--start", help="起始日期 YYYYMMDD")
    parser.add_argument("--end", help="结束日期 YYYYMMDD")
    parser.add_argument("--force", action="store_true", help="强制按 start 重拉")
    parser.add_argument("--workers", type=int, default=None, help="并行进程数")
    args = parser.parse_args()

    stats = update_daily(
        args.code,
        start=args.start,
        end=args.end,
        force=args.force,
        workers=args.workers,
    )
    print(
        f"完成: 更新 {stats['ok']}，跳过 {stats['skip']}，"
        f"失败 {stats['fail']}，合计 {stats['total']}"
    )


if __name__ == "__main__":
    main()
