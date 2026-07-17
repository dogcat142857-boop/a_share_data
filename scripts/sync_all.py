#!/usr/bin/env python
"""先更新元数据，再增量更新日线（日常一键同步）。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from a_share.pipeline import update_daily, update_meta


def main() -> None:
    meta = update_meta()
    print(
        f"[meta] 股票 {len(meta['stock_list'])} 只，"
        f"日历 {len(meta['trade_calendar'])} 天"
    )
    stats = update_daily()
    print(
        f"[daily] 更新 {stats['ok']}，跳过 {stats['skip']}，"
        f"失败 {stats['fail']}，合计 {stats['total']}"
    )


if __name__ == "__main__":
    main()
