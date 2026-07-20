#!/usr/bin/env python
"""打包本地数据根目录为可分发 zip，便于拷到其他机器后通过 A_SHARE_DATA_ROOT 调用。"""
from __future__ import annotations

import argparse
import sys
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from a_share.config import load_settings


def main() -> None:
    parser = argparse.ArgumentParser(description="打包数据根目录为 release zip")
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="输出 zip 路径，默认 dist/a_share_data_YYYYMMDD.zip",
    )
    parser.add_argument(
        "--include-raw",
        action="store_true",
        help="同时打包 raw/wencai（体积更大）",
    )
    args = parser.parse_args()

    settings = load_settings()
    data = Path(settings["storage"]["root_path"])
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d")
    out = Path(args.output) if args.output else dist / f"a_share_data_{stamp}.zip"

    patterns = ["meta/**/*", "daily/**/*"]
    if args.include_raw:
        patterns.append("raw/**/*")

    count = 0
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for pattern in patterns:
            for path in data.glob(pattern):
                if path.is_file() and path.name != ".gitkeep":
                    # zip 内统一为 data/...，方便解压后设 A_SHARE_DATA_ROOT
                    arc = Path("data") / path.relative_to(data)
                    zf.write(path, arc.as_posix())
                    count += 1

    print(f"wrote {out} ({count} files, {out.stat().st_size / 1e6:.1f} MB)")
    print(f"source {data}")


if __name__ == "__main__":
    main()
