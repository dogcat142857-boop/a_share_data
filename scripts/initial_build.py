#!/usr/bin/env python3
"""
一键全量构建：
  1. 清空旧数据
  2. baostock 拉全市场日线（含 baostock 全部交易字段）
  3. 问财 thsdk 拉全历史 volamount 并合并进 daily
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from a_share.config import load_settings
from a_share.maintenance import clean_all_data
from a_share.pipeline import merge_volamount_from_raw, update_daily, update_meta, update_volamount


def main() -> None:
    settings = load_settings()
    fetch_cfg = settings.get("fetch", {})
    wencai_cfg = settings.get("wencai", {})

    parser = argparse.ArgumentParser(description="全量构建：清空 → baostock 日线 → 问财 volamount")
    parser.add_argument("--keep-data", action="store_true", help="不清空已有 data")
    parser.add_argument("--workers", type=int, default=None, help="baostock 并行进程数")
    parser.add_argument(
        "--start",
        default=fetch_cfg.get("default_start", "19900101"),
        help="日线起始 YYYYMMDD",
    )
    parser.add_argument("--end", default=None, help="日线结束 YYYYMMDD")
    parser.add_argument(
        "--volamount-start",
        default=wencai_cfg.get("backfill_start", "20100101"),
        help="volamount 回填起始 YYYYMMDD",
    )
    parser.add_argument("--volamount-end", default=None, help="volamount 回填结束 YYYYMMDD")
    parser.add_argument("--skip-volamount", action="store_true", help="跳过问财 volamount")
    parser.add_argument("--skip-daily", action="store_true", help="跳过 baostock 日线")
    args = parser.parse_args()

    if not args.keep_data:
        stats = clean_all_data(settings)
        print("[clean]", stats)

    meta = update_meta(settings)
    print(
        f"[meta] 股票 {len(meta['stock_list'])} 只，"
        f"日历 {len(meta['trade_calendar'])} 天"
    )

    if not args.skip_daily:
        dstats = update_daily(
            settings=settings,
            start=args.start,
            end=args.end,
            force=True,
            workers=args.workers,
        )
        print(
            f"[daily] 更新 {dstats['ok']}，跳过 {dstats['skip']}，"
            f"失败 {dstats['fail']}，合计 {dstats['total']}"
        )
        if dstats["ok"] <= 0:
            print("[error] 日线拉取失败，中止")
            raise SystemExit(1)

    if args.skip_volamount or not wencai_cfg.get("enabled", True):
        print("[volamount] 已跳过")
        return

    print(
        f"[volamount] 回填 {args.volamount_start} -> "
        f"{args.volamount_end or 'today'}（先 raw 后合并）"
    )
    vstats = update_volamount(
        settings=settings,
        start=args.volamount_start,
        end=args.volamount_end,
        fetch_only=True,
        newest_first=True,
    )
    print(
        f"[volamount] 拉取 {vstats['ok']} 段，跳过 {vstats['skip']}，"
        f"失败 {vstats['fail']}，交易日 {vstats['total']}，行数 {vstats['rows']}"
    )

    mstats = merge_volamount_from_raw(
        settings=settings,
        start=args.volamount_start,
        end=args.volamount_end,
    )
    print(
        f"[volamount] 合并 files={mstats.get('files', 0)} "
        f"updated={mstats.get('updated', 0)} "
        f"created={mstats.get('created', 0)} rows={mstats.get('rows', 0)}"
    )
    print("[done] 全量构建完成。之后请每日运行 scripts/sync_all.py 增量更新。")


if __name__ == "__main__":
    main()
