from __future__ import annotations

import time
from typing import Callable

import akshare as ak
import pandas as pd

from .storage import DAILY_COLUMNS, normalize_code


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


def fetch_stock_list(*, max_retries: int = 3, retry_pause: float = 2.0) -> pd.DataFrame:
    """获取全市场 A 股代码与名称。"""

    def _pull() -> pd.DataFrame:
        df = ak.stock_info_a_code_name()
        df = df.rename(columns={"code": "code", "name": "name"})
        df["code"] = df["code"].map(normalize_code)
        return df[["code", "name"]].drop_duplicates(subset=["code"]).sort_values("code")

    return _with_retry(_pull, max_retries=max_retries, retry_pause=retry_pause)


def fetch_trade_calendar(*, max_retries: int = 3, retry_pause: float = 2.0) -> pd.DataFrame:
    """获取沪市交易日历（可作为 A 股交易日参考）。"""

    def _pull() -> pd.DataFrame:
        df = ak.tool_trade_date_hist_sina()
        df = df.rename(columns={"trade_date": "date"})
        df["date"] = pd.to_datetime(df["date"]).dt.normalize()
        return df[["date"]].drop_duplicates().sort_values("date").reset_index(drop=True)

    return _with_retry(_pull, max_retries=max_retries, retry_pause=retry_pause)


def _market_symbol(code: str) -> str:
    """akshare 新浪/腾讯接口需要的市场前缀代码，如 sz000001。"""
    code = normalize_code(code)
    if code.startswith("6") or code.startswith("9"):
        return f"sh{code}"
    if code.startswith(("4", "8")) or code.startswith("92"):
        return f"bj{code}"
    return f"sz{code}"


def _finalize_daily(df: pd.DataFrame, code: str) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=DAILY_COLUMNS)
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"]).dt.normalize()
    out["code"] = normalize_code(code)
    if "pct_chg" not in out.columns or out["pct_chg"].isna().all():
        close = pd.to_numeric(out["close"], errors="coerce")
        out["pct_chg"] = close.pct_change() * 100
    for col in DAILY_COLUMNS:
        if col not in out.columns:
            out[col] = pd.NA
    return out[DAILY_COLUMNS].sort_values("date").reset_index(drop=True)


def fetch_daily_hist(
    code: str,
    start: str,
    end: str | None = None,
    *,
    max_retries: int = 3,
    retry_pause: float = 2.0,
) -> pd.DataFrame:
    """
    拉取个股前复权日线。
    start/end: YYYYMMDD
    优先新浪，失败再尝试东财 / 腾讯。
    """
    code = normalize_code(code)
    end = end or pd.Timestamp.today().strftime("%Y%m%d")
    symbol = _market_symbol(code)
    start_dash = pd.Timestamp(start).strftime("%Y-%m-%d")
    end_dash = pd.Timestamp(end).strftime("%Y-%m-%d")

    def _from_sina() -> pd.DataFrame:
        raw = ak.stock_zh_a_daily(
            symbol=symbol,
            start_date=start,
            end_date=end,
            adjust="qfq",
        )
        if raw is None or raw.empty:
            return pd.DataFrame(columns=DAILY_COLUMNS)
        df = raw.rename(
            columns={
                "date": "date",
                "open": "open",
                "high": "high",
                "low": "low",
                "close": "close",
                "volume": "volume",
                "amount": "amount",
                "turnover": "turnover",
            }
        )
        return _finalize_daily(df, code)

    def _from_eastmoney() -> pd.DataFrame:
        raw = ak.stock_zh_a_hist(
            symbol=code,
            period="daily",
            start_date=start,
            end_date=end,
            adjust="qfq",
        )
        if raw is None or raw.empty:
            return pd.DataFrame(columns=DAILY_COLUMNS)
        df = raw.rename(
            columns={
                "日期": "date",
                "股票代码": "code",
                "开盘": "open",
                "收盘": "close",
                "最高": "high",
                "最低": "low",
                "成交量": "volume",
                "成交额": "amount",
                "换手率": "turnover",
                "涨跌幅": "pct_chg",
            }
        )
        return _finalize_daily(df, code)

    def _from_tx() -> pd.DataFrame:
        raw = ak.stock_zh_a_hist_tx(
            symbol=symbol,
            start_date=start_dash,
            end_date=end_dash,
            adjust="qfq",
        )
        if raw is None or raw.empty:
            return pd.DataFrame(columns=DAILY_COLUMNS)
        # 腾讯接口 amount 实为成交量（手），无成交额/换手
        df = raw.rename(
            columns={
                "date": "date",
                "open": "open",
                "close": "close",
                "high": "high",
                "low": "low",
                "amount": "volume",
            }
        )
        return _finalize_daily(df, code)

    last_err: Exception | None = None
    for pull in (_from_sina, _from_eastmoney, _from_tx):
        try:
            df = _with_retry(
                pull, max_retries=max_retries, retry_pause=retry_pause
            )
            if not df.empty and df["close"].notna().any():
                return df
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            time.sleep(retry_pause)
    if last_err is not None:
        raise last_err
    return pd.DataFrame(columns=DAILY_COLUMNS)
