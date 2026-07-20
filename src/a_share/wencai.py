"""问财 thsdk.wencai_nlp：VOLAMOUNT（总笔数）+ 日线 OHLCV 兜底。"""

from __future__ import annotations

import os
import re
import time
from typing import Any

import pandas as pd

from .storage import normalize_code

VOL_COL_RE = re.compile(
    r"^(?:总笔数|成交笔数|成交次数|VOLAMOUNT)\[(\d{8})\]$",
    re.IGNORECASE,
)

# 例：开盘价:前复权[20260720] / 成交量[20260720] / 涨跌幅:前复权[20260720]
OHLCV_FIELD_RE = re.compile(
    r"^(开盘价|最高价|最低价|收盘价|成交量|成交额|换手率|涨跌幅)"
    r"(?::(?:前复权|不复权|后复权))?"
    r"\[(\d{8})\]$"
)

OHLCV_FIELD_MAP = {
    "开盘价": "open",
    "最高价": "high",
    "最低价": "low",
    "收盘价": "close",
    "成交量": "volume",
    "成交额": "amount",
    "换手率": "turnover",
    "涨跌幅": "pct_chg",
}

OHLCV_METRICS = (
    "前复权开盘价,前复权最高价,前复权最低价,前复权收盘价,"
    "成交量,成交额,换手率,涨跌幅"
)


def _ths_client(settings: dict | None = None):
    """创建 THS 客户端；可用环境变量配置账号。"""
    from thsdk import THS

    settings = settings or {}
    cfg = settings.get("wencai", {}) or {}
    username = (
        os.environ.get("THS_USERNAME", "").strip()
        or str(cfg.get("username") or "").strip()
    )
    password = (
        os.environ.get("THS_PASSWORD", "").strip()
        or str(cfg.get("password") or "").strip()
    )
    mac = os.environ.get("THS_MAC", "").strip() or str(cfg.get("mac") or "").strip()
    if username and password:
        opts: dict[str, Any] = {"username": username, "password": password}
        if mac:
            opts["mac"] = mac
        return THS(opts)
    return THS()


def _format_cn_date(ts: pd.Timestamp) -> str:
    ts = pd.Timestamp(ts)
    return f"{ts.year}年{ts.month}月{ts.day}日"


def build_range_query(
    start: str | pd.Timestamp,
    end: str | pd.Timestamp,
    *,
    universe: str = "沪深A股",
    metric: str = "总笔数",
) -> str:
    """例：沪深A股,2024年1月2日至2024年1月31日总笔数"""
    s = _format_cn_date(start)
    e = _format_cn_date(end)
    if pd.Timestamp(start).normalize() == pd.Timestamp(end).normalize():
        return f"{universe},{s}{metric}"
    return f"{universe},{s}至{e}{metric}"


def _response_to_frame(resp: Any) -> pd.DataFrame:
    if resp is None:
        raise ValueError("thsdk 返回为空")
    ok = getattr(resp, "success", True)
    if ok is False:
        raise RuntimeError(f"thsdk 问财失败: {getattr(resp, 'error', '')}")

    df = getattr(resp, "df", None)
    if isinstance(df, pd.DataFrame) and not df.empty:
        return df

    data = getattr(resp, "data", None)
    if isinstance(data, list) and data:
        return pd.DataFrame(data)
    if isinstance(data, pd.DataFrame) and not data.empty:
        return data
    raise ValueError("thsdk 问财无表格数据")


def _pick_code_column(columns: list[str]) -> str:
    for pattern in (r"^股票代码$", r"^code$", r"代码"):
        rx = re.compile(pattern, re.IGNORECASE)
        for col in columns:
            if rx.search(str(col)):
                return col
    raise ValueError(f"无法识别股票代码列: {columns[:20]}")


def wide_volamount_to_long(raw: pd.DataFrame) -> pd.DataFrame:
    """
    宽表 总笔数[YYYYMMDD] -> 长表 date/code/volamount。
    """
    if raw is None or raw.empty:
        return pd.DataFrame(columns=["date", "code", "volamount"])

    cols = [str(c) for c in raw.columns]
    code_col = _pick_code_column(cols)
    vol_cols: list[tuple[str, pd.Timestamp]] = []
    for col in cols:
        m = VOL_COL_RE.match(str(col).strip())
        if m:
            vol_cols.append((col, pd.Timestamp(m.group(1)).normalize()))
    if not vol_cols:
        raise ValueError(
            "未找到总笔数[YYYYMMDD] 列，"
            f"实际列: {cols[:20]}{'...' if len(cols) > 20 else ''}"
        )

    base = raw[[code_col] + [c for c, _ in vol_cols]].copy()
    base = base.rename(columns={code_col: "code"})
    base["code"] = base["code"].map(normalize_code)
    long = base.melt(id_vars=["code"], var_name="col", value_name="volamount")
    col_to_date = {c: d for c, d in vol_cols}
    long["date"] = long["col"].map(col_to_date)
    long["volamount"] = pd.to_numeric(long["volamount"], errors="coerce")
    long = (
        long.dropna(subset=["code", "date"])
        .drop(columns=["col"])
        .drop_duplicates(subset=["code", "date"], keep="last")
        .sort_values(["date", "code"])
        .reset_index(drop=True)
    )
    return long[["date", "code", "volamount"]]


def fetch_volamount_range(
    start: str | pd.Timestamp,
    end: str | pd.Timestamp,
    *,
    settings: dict | None = None,
    universe: str = "沪深A股",
    metric: str = "总笔数",
    max_retries: int = 3,
    retry_pause: float = 2.0,
) -> pd.DataFrame:
    """
    一次拉取日期区间内全市场总笔数，返回长表 date/code/volamount。
    """
    start_ts = pd.Timestamp(start).normalize()
    end_ts = pd.Timestamp(end).normalize()
    if end_ts < start_ts:
        start_ts, end_ts = end_ts, start_ts

    query = build_range_query(start_ts, end_ts, universe=universe, metric=metric)
    last_err: Exception | None = None

    for attempt in range(1, max_retries + 1):
        try:
            with _ths_client(settings) as ths:
                resp = ths.wencai_nlp(query)
            wide = _response_to_frame(resp)
            return wide_volamount_to_long(wide)
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            if attempt < max_retries:
                time.sleep(retry_pause * attempt)

    assert last_err is not None
    raise last_err


# ---- 兼容旧单日接口（内部转成区间查询）----

def fetch_wencai_volamount(
    trade_date: str | pd.Timestamp,
    *,
    cookie: str | None = None,  # noqa: ARG001 - 兼容旧签名，thsdk 无需 cookie
    settings: dict | None = None,
    query_template: str | None = None,  # noqa: ARG001
    loop: bool = True,  # noqa: ARG001
    page_sleep: float = 1.0,  # noqa: ARG001
    max_retries: int = 3,
    retry_pause: float = 2.0,
) -> pd.DataFrame:
    """单日全市场总笔数（走 thsdk 区间查询）。"""
    ts = pd.Timestamp(trade_date).normalize()
    return fetch_volamount_range(
        ts,
        ts,
        settings=settings,
        max_retries=max_retries,
        retry_pause=retry_pause,
    )


def resolve_wencai_cookie(settings: dict | None = None) -> str:
    """兼容旧代码：thsdk 游客模式可不需要 cookie，返回空串。"""
    settings = settings or {}
    wencai = settings.get("wencai", {})
    env_name = wencai.get("cookie_env", "WENCAI_COOKIE")
    return os.environ.get(env_name, "").strip() or str(wencai.get("cookie") or "").strip()


def build_ohlcv_day_query(
    trade_date: str | pd.Timestamp,
    *,
    universe: str = "沪深A股",
    metrics: str = OHLCV_METRICS,
) -> str:
    """例：沪深A股,2026年7月20日前复权开盘价,前复权最高价,..."""
    day = _format_cn_date(trade_date)
    return f"{universe},{day}{metrics}"


def wide_ohlcv_to_long(raw: pd.DataFrame) -> pd.DataFrame:
    """
    问财单日宽表 -> 长表 date/code/open/high/low/close/volume/amount/turnover/pct_chg。
    换手率按百分数转成比例（与本地 baostock 字段一致）。
    """
    if raw is None or raw.empty:
        return pd.DataFrame(
            columns=[
                "date",
                "code",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "amount",
                "turnover",
                "pct_chg",
            ]
        )

    cols = [str(c) for c in raw.columns]
    code_col = _pick_code_column(cols)

    # field -> (original_col, date)
    picked: dict[str, tuple[str, pd.Timestamp]] = {}
    for col in cols:
        m = OHLCV_FIELD_RE.match(str(col).strip())
        if not m:
            continue
        cn_name, ymd = m.group(1), m.group(2)
        field = OHLCV_FIELD_MAP.get(cn_name)
        if not field:
            continue
        # 同字段多列时优先保留先匹配到的（查询已指定前复权）
        picked.setdefault(field, (col, pd.Timestamp(ymd).normalize()))

    need = ("open", "high", "low", "close")
    if not all(k in picked for k in need):
        raise ValueError(
            "未找到完整 OHLCV 列（开高低收），"
            f"实际列: {cols[:20]}{'...' if len(cols) > 20 else ''}"
        )

    dates = {d for _, d in picked.values()}
    if len(dates) != 1:
        raise ValueError(f"OHLCV 列日期不一致: {sorted(str(d.date()) for d in dates)}")
    trade_date = next(iter(dates))

    out = pd.DataFrame(
        {
            "code": raw[code_col].map(normalize_code),
            "date": trade_date,
        }
    )
    for field, (col, _) in picked.items():
        out[field] = pd.to_numeric(raw[col], errors="coerce")

    # 问财换手率一般为百分数
    if "turnover" in out.columns:
        out["turnover"] = out["turnover"] / 100.0

    out = out.dropna(subset=["code", "close"])
    out = out.drop_duplicates(subset=["code", "date"], keep="last")
    cols_out = [
        "date",
        "code",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "turnover",
        "pct_chg",
    ]
    for c in cols_out:
        if c not in out.columns:
            out[c] = pd.NA
    return out[cols_out].reset_index(drop=True)


def fetch_ohlcv_day(
    trade_date: str | pd.Timestamp,
    *,
    settings: dict | None = None,
    universe: str = "沪深A股",
    metrics: str = OHLCV_METRICS,
    max_retries: int = 3,
    retry_pause: float = 2.0,
) -> pd.DataFrame:
    """拉取单日全市场前复权 OHLCV 截面。"""
    ts = pd.Timestamp(trade_date).normalize()
    query = build_ohlcv_day_query(ts, universe=universe, metrics=metrics)
    last_err: Exception | None = None

    for attempt in range(1, max_retries + 1):
        try:
            with _ths_client(settings) as ths:
                resp = ths.wencai_nlp(query)
            wide = _response_to_frame(resp)
            return wide_ohlcv_to_long(wide)
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            if attempt < max_retries:
                time.sleep(retry_pause * attempt)

    assert last_err is not None
    raise last_err
