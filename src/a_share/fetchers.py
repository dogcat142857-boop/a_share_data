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
    """
    code = normalize_code(code)
    end = end or pd.Timestamp.today().strftime("%Y%m%d")

    def _pull() -> pd.DataFrame:
        raw = ak.stock_zh_a_hist(
            symbol=code,
            period="daily",
            start_date=start,
            end_date=end,
            adjust="qfq",
        )
        if raw is None or raw.empty:
            return pd.DataFrame(columns=DAILY_COLUMNS)

        rename = {
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
        df = raw.rename(columns=rename)
        df["date"] = pd.to_datetime(df["date"]).dt.normalize()
        df["code"] = code
        for col in DAILY_COLUMNS:
            if col not in df.columns:
                df[col] = pd.NA
        return df[DAILY_COLUMNS].sort_values("date").reset_index(drop=True)

    return _with_retry(_pull, max_retries=max_retries, retry_pause=retry_pause)
