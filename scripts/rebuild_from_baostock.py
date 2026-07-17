#!/usr/bin/env python
"""清空坏日线后，用 baostock 全量重拉，并合并已有问财 volamount。"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from a_share.config import ensure_dirs, load_settings
from a_share.pipeline import merge_volamount_from_raw, update_daily, update_meta


def main() -> None:
    parser = argparse.ArgumentParser(description="baostock 全量重建日线 + 合并 volamount")
    parser.add_argument("--workers", type=int, default=None, help="并行进程数")
    parser.add_argument(
        "--keep-daily",
        action="store_true",
        help="不清空 data/daily（默认清空后重拉）",
    )
    parser.add_argument(
        "--skip-volamount-merge",
        action="store_true",
        help="不合并 raw/wencai/volamount",
    )
    parser.add_argument("--start", default=None, help="日线起始 YYYYMMDD")
    parser.add_argument("--end", default=None, help="日线结束 YYYYMMDD")
    args = parser.parse_args()

    settings = load_settings()
    ensure_dirs(settings)
    daily_dir = Path(settings["storage"]["daily_path"])
    import_dir = Path(settings["storage"]["root_path"]) / "import"

    if import_dir.exists():
        try:
            shutil.rmtree(import_dir)
            print(f"[clean] 已删除 {import_dir}")
        except OSError as exc:
            # Windows 下可能被下载进程占用，尽量逐文件删
            removed = 0
            for p in import_dir.glob("*"):
                try:
                    p.unlink()
                    removed += 1
                except OSError:
                    print(f"[clean] 跳过占用文件: {p.name}")
            print(f"[clean] import 部分清理 {removed} 个文件（{exc}）")

    if not args.keep_daily and daily_dir.exists():
        n = len(list(daily_dir.glob("*.parquet")))
        shutil.rmtree(daily_dir)
        daily_dir.mkdir(parents=True, exist_ok=True)
        print(f"[clean] 已清空 daily（原 {n} 个文件）")

    meta = update_meta(settings)
    print(
        f"[meta] 股票 {len(meta['stock_list'])} 只，"
        f"日历 {len(meta['trade_calendar'])} 天"
    )

    stats = update_daily(
        settings=settings,
        start=args.start,
        end=args.end,
        force=True,
        workers=args.workers,
    )
    print(
        f"[daily] 更新 {stats['ok']}，跳过 {stats['skip']}，"
        f"失败 {stats['fail']}，合计 {stats['total']}"
    )

    if stats["ok"] <= 0:
        print("[volamount] 日线未成功，跳过合并")
        raise SystemExit(1)

    if not args.skip_volamount_merge:
        vstats = merge_volamount_from_raw(settings=settings)
        print(
            f"[volamount] 合并文件 {vstats.get('files', 0)}，"
            f"更新 {vstats.get('updated', 0)}，新建 {vstats.get('created', 0)}，"
            f"行数 {vstats.get('rows', 0)}"
        )


if __name__ == "__main__":
    main()
