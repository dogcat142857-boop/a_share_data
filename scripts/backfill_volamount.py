#!/usr/bin/env python
"""
全量补全 VOLAMOUNT：由近到远抓取所有交易日 raw，最后批量合并进个股日线。
可重复执行（已有 raw 会跳过）。约 4000 个交易日，需长时间运行。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from a_share.config import load_settings
from a_share.pipeline import merge_volamount_from_raw, update_volamount


def main() -> None:
    settings = load_settings()
    wencai = settings.get("wencai", {})
    default_start = wencai.get(
        "backfill_start", settings.get("fetch", {}).get("default_start", "20100101")
    )

    parser = argparse.ArgumentParser(description="全量回填问财 VOLAMOUNT")
    parser.add_argument("--start", default=default_start, help="起始 YYYYMMDD")
    parser.add_argument("--end", default=None, help="结束 YYYYMMDD，默认今天")
    parser.add_argument("--force", action="store_true", help="强制重拉已有 raw")
    parser.add_argument(
        "--merge-only",
        action="store_true",
        help="只把已有 raw 合并进 daily，不再请求问财",
    )
    parser.add_argument(
        "--live-merge",
        action="store_true",
        help="边抓边写入 daily（更慢）；默认先抓完 raw 再批量合并",
    )
    args = parser.parse_args()

    if args.merge_only:
        stats = merge_volamount_from_raw(
            settings=settings, start=args.start, end=args.end
        )
        print(
            f"[merge] files={stats['files']} updated={stats['updated']} "
            f"created={stats['created']} rows={stats['rows']}"
        )
        return

    fetch_only = not args.live_merge
    mode = "raw only" if fetch_only else "live merge"
    print(f"[fetch] {args.start} -> {args.end or 'today'} ({mode}, newest first)")
    stats = update_volamount(
        settings=settings,
        start=args.start,
        end=args.end,
        force=args.force,
        fetch_only=fetch_only,
        newest_first=True,
    )
    print(
        f"[fetch] 拉取 {stats['ok']} 段，跳过 {stats['skip']}，"
        f"失败 {stats['fail']}，交易日 {stats['total']}，"
        f"chunks={stats.get('chunks')}，行数 {stats['rows']}"
    )

    if fetch_only:
        print("[merge] 批量写入 daily ...")
        mstats = merge_volamount_from_raw(
            settings=settings, start=args.start, end=args.end
        )
        print(
            f"[merge] files={mstats['files']} updated={mstats['updated']} "
            f"created={mstats['created']} rows={mstats['rows']}"
        )


if __name__ == "__main__":
    main()
