#!/usr/bin/env python
"""日常一键同步：元数据 → baostock 日线 → 问财 VOLAMOUNT。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from a_share.config import load_settings
from a_share.pipeline import update_daily, update_meta, update_volamount


def main() -> None:
    parser = argparse.ArgumentParser(description="一键同步 meta + 日线 + volamount")
    parser.add_argument("--force-daily", action="store_true", help="强制重拉日线")
    parser.add_argument("--workers", type=int, default=None, help="日线并行进程数")
    parser.add_argument("--skip-volamount", action="store_true", help="跳过问财")
    args = parser.parse_args()

    settings = load_settings()
    meta = update_meta(settings)
    print(
        f"[meta] 股票 {len(meta['stock_list'])} 只，"
        f"日历 {len(meta['trade_calendar'])} 天"
    )
    stats = update_daily(
        settings=settings, force=args.force_daily, workers=args.workers
    )
    print(
        f"[daily] 更新 {stats['ok']}，跳过 {stats['skip']}，"
        f"失败 {stats['fail']}，合计 {stats['total']}"
    )

    wencai_cfg = settings.get("wencai", {})
    if args.skip_volamount or not wencai_cfg.get("enabled", True):
        print("[volamount] 已跳过")
        return

    days = int(wencai_cfg.get("daily_days", 1))
    vstats = update_volamount(settings=settings, days=days)
    print(
        f"[volamount] 拉取 {vstats['ok']} 段，跳过 {vstats['skip']}，"
        f"失败 {vstats['fail']}，交易日 {vstats['total']}，行数 {vstats['rows']}"
    )


if __name__ == "__main__":
    main()
