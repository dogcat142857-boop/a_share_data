"""行情抓取：日线用 baostock；股票列表/交易日历优先 baostock，失败再回退 akshare。"""

from __future__ import annotations

import time
from typing import Callable

import pandas as pd

from .storage import DAILY_COLUMNS, normalize_code

# baostock 日线交易字段（前复权 adjustflag=2）
BS_DAILY_FIELDS = (
    "date,open,high,low,close,preclose,volume,amount,"
    "turn,tradestatus,pctChg,peTTM,pbMRQ,psTTM,pcfNcfTTM,isST"
)


def _with_retry(
    fn: Callable[[], pd.DataFrame],
    *,
    max_retries: int = 3,
    retry_pause: float = 2.0,
) -> pd.DataFrame:
    last_err: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - 数据源偶发失败，统一重试
            last_err = exc
            if attempt < max_retries:
                time.sleep(retry_pause * attempt)
    assert last_err is not None
    raise last_err


def to_baostock_code(code: str) -> str:
    """600000 -> sh.600000；000001 -> sz.000001。不含北交所。"""
    code = normalize_code(code)
    if code.startswith(("4", "8")) or code.startswith("92"):
        raise ValueError(f"不支持北交所代码: {code}")
    if code.startswith(("5", "6", "9")):
        return f"sh.{code}"
    return f"sz.{code}"


def _is_hs_a_share(bs_code: str) -> bool:
    """沪深 A 股：主板/创业板/科创板，排除指数、基金、北交所。"""
    code = str(bs_code).strip().lower()
    if code.startswith("sh.6"):
        return True
    if code.startswith("sz.0") or code.startswith("sz.3"):
        return True
    return False


def _f(x) -> float:
    if x in ("", None):
        return float("nan")
    try:
        return float(x)
    except (TypeError, ValueError):
        return float("nan")


def _finalize_daily(df: pd.DataFrame, code: str) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=DAILY_COLUMNS)
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"]).dt.normalize()
    out["code"] = normalize_code(code)
    for col in ("open", "high", "low", "close", "volume", "amount", "turnover", "pct_chg"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    if "pct_chg" not in out.columns or out["pct_chg"].isna().all():
        close = pd.to_numeric(out["close"], errors="coerce")
        out["pct_chg"] = close.pct_change() * 100
    for col in DAILY_COLUMNS:
        if col not in out.columns:
            out[col] = pd.NA
    return out[DAILY_COLUMNS].sort_values("date").reset_index(drop=True)


def fetch_stock_list(*, max_retries: int = 3, retry_pause: float = 2.0) -> pd.DataFrame:
    """获取沪深 A 股代码与名称（不含北交所）。"""

    def _from_baostock() -> pd.DataFrame:
        import baostock as bs

        lg = bs.login()
        if lg.error_code != "0":
            raise RuntimeError(f"baostock login failed: {lg.error_msg}")
        try:
            rs = bs.query_stock_basic()
            if rs.error_code != "0":
                raise RuntimeError(f"query_stock_basic: {rs.error_msg}")
            rows: list[dict] = []
            while rs.error_code == "0" and rs.next():
                raw = rs.get_row_data()
                # code, code_name, ipoDate, outDate, type, status
                bs_code, name, _ipo, _out, typ, status = raw[:6]
                if typ != "1" or status != "1":
                    continue
                if not _is_hs_a_share(bs_code):
                    continue
                rows.append({"code": normalize_code(bs_code), "name": name})
            df = pd.DataFrame(rows)
            if df.empty:
                raise RuntimeError("baostock 股票列表为空")
            return (
                df.drop_duplicates(subset=["code"])
                .sort_values("code")
                .reset_index(drop=True)
            )
        finally:
            bs.logout()

    def _from_akshare() -> pd.DataFrame:
        import akshare as ak

        df = ak.stock_info_a_code_name()
        df = df.rename(columns={"code": "code", "name": "name"})
        df["code"] = df["code"].map(normalize_code)
        # 排除北交所
        df = df[~df["code"].str.startswith(("4", "8"))]
        df = df[~df["code"].str.startswith("92")]
        return (
            df[["code", "name"]]
            .drop_duplicates(subset=["code"])
            .sort_values("code")
            .reset_index(drop=True)
        )

    last_err: Exception | None = None
    for pull in (_from_baostock, _from_akshare):
        try:
            return _with_retry(pull, max_retries=max_retries, retry_pause=retry_pause)
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            time.sleep(retry_pause)
    assert last_err is not None
    raise last_err


def fetch_trade_calendar(*, max_retries: int = 3, retry_pause: float = 2.0) -> pd.DataFrame:
    """获取 A 股交易日历。"""

    def _from_baostock() -> pd.DataFrame:
        import baostock as bs

        lg = bs.login()
        if lg.error_code != "0":
            raise RuntimeError(f"baostock login failed: {lg.error_msg}")
        try:
            # 按年分段拉取，避免长连接中途断开导致日历残缺
            start_year = 1990
            end_year = int(pd.Timestamp.today().year)
            dates: list[pd.Timestamp] = []
            for year in range(start_year, end_year + 1):
                y_start = f"{year}-01-01"
                y_end = f"{year}-12-31"
                rs = bs.query_trade_dates(start_date=y_start, end_date=y_end)
                if rs.error_code != "0":
                    raise RuntimeError(f"query_trade_dates {year}: {rs.error_msg}")
                while rs.error_code == "0" and rs.next():
                    d, flag = rs.get_row_data()[:2]
                    if str(flag) == "1":
                        dates.append(pd.Timestamp(d).normalize())
            if len(dates) < 1000:
                raise RuntimeError(f"baostock 交易日历过短: {len(dates)}")
            return (
                pd.DataFrame({"date": dates})
                .drop_duplicates()
                .sort_values("date")
                .reset_index(drop=True)
            )
        finally:
            try:
                bs.logout()
            except Exception:  # noqa: BLE001
                pass

    def _from_akshare() -> pd.DataFrame:
        import akshare as ak

        df = ak.tool_trade_date_hist_sina()
        df = df.rename(columns={"trade_date": "date"})
        df["date"] = pd.to_datetime(df["date"]).dt.normalize()
        return df[["date"]].drop_duplicates().sort_values("date").reset_index(drop=True)

    last_err: Exception | None = None
    for pull in (_from_baostock, _from_akshare):
        try:
            return _with_retry(pull, max_retries=max_retries, retry_pause=retry_pause)
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            time.sleep(retry_pause)
    assert last_err is not None
    raise last_err


def fetch_daily_hist(
    code: str,
    start: str,
    end: str | None = None,
    *,
    max_retries: int = 3,
    retry_pause: float = 2.0,
    manage_login: bool = True,
) -> pd.DataFrame:
    """
    拉取个股前复权日线（baostock adjustflag=2）。
    start/end: YYYYMMDD 或 YYYY-MM-DD
    manage_login=False 时假定调用方已 login（便于同进程批量）。
    """
    code = normalize_code(code)
    end = end or pd.Timestamp.today().strftime("%Y%m%d")
    start_dash = pd.Timestamp(start).strftime("%Y-%m-%d")
    end_dash = pd.Timestamp(end).strftime("%Y-%m-%d")
    bs_code = to_baostock_code(code)

    def _pull() -> pd.DataFrame:
        import baostock as bs

        if manage_login:
            lg = bs.login()
            if lg.error_code != "0":
                raise RuntimeError(f"baostock login failed: {lg.error_msg}")
        try:
            rs = bs.query_history_k_data_plus(
                bs_code,
                BS_DAILY_FIELDS,
                start_date=start_dash,
                end_date=end_dash,
                frequency="d",
                adjustflag="2",
            )
            if rs.error_code != "0":
                raise RuntimeError(f"{bs_code}: {rs.error_msg}")
            rows: list[dict] = []
            while rs.error_code == "0" and rs.next():
                (
                    date,
                    open_,
                    high,
                    low,
                    close,
                    _preclose,
                    volume,
                    amount,
                    turn,
                    _tradestatus,
                    pct_chg,
                    *_rest,
                ) = rs.get_row_data()
                if not close:
                    continue
                rows.append(
                    {
                        "date": date,
                        "open": _f(open_),
                        "high": _f(high),
                        "low": _f(low),
                        "close": _f(close),
                        "volume": _f(volume) if volume not in ("", None) else 0.0,
                        "amount": _f(amount) if amount not in ("", None) else 0.0,
                        "turnover": _f(turn),
                        "pct_chg": _f(pct_chg),
                    }
                )
            return _finalize_daily(pd.DataFrame(rows), code)
        finally:
            if manage_login:
                try:
                    bs.logout()
                except Exception:  # noqa: BLE001
                    pass

    return _with_retry(_pull, max_retries=max_retries, retry_pause=retry_pause)


def _worker_login() -> None:
    """ProcessPool 子进程初始化：错峰登录，复用会话。"""
    import atexit
    import os
    import random

    import baostock as bs

    # 错峰，避免同时 login 触发 baostock 用户数限制
    time.sleep(random.uniform(0.2, 2.5) + (os.getpid() % 7) * 0.15)
    last_err = "unknown"
    for attempt in range(1, 6):
        lg = bs.login()
        if lg.error_code == "0":
            break
        last_err = lg.error_msg
        time.sleep(1.5 * attempt + random.uniform(0, 1))
    else:
        raise RuntimeError(f"baostock worker login failed: {last_err}")

    def _logout() -> None:
        try:
            bs.logout()
        except Exception:  # noqa: BLE001
            pass

    atexit.register(_logout)


def fetch_daily_worker(
    payload: tuple[str, str, str, int, float],
) -> tuple[str, pd.DataFrame | None, str | None]:
    """
    多进程入口（需配合 ProcessPoolExecutor initializer=_worker_login）。
    payload = (code, start_YYYYMMDD, end_YYYYMMDD, max_retries, retry_pause)
    返回 (code, df|None, error|None)
    """
    code, start, end, max_retries, retry_pause = payload
    try:
        df = fetch_daily_hist(
            code,
            start,
            end,
            max_retries=max_retries,
            retry_pause=retry_pause,
            manage_login=False,
        )
        if df.empty or not df["close"].notna().any():
            return code, None, "empty or no close"
        return code, df, None
    except Exception as exc:  # noqa: BLE001
        # 会话偶发失效时，退回单次独立 login
        try:
            df = fetch_daily_hist(
                code,
                start,
                end,
                max_retries=max_retries,
                retry_pause=retry_pause,
                manage_login=True,
            )
            return code, df, None
        except Exception as exc2:  # noqa: BLE001
            return code, None, f"{exc} | fallback: {exc2}"
