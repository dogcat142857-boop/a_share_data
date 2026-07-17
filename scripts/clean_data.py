#!/usr/bin/env python3
"""清空 data/ 下全部本地行情与问财缓存。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from a_share.maintenance import clean_all_data


def main() -> None:
    parser = argparse.ArgumentParser(description="清空 data/daily meta raw import")
    parser.add_argument("--keep-logs", action="store_true", help="保留 logs/")
    args = parser.parse_args()
    stats = clean_all_data(keep_logs=args.keep_logs)
    for k, v in stats.items():
        print(f"[clean] {k}: 删除 {v} 个文件")
    print("完成。可运行 scripts/initial_build.py 重新拉取。")


if __name__ == "__main__":
    main()
