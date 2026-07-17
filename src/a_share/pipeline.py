from __future__ import annotations

import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
from tqdm import tqdm

from . import fetchers
from . import wencai as wencai_api
from .config import ROOT, ensure_dirs, load_settings
from .storage import (
    apply_volamount_frames,
    merge_daily,
    normalize_code,
    read_daily,
    write_daily,
)


def _last_ohlcv_date(df: pd.DataFrame) -> pd.Timestamp | None:
    """仅把有收盘价的日期视为 OHLCV 已就绪（忽略仅有 volamount 的行）。"""
    if df is None or df.empty or "close" not in df.columns:
        return None
    sub = df[df["close"].notna()]
    if sub.empty:
        return None
    return pd.to_datetime(sub["date"]).max()


def _read_watchlist(path: Path) -> list[str]:
    codes: list[str] = []
    if not path.exists():
        return codes
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        codes.append(normalize_code(line))
    return codes


def resolve_universe(settings: dict | None = None) -> pd.DataFrame:
    settings = settings or load_settings()
    ensure_dirs(settings)
    meta_path = Path(settings["storage"]["meta_path"])
    list_path = meta_path / "stock_list.parquet"

    mode = settings.get("universe", {}).get("mode", "all")
    if mode == "watchlist":
        watchlist_rel = settings["universe"].get("watchlist", "config/watchlist.txt")
        codes = _read_watchlist(ROOT / watchlist_rel)
        if not codes:
            raise ValueError(
                f"watchlist 为空，请编辑 {watchlist_rel} 或将 universe.mode 改为 all"
            )
        if list_path.exists():
            full = pd.read_parquet(list_path)
            full["code"] = full["code"].map(normalize_code)
            return full[full["code"].isin(codes)].reset_index(drop=True)
        return pd.DataFrame({"code": codes, "name": pd.NA})

    if list_path.exists():
        df = pd.read_parquet(list_path)
        df["code"] = df["code"].map(normalize_code)
        return df.reset_index(drop=True)

    return update_meta(settings)["stock_list"]


def update_meta(settings: dict | None = None) -> dict[str, pd.DataFrame]:
    settings = settings or load_settings()
    ensure_dirs(settings)
    fetch_cfg = settings.get("fetch", {})
    meta_path = Path(settings["storage"]["meta_path"])

    stock_list = fetchers.fetch_stock_list(
        max_retries=fetch_cfg.get("max_retries", 3),
        retry_pause=fetch_cfg.get("retry_pause", 2.0),
    )
    calendar = fetchers.fetch_trade_calendar(
        max_retries=fetch_cfg.get("max_retries", 3),
        retry_pause=fetch_cfg.get("retry_pause", 2.0),
    )

    stock_list.to_parquet(meta_path / "stock_list.parquet", index=False)
    calendar.to_parquet(meta_path / "trade_calendar.parquet", index=False)
    stock_list.to_csv(meta_path / "stock_list.csv", index=False, encoding="utf-8-sig")
    calendar.to_csv(meta_path / "trade_calendar.csv", index=False, encoding="utf-8-sig")
    return {"stock_list": stock_list, "trade_calendar": calendar}


def _latest_calendar_date(settings: dict) -> pd.Timestamp | None:
    cal_path = Path(settings["storage"]["meta_path"]) / "trade_calendar.parquet"
    if not cal_path.exists():
        return None
    cal = pd.read_parquet(cal_path)
    if cal.empty:
        return None
    today = pd.Timestamp.today().normalize()
    dates = pd.to_datetime(cal["date"])
    past = dates[dates <= today]
    if past.empty:
        return None
    return past.max()


def update_daily(
    codes: list[str] | None = None,
    *,
    settings: dict | None = None,
    start: str | None = None,
    end: str | None = None,
    force: bool = False,
    workers: int | None = None,
) -> dict[str, int]:
    """
    用 baostock 更新个股日线。
    workers>1 时用多进程并行（baostock 会话是进程级全局状态）。
    """
    settings = settings or load_settings()
    ensure_dirs(settings)
    fetch_cfg = settings.get("fetch", {})
    update_cfg = settings.get("update", {})
    daily_dir = Path(settings["storage"]["daily_path"])

    if codes is None:
        universe = resolve_universe(settings)
        codes = universe["code"].map(normalize_code).tolist()
    else:
        codes = [normalize_code(c) for c in codes]

    # 排除北交所
    codes = [
        c
        for c in codes
        if not c.startswith(("4", "8")) and not c.startswith("92")
    ]

    default_start = start or fetch_cfg.get("default_start", "20100101")
    end = end or pd.Timestamp.today().strftime("%Y%m%d")
    pause = float(fetch_cfg.get("request_pause", 0.05))
    skip_if_fresh = bool(update_cfg.get("skip_if_fresh", True)) and not force
    latest_cal = _latest_calendar_date(settings) if skip_if_fresh else None
    max_retries = int(fetch_cfg.get("max_retries", 3))
    retry_pause = float(fetch_cfg.get("retry_pause", 2.0))
    n_workers = int(workers if workers is not None else fetch_cfg.get("workers", 8))

    jobs: list[tuple[str, str, str, int, float]] = []
    skip = 0
    for code in codes:
        existing = read_daily(daily_dir, code)
        last = _last_ohlcv_date(existing)
        if skip_if_fresh and last is not None and latest_cal is not None:
            if last.normalize() >= latest_cal.normalize():
                skip += 1
                continue
        if last is not None and not force:
            pull_start = (last + pd.Timedelta(days=1)).strftime("%Y%m%d")
        else:
            pull_start = default_start
        if pull_start > end:
            skip += 1
            continue
        jobs.append((code, pull_start, end, max_retries, retry_pause))

    ok = fail = 0
    errors: list[str] = []

    def _commit(code: str, new: pd.DataFrame) -> None:
        existing = read_daily(daily_dir, code)
        # force 时用新 OHLCV 覆盖同日价量，仍通过 merge 保留已有 volamount
        merged = merge_daily(existing, new)
        write_daily(daily_dir, code, merged)

    if n_workers <= 1 or len(jobs) <= 1:
        for code, pull_start, pull_end, *_ in tqdm(jobs, desc="更新日线(baostock)", unit="只"):
            try:
                new = fetchers.fetch_daily_hist(
                    code,
                    pull_start,
                    pull_end,
                    max_retries=max_retries,
                    retry_pause=retry_pause,
                )
                _commit(code, new)
                ok += 1
                if pause > 0:
                    time.sleep(pause)
            except Exception as exc:  # noqa: BLE001
                fail += 1
                errors.append(f"{code}: {exc}")
    else:
        with ProcessPoolExecutor(
            max_workers=max(1, n_workers),
            initializer=fetchers._worker_login,
        ) as pool:
            futs = {
                pool.submit(fetchers.fetch_daily_worker, job): job[0] for job in jobs
            }
            for fut in tqdm(
                as_completed(futs),
                total=len(futs),
                desc=f"更新日线(baostock×{n_workers})",
                unit="只",
            ):
                code = futs[fut]
                try:
                    code, new, err = fut.result()
                    if err or new is None:
                        fail += 1
                        errors.append(f"{code}: {err or 'empty'}")
                        continue
                    _commit(code, new)
                    ok += 1
                except Exception as exc:  # noqa: BLE001
                    fail += 1
                    errors.append(f"{code}: {exc}")

    if errors:
        log_dir = ROOT / "logs"
        log_dir.mkdir(exist_ok=True)
        stamp = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")
        (log_dir / f"daily_errors_{stamp}.log").write_text(
            "\n".join(errors), encoding="utf-8"
        )

    return {"ok": ok, "skip": skip, "fail": fail, "total": len(codes)}


def _trade_dates_between(
    settings: dict,
    start: str | None,
    end: str | None,
) -> list[pd.Timestamp]:
    cal_path = Path(settings["storage"]["meta_path"]) / "trade_calendar.parquet"
    if not cal_path.exists():
        update_meta(settings)
    cal = pd.read_parquet(cal_path)
    dates = pd.to_datetime(cal["date"]).sort_values()
    today = pd.Timestamp.today().normalize()
    end_ts = pd.Timestamp(end) if end else today
    end_ts = min(end_ts.normalize(), today)
    if start:
        start_ts = pd.Timestamp(start).normalize()
    else:
        start_ts = end_ts
    mask = (dates >= start_ts) & (dates <= end_ts)
    return [pd.Timestamp(d).normalize() for d in dates[mask].tolist()]


def _volamount_raw_path(settings: dict, trade_date: pd.Timestamp) -> Path:
    raw = Path(settings["storage"]["raw_path"]) / "wencai" / "volamount"
    return raw / f"{trade_date.strftime('%Y%m%d')}.parquet"


def _volamount_chunk_path(
    settings: dict, start: pd.Timestamp, end: pd.Timestamp
) -> Path:
    raw = Path(settings["storage"]["raw_path"]) / "wencai" / "volamount_chunks"
    return raw / f"{start.strftime('%Y%m%d')}_{end.strftime('%Y%m%d')}.parquet"


def _iter_date_chunks(
    dates: list[pd.Timestamp], chunk_days: int
) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """把交易日列表按日历跨度切成若干 [start,end] 区间（默认约一个月）。"""
    if not dates:
        return []
    dates = sorted(pd.Timestamp(d).normalize() for d in dates)
    chunk_days = max(int(chunk_days), 1)
    chunks: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    i = 0
    while i < len(dates):
        start = dates[i]
        end_limit = start + pd.Timedelta(days=chunk_days - 1)
        j = i
        while j + 1 < len(dates) and dates[j + 1] <= end_limit:
            j += 1
        chunks.append((start, dates[j]))
        i = j + 1
    return chunks


def _chunk_fully_cached(
    settings: dict,
    start: pd.Timestamp,
    end: pd.Timestamp,
    dates: list[pd.Timestamp],
) -> bool:
    needed = [d for d in dates if start <= d <= end]
    if not needed:
        return True
    return all(_volamount_raw_path(settings, d).exists() for d in needed)


def _save_volamount_long(settings: dict, long_df: pd.DataFrame) -> None:
    if long_df.empty:
        return
    data = long_df.copy()
    data["date"] = pd.to_datetime(data["date"]).dt.normalize()
    for day, grp in data.groupby("date", sort=True):
        path = _volamount_raw_path(settings, pd.Timestamp(day))
        path.parent.mkdir(parents=True, exist_ok=True)
        grp[["date", "code", "volamount"]].reset_index(drop=True).to_parquet(
            path, index=False
        )


def update_volamount(
    *,
    settings: dict | None = None,
    start: str | None = None,
    end: str | None = None,
    force: bool = False,
    days: int | None = None,
    fetch_only: bool = False,
    newest_first: bool = True,
) -> dict[str, int]:
    """
    用 thsdk.wencai_nlp 按日期区间批量补全全市场 volamount（总笔数）。
    问句形如：沪深A股,2024年1月2日至2024年1月31日总笔数
    """
    settings = settings or load_settings()
    ensure_dirs(settings)
    wencai_cfg = settings.get("wencai", {})
    if not wencai_cfg.get("enabled", True):
        return {"ok": 0, "skip": 0, "fail": 0, "total": 0, "rows": 0, "chunks": 0}

    daily_dir = Path(settings["storage"]["daily_path"])
    merge_into_daily = bool(wencai_cfg.get("merge_into_daily", True)) and not fetch_only
    chunk_days = int(wencai_cfg.get("chunk_days", 31))
    chunk_pause = float(wencai_cfg.get("chunk_pause", 1.0))
    universe = str(wencai_cfg.get("universe", "沪深A股"))
    metric = str(wencai_cfg.get("metric", "总笔数"))

    if days is not None and start is None:
        latest = _latest_calendar_date(settings)
        if latest is None:
            raise RuntimeError("无交易日历，请先运行 update-meta")
        cal_path = Path(settings["storage"]["meta_path"]) / "trade_calendar.parquet"
        cal = pd.read_parquet(cal_path)
        cal_dates = pd.to_datetime(cal["date"]).sort_values()
        past = cal_dates[cal_dates <= latest]
        selected = past.tail(max(int(days), 1))
        date_list = [pd.Timestamp(d).normalize() for d in selected.tolist()]
    else:
        date_list = _trade_dates_between(settings, start, end)

    if not date_list:
        return {"ok": 0, "skip": 0, "fail": 0, "total": 0, "rows": 0, "chunks": 0}

    chunks = _iter_date_chunks(date_list, chunk_days)
    if newest_first:
        chunks = list(reversed(chunks))

    ok = skip = fail = rows = 0
    errors: list[str] = []
    progress_path = Path(settings["storage"]["meta_path"]) / "volamount_progress.txt"
    merged_frames: list[pd.DataFrame] = []

    for chunk_start, chunk_end in tqdm(chunks, desc="更新VOLAMOUNT", unit="段"):
        label = f"{chunk_start.strftime('%Y%m%d')}-{chunk_end.strftime('%Y%m%d')}"
        try:
            if not force and _chunk_fully_cached(
                settings, chunk_start, chunk_end, date_list
            ):
                parts = [
                    pd.read_parquet(_volamount_raw_path(settings, d))
                    for d in date_list
                    if chunk_start <= d <= chunk_end
                    and _volamount_raw_path(settings, d).exists()
                ]
                long_df = (
                    pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
                )
                skip += 1
            else:
                long_df = wencai_api.fetch_volamount_range(
                    chunk_start,
                    chunk_end,
                    settings=settings,
                    universe=universe,
                    metric=metric,
                    max_retries=int(wencai_cfg.get("max_retries", 3)),
                    retry_pause=float(wencai_cfg.get("retry_pause", 2.0)),
                )
                if long_df.empty:
                    raise ValueError("问财返回空表")
                wanted = {d for d in date_list if chunk_start <= d <= chunk_end}
                long_df = long_df[
                    pd.to_datetime(long_df["date"]).dt.normalize().isin(wanted)
                ]
                chunk_path = _volamount_chunk_path(settings, chunk_start, chunk_end)
                chunk_path.parent.mkdir(parents=True, exist_ok=True)
                long_df.to_parquet(chunk_path, index=False)
                _save_volamount_long(settings, long_df)
                ok += 1
                time.sleep(chunk_pause)

            rows += len(long_df)
            if merge_into_daily and not long_df.empty:
                merged_frames.append(long_df)

            progress_path.write_text(
                f"last={label}\nok={ok}\nskip={skip}\nfail={fail}\nrows={rows}\n",
                encoding="utf-8",
            )
        except Exception as exc:  # noqa: BLE001
            fail += 1
            errors.append(f"{label}: {exc}")
            progress_path.write_text(
                f"last={label}\nok={ok}\nskip={skip}\nfail={fail}\nerr={exc}\n",
                encoding="utf-8",
            )
            time.sleep(chunk_pause)

    if merge_into_daily and merged_frames:
        big = pd.concat(merged_frames, ignore_index=True)
        apply_volamount_frames(daily_dir, big)

    if errors:
        log_dir = ROOT / "logs"
        log_dir.mkdir(exist_ok=True)
        stamp = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")
        (log_dir / f"volamount_errors_{stamp}.log").write_text(
            "\n".join(errors), encoding="utf-8"
        )

    return {
        "ok": ok,
        "skip": skip,
        "fail": fail,
        "total": len(date_list),
        "rows": rows,
        "chunks": len(chunks),
    }


def merge_volamount_from_raw(
    *,
    settings: dict | None = None,
    start: str | None = None,
    end: str | None = None,
) -> dict[str, int]:
    """把 data/raw/wencai/volamount/*.parquet 批量合并进个股日线。"""
    settings = settings or load_settings()
    ensure_dirs(settings)
    raw_dir = Path(settings["storage"]["raw_path"]) / "wencai" / "volamount"
    daily_dir = Path(settings["storage"]["daily_path"])
    files = sorted(raw_dir.glob("*.parquet"))
    if start:
        start_ts = pd.Timestamp(start).normalize()
        files = [
            f for f in files if f.stem.isdigit() and pd.Timestamp(f.stem) >= start_ts
        ]
    if end:
        end_ts = pd.Timestamp(end).normalize()
        files = [
            f for f in files if f.stem.isdigit() and pd.Timestamp(f.stem) <= end_ts
        ]
    if not files:
        return {"files": 0, "updated": 0, "created": 0, "rows": 0}

    frames: list[pd.DataFrame] = []
    for path in tqdm(files, desc="读取VOLAMOUNT raw", unit="日"):
        df = pd.read_parquet(path)
        if df.empty:
            continue
        if "date" not in df.columns:
            df = df.copy()
            df["date"] = pd.Timestamp(path.stem)
        frames.append(df[["date", "code", "volamount"]])

    if not frames:
        return {"files": len(files), "updated": 0, "created": 0, "rows": 0}

    big = pd.concat(frames, ignore_index=True)
    stats = apply_volamount_frames(daily_dir, big)
    stats["files"] = len(files)
    stats["rows"] = len(big)
    return stats
