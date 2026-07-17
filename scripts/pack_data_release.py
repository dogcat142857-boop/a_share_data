#!/usr/bin/env python
"""打包本地 data/ 为可分发的 zip，便于拷到其他机器后通过 A_SHARE_DATA_ROOT 调用。"""
from __future__ import annotations

import argparse
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description="打包 data/ 为 release zip")
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

    data = ROOT / "data"
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
                    zf.write(path, path.relative_to(ROOT).as_posix())
                    count += 1

    print(f"wrote {out} ({count} files, {out.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
