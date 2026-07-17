#!/usr/bin/env python
"""用问财补全全市场 VOLAMOUNT（总笔数）。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from a_share.pipeline import update_volamount


def main() -> None:
    parser = argparse.ArgumentParser(description="问财补全 A 股 VOLAMOUNT（总笔数）")
    parser.add_argument("--start", help="起始交易日 YYYYMMDD")
    parser.add_argument("--end", help="结束交易日 YYYYMMDD")
    parser.add_argument(
        "--days",
        type=int,
        default=None,
        help="回填最近 N 个交易日（与 start 互斥优先 days）",
    )
    parser.add_argument("--force", action="store_true", help="忽略本地 raw 缓存重拉")
    parser.add_argument(
        "--fetch-only",
        action="store_true",
        help="只写 raw，不合并进 daily",
    )
    args = parser.parse_args()

    stats = update_volamount(
        start=args.start,
        end=args.end,
        days=args.days,
        force=args.force,
        fetch_only=args.fetch_only,
    )
    print(
        f"完成: 拉取 {stats['ok']} 段，缓存跳过 {stats['skip']}，"
        f"失败 {stats['fail']}，交易日 {stats['total']}，"
        f"chunks={stats.get('chunks')}，行数 {stats['rows']}"
    )


if __name__ == "__main__":
    main()
