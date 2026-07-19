#!/usr/bin/env python3
"""
高速把 raw/wencai/volamount 合并进 data/daily。
- 先汇总成长表，再按股票并行 join 写入
- 已有较多 volamount 的股票自动跳过（可断点续跑）
"""
from __future__ import annotations

import argparse
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
from tqdm import tqdm

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from a_share.config import load_settings
from a_share.storage import DAILY_COLUMNS, normalize_code, write_daily


def _merge_one(args: tuple[str, str, str, int]) -> tuple[str, str]:
    """(code, daily_dir, patch_path, min_filled) -> (code, status)"""
    code, daily_dir, patch_path, min_filled = args
    daily_path = Path(daily_dir) / f"{code}.parquet"
    patch = pd.read_parquet(patch_path)
    patch["date"] = pd.to_datetime(patch["date"]).dt.normalize()
    patch["volamount"] = pd.to_numeric(patch["volamount"], errors="coerce")
    patch = patch.dropna(subset=["date"]).drop_duplicates("date", keep="last")

    if daily_path.exists():
        df = pd.read_parquet(daily_path)
        df["date"] = pd.to_datetime(df["date"]).dt.normalize()
        if "volamount" in df.columns and df["volamount"].notna().sum() >= min_filled:
            return code, "skip"
        merged = df.merge(
            patch[["date", "volamount"]],
            on="date",
            how="outer",
            suffixes=("", "_new"),
        )
        if "volamount_new" in merged.columns:
            if "volamount" not in merged.columns:
                merged["volamount"] = merged["volamount_new"]
            else:
                merged["volamount"] = merged["volamount_new"].combine_first(
                    merged["volamount"]
                )
            merged = merged.drop(columns=["volamount_new"])
        merged["code"] = code
        for col in DAILY_COLUMNS:
            if col not in merged.columns:
                merged[col] = pd.NA
        write_daily(Path(daily_dir), code, merged[DAILY_COLUMNS])
        return code, "updated"
    else:
        out = patch.copy()
        out["code"] = code
        for col in DAILY_COLUMNS:
            if col not in out.columns:
                out[col] = pd.NA
        write_daily(Path(daily_dir), code, out[DAILY_COLUMNS])
        return code, "created"


def main() -> None:
    parser = argparse.ArgumentParser(description="并行高速合并 volamount 进 daily")
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument(
        "--min-filled",
        type=int,
        default=100,
        help="已有不少于该数量非空 volamount 则跳过",
    )
    args = parser.parse_args()

    settings = load_settings()
    daily_dir = Path(settings["storage"]["daily_path"])
    raw_dir = Path(settings["storage"]["raw_path"]) / "wencai" / "volamount"
    work = Path(settings["storage"]["raw_path"]) / "wencai" / "_vol_by_code"
    work.mkdir(parents=True, exist_ok=True)

    files = sorted(raw_dir.glob("*.parquet"))
    if not files:
        raise SystemExit(f"无 raw volamount: {raw_dir}")

    print(f"[1/3] 读取 {len(files)} 个 raw 日文件 ...")
    parts = []
    for path in tqdm(files, unit="日"):
        df = pd.read_parquet(path)
        if df.empty:
            continue
        if "date" not in df.columns:
            df = df.copy()
            df["date"] = pd.Timestamp(path.stem)
        parts.append(df[["date", "code", "volamount"]])
    big = pd.concat(parts, ignore_index=True)
    big["code"] = big["code"].map(normalize_code)
    big["date"] = pd.to_datetime(big["date"]).dt.normalize()
    big["volamount"] = pd.to_numeric(big["volamount"], errors="coerce")
    big = (
        big.dropna(subset=["code", "date"])
        .drop_duplicates(["code", "date"], keep="last")
        .sort_values(["code", "date"])
    )
    print(f"    长表 {len(big)} 行，股票 {big['code'].nunique()} 只")

    print(f"[2/3] 写出按股票分片到 {work} ...")
    jobs = []
    for code, grp in tqdm(big.groupby("code", sort=False), unit="只"):
        code = str(code)
        patch_path = work / f"{code}.parquet"
        grp[["date", "volamount"]].to_parquet(patch_path, index=False)
        jobs.append((code, str(daily_dir), str(patch_path), args.min_filled))

    print(f"[3/3] 并行合并 workers={args.workers} ...")
    ok = skip = created = fail = 0
    with ProcessPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futs = [pool.submit(_merge_one, job) for job in jobs]
        for fut in tqdm(as_completed(futs), total=len(futs), unit="只"):
            try:
                _, status = fut.result()
                if status == "skip":
                    skip += 1
                elif status == "created":
                    created += 1
                else:
                    ok += 1
            except Exception as exc:  # noqa: BLE001
                fail += 1
                tqdm.write(f"fail: {exc}")

    print(f"完成: updated={ok} created={created} skip={skip} fail={fail}")


if __name__ == "__main__":
    main()
