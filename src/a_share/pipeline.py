from __future__ import annotations

import time
from pathlib import Path

import pandas as pd
from tqdm import tqdm

from . import fetchers
from .config import ROOT, ensure_dirs, load_settings
from .storage import (
    last_trade_date,
    merge_daily,
    normalize_code,
    read_daily,
    write_daily,
)


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
) -> dict[str, int]:
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

    default_start = start or fetch_cfg.get("default_start", "20100101")
    end = end or pd.Timestamp.today().strftime("%Y%m%d")
    pause = float(fetch_cfg.get("request_pause", 0.35))
    skip_if_fresh = bool(update_cfg.get("skip_if_fresh", True)) and not force
    latest_cal = _latest_calendar_date(settings) if skip_if_fresh else None

    ok = skip = fail = 0
    errors: list[str] = []

    for code in tqdm(codes, desc="更新日线", unit="只"):
        try:
            existing = read_daily(daily_dir, code)
            last = last_trade_date(existing)
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

            new = fetchers.fetch_daily_hist(
                code,
                pull_start,
                end,
                max_retries=fetch_cfg.get("max_retries", 3),
                retry_pause=fetch_cfg.get("retry_pause", 2.0),
            )
            merged = merge_daily(existing, new)
            write_daily(daily_dir, code, merged)
            ok += 1
            time.sleep(pause)
        except Exception as exc:  # noqa: BLE001
            fail += 1
            errors.append(f"{code}: {exc}")
            time.sleep(pause)

    if errors:
        log_dir = ROOT / "logs"
        log_dir.mkdir(exist_ok=True)
        stamp = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")
        (log_dir / f"daily_errors_{stamp}.log").write_text(
            "\n".join(errors), encoding="utf-8"
        )

    return {"ok": ok, "skip": skip, "fail": fail, "total": len(codes)}
