#!/usr/bin/env python
"""日常一键同步：元数据 → 日线 OHLCV → 问财 VOLAMOUNT。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from a_share.config import load_settings
from a_share.pipeline import update_daily, update_meta, update_volamount


def main() -> None:
    settings = load_settings()
    meta = update_meta(settings)
    print(
        f"[meta] 股票 {len(meta['stock_list'])} 只，"
        f"日历 {len(meta['trade_calendar'])} 天"
    )
    stats = update_daily(settings=settings)
    print(
        f"[daily] 更新 {stats['ok']}，跳过 {stats['skip']}，"
        f"失败 {stats['fail']}，合计 {stats['total']}"
    )

    wencai_cfg = settings.get("wencai", {})
    if wencai_cfg.get("enabled", True):
        days = int(wencai_cfg.get("daily_days", 1))
        vstats = update_volamount(settings=settings, days=days)
        print(
            f"[volamount] 拉取 {vstats['ok']}，缓存跳过 {vstats['skip']}，"
            f"失败 {vstats['fail']}，合计 {vstats['total']} 日，行数 {vstats['rows']}"
        )
    else:
        print("[volamount] 已禁用（settings.wencai.enabled=false）")


if __name__ == "__main__":
    main()
