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
    apply_ohlcv_frames,
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


def _valid_daily(df: pd.DataFrame) -> bool:
    """至少有一条有效收盘价。"""
    return (
        df is not None
        and not df.empty
        and "close" in df.columns
        and df["close"].notna().any()
    )


def _is_baostock_systemic_error(msg: str | None) -> bool:
    """
    判断是否为 baostock 全局不可用（登录上限、会话失效、网络中断等）。
    这类错误不应再对剩余股票做逐只重试，应尽快交给问财兜底。
    """
    if not msg:
        return False
    text = str(msg).lower()
    needles = (
        "login failed",
        "user login",
        "10001011",  # baostock 用户数限制
        "10001001",
        "worker login failed",
        "winerror 10057",
        "winerror 10054",
        "connection aborted",
        "connection reset",
        "remotelyclosed",
        "远程主机关闭",
        "没有连接",
        "未连接",
        "用户数量",
        "超过最大",
    )
    return any(n in text for n in needles)


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
    baostock_ok = True

    # 先探测 baostock；不可用则跳过逐只重试，交给问财兜底
    if jobs:
        try:
            import baostock as bs

            lg = bs.login()
            if lg.error_code != "0":
                baostock_ok = False
                errors.append(f"baostock login: {lg.error_msg}")
            else:
                try:
                    bs.logout()
                except Exception:  # noqa: BLE001
                    pass
        except Exception as exc:  # noqa: BLE001
            baostock_ok = False
            errors.append(f"baostock probe: {exc}")

    def _commit(code: str, new: pd.DataFrame) -> None:
        if not _valid_daily(new):
            raise ValueError("返回空表或无有效收盘价")
        existing = read_daily(daily_dir, code)
        merged = merge_daily(existing, new)
        write_daily(daily_dir, code, merged)

    # 连续/累计出现全局错误时，提前放弃 baostock，改走问财
    systemic_abort_after = int(fetch_cfg.get("baostock_systemic_abort_after", 8))
    retry_max = int(fetch_cfg.get("baostock_retry_max", 30))
    systemic_hits = 0
    aborted_systemic = False

    if not jobs:
        pass
    elif not baostock_ok:
        fail = len(jobs)
        print(f"[daily] baostock 不可用，跳过 {fail} 只，改走问财兜底")
    elif n_workers <= 1 or len(jobs) <= 1:
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
                systemic_hits = 0
                if pause > 0:
                    time.sleep(pause)
            except Exception as exc:  # noqa: BLE001
                fail += 1
                err_s = str(exc)
                errors.append(f"{code}: {err_s}")
                if _is_baostock_systemic_error(err_s):
                    systemic_hits += 1
                    if systemic_hits >= systemic_abort_after:
                        aborted_systemic = True
                        remain = len(jobs) - ok - fail
                        if remain > 0:
                            fail += remain
                        print(
                            f"[daily] baostock 连续全局失败 {systemic_hits} 次，"
                            f"跳过剩余 {max(remain, 0)} 只，改走问财兜底"
                        )
                        break
                else:
                    systemic_hits = 0
    else:
        failed_jobs: list[tuple[str, str, str, int, float]] = []
        retry_candidates: list[tuple[str, str, str, int, float]] = []
        processed: set = set()
        with ProcessPoolExecutor(
            max_workers=max(1, n_workers),
            initializer=fetchers._worker_login,
        ) as pool:
            futs = {
                pool.submit(fetchers.fetch_daily_worker, job): job for job in jobs
            }
            for fut in tqdm(
                as_completed(futs),
                total=len(futs),
                desc=f"更新日线(baostock×{n_workers})",
                unit="只",
            ):
                processed.add(fut)
                job = futs[fut]
                code = job[0]
                try:
                    code, new, err = fut.result()
                    if err or new is None:
                        fail += 1
                        err_s = str(err or "empty")
                        failed_jobs.append(job)
                        errors.append(f"{code}: {err_s}")
                        if _is_baostock_systemic_error(err_s):
                            systemic_hits += 1
                            if systemic_hits >= systemic_abort_after:
                                aborted_systemic = True
                                print(
                                    f"[daily] baostock 连续全局失败 {systemic_hits} 次，"
                                    f"中止并行拉取，改走问财兜底"
                                )
                        else:
                            systemic_hits = 0
                            retry_candidates.append(job)
                    else:
                        _commit(code, new)
                        ok += 1
                        systemic_hits = 0
                except Exception as exc:  # noqa: BLE001
                    fail += 1
                    err_s = str(exc)
                    failed_jobs.append(job)
                    errors.append(f"{code}: {err_s}")
                    if _is_baostock_systemic_error(err_s):
                        systemic_hits += 1
                        if systemic_hits >= systemic_abort_after:
                            aborted_systemic = True
                            print(
                                f"[daily] baostock 连续全局失败 {systemic_hits} 次，"
                                f"中止并行拉取，改走问财兜底"
                            )
                    else:
                        systemic_hits = 0
                        retry_candidates.append(job)

                if aborted_systemic:
                    for pending, pjob in futs.items():
                        if pending in processed:
                            continue
                        pending.cancel()
                        fail += 1
                        failed_jobs.append(pjob)
                        errors.append(f"{pjob[0]}: aborted (baostock systemic)")
                    break

        # 仅对「非全局」失败做有限单进程重试；登录上限类错误直接交给问财
        if aborted_systemic:
            print(
                f"[daily] 跳过 baostock 逐只重试"
                f"（失败 {fail}，成功 {ok}），优先问财兜底"
            )
        elif retry_candidates:
            to_retry = retry_candidates[: max(0, retry_max)]
            if len(retry_candidates) > len(to_retry):
                print(
                    f"[daily] 非全局失败 {len(retry_candidates)} 只，"
                    f"仅重试前 {len(to_retry)} 只"
                )
            retry_ok = 0
            retry_systemic = 0
            for job in tqdm(to_retry, desc="重试失败股票", unit="只"):
                code, pull_start, pull_end, *_ = job
                try:
                    new = fetchers.fetch_daily_hist(
                        code,
                        pull_start,
                        pull_end,
                        max_retries=min(max_retries, 2),
                        retry_pause=retry_pause,
                    )
                    _commit(code, new)
                    ok += 1
                    retry_ok += 1
                    fail -= 1
                    errors = [e for e in errors if not e.startswith(f"{code}:")]
                    retry_systemic = 0
                    if pause > 0:
                        time.sleep(pause)
                except Exception as exc:  # noqa: BLE001
                    err_s = str(exc)
                    errors.append(f"{code}: retry {err_s}")
                    if _is_baostock_systemic_error(err_s):
                        retry_systemic += 1
                        if retry_systemic >= 3:
                            print(
                                "[daily] 重试阶段再次遇到 baostock 全局失败，"
                                "停止重试，改走问财兜底"
                            )
                            break
                    else:
                        retry_systemic = 0
            if retry_ok:
                print(f"[daily] 单进程重试成功 {retry_ok} 只")

    if errors:
        log_dir = ROOT / "logs"
        log_dir.mkdir(exist_ok=True)
        stamp = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")
        (log_dir / f"daily_errors_{stamp}.log").write_text(
            "\n".join(errors), encoding="utf-8"
        )

    stats = {"ok": ok, "skip": skip, "fail": fail, "total": len(codes)}

    # baostock 有失败时，用问财按日截面兜底最近 N 个交易日
    wencai_cfg = settings.get("wencai", {}) or {}
    fallback_on = bool(wencai_cfg.get("ohlcv_fallback", True)) and bool(
        wencai_cfg.get("enabled", True)
    )
    if fallback_on and fail > 0:
        days = int(wencai_cfg.get("ohlcv_days", wencai_cfg.get("daily_days", 5)))
        try:
            fb = update_daily_wencai_fallback(
                settings=settings,
                days=days,
                end=end,
            )
            stats["wencai_fallback"] = fb
            print(
                f"[daily] 问财兜底: 日={fb.get('days', 0)} "
                f"ok={fb.get('ok', 0)} fail={fb.get('fail', 0)} "
                f"rows={fb.get('rows', 0)} updated={fb.get('updated', 0)}"
            )
        except Exception as exc:  # noqa: BLE001
            stats["wencai_fallback_error"] = str(exc)
            print(f"[daily] 问财兜底失败: {exc}")

    return stats


def update_daily_wencai_fallback(
    *,
    settings: dict | None = None,
    days: int = 5,
    start: str | None = None,
    end: str | None = None,
    force: bool = False,
) -> dict[str, int]:
    """
    用问财按交易日拉取全市场前复权 OHLCV，合并进 daily。
    适合 baostock 不可用时的增量兜底（逐日截面，不做超长历史回填）。
    """
    settings = settings or load_settings()
    ensure_dirs(settings)
    wencai_cfg = settings.get("wencai", {}) or {}
    if not wencai_cfg.get("enabled", True):
        return {"ok": 0, "skip": 0, "fail": 0, "days": 0, "rows": 0, "updated": 0}

    daily_dir = Path(settings["storage"]["daily_path"])
    universe = str(wencai_cfg.get("universe", "沪深A股"))
    chunk_pause = float(wencai_cfg.get("chunk_pause", 1.0))
    max_retries = int(wencai_cfg.get("max_retries", 3))
    retry_pause = float(wencai_cfg.get("retry_pause", 2.0))

    if start is not None or end is not None:
        date_list = _trade_dates_between(settings, start, end)
    else:
        latest = _latest_calendar_date(settings)
        if latest is None:
            raise RuntimeError("无交易日历，请先运行 update-meta")
        cal_path = Path(settings["storage"]["meta_path"]) / "trade_calendar.parquet"
        cal = pd.read_parquet(cal_path)
        cal_dates = pd.to_datetime(cal["date"]).sort_values()
        past = cal_dates[cal_dates <= latest]
        date_list = [
            pd.Timestamp(d).normalize()
            for d in past.tail(max(int(days), 1)).tolist()
        ]

    if not date_list:
        return {"ok": 0, "skip": 0, "fail": 0, "days": 0, "rows": 0, "updated": 0}

    ok = skip = fail = rows = updated = 0
    errors: list[str] = []
    frames: list[pd.DataFrame] = []
    raw_dir = Path(settings["storage"]["raw_path"]) / "wencai" / "ohlcv"
    raw_dir.mkdir(parents=True, exist_ok=True)

    for day in tqdm(date_list, desc="问财OHLCV兜底", unit="日"):
        label = day.strftime("%Y%m%d")
        cache_path = raw_dir / f"{label}.parquet"
        try:
            if not force and cache_path.exists():
                long_df = pd.read_parquet(cache_path)
                skip += 1
            else:
                long_df = wencai_api.fetch_ohlcv_day(
                    day,
                    settings=settings,
                    universe=universe,
                    max_retries=max_retries,
                    retry_pause=retry_pause,
                )
                if long_df.empty or not long_df["close"].notna().any():
                    raise ValueError("问财 OHLCV 返回空表")
                long_df.to_parquet(cache_path, index=False)
                ok += 1
                time.sleep(chunk_pause)

            rows += len(long_df)
            frames.append(long_df)
        except Exception as exc:  # noqa: BLE001
            fail += 1
            errors.append(f"{label}: {exc}")
            time.sleep(chunk_pause)

    if frames:
        big = pd.concat(frames, ignore_index=True)
        mstats = apply_ohlcv_frames(daily_dir, big)
        updated = int(mstats.get("updated", 0)) + int(mstats.get("created", 0))


    if errors:
        log_dir = ROOT / "logs"
        log_dir.mkdir(exist_ok=True)
        stamp = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")
        (log_dir / f"ohlcv_wencai_errors_{stamp}.log").write_text(
            "\n".join(errors), encoding="utf-8"
        )

    return {
        "ok": ok,
        "skip": skip,
        "fail": fail,
        "days": len(date_list),
        "rows": rows,
        "updated": updated,
    }


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
