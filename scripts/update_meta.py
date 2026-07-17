#!/usr/bin/env python
"""更新股票列表与交易日历。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from a_share.pipeline import update_meta

if __name__ == "__main__":
    result = update_meta()
    print(
        f"股票列表 {len(result['stock_list'])} 只，"
        f"交易日历 {len(result['trade_calendar'])} 天"
    )
