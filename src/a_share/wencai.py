from __future__ import annotations

import os
import re
import time
from typing import Callable

import pandas as pd

from .storage import normalize_code


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
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            if attempt < max_retries:
                time.sleep(retry_pause * attempt)
    assert last_err is not None
    raise last_err


def resolve_wencai_cookie(settings: dict | None = None) -> str:
    """优先环境变量，其次 settings.wencai.cookie。"""
    settings = settings or {}
    wencai = settings.get("wencai", {})
    env_name = wencai.get("cookie_env", "WENCAI_COOKIE")
    cookie = os.environ.get(env_name, "").strip()
    if cookie:
        return cookie
    cookie = str(wencai.get("cookie") or "").strip()
    if cookie:
        return cookie
    raise RuntimeError(
        f"缺少问财 Cookie：请在环境变量 {env_name} 或 .env 中配置，"
        "浏览器登录 iwencai.com 后从请求头复制 Cookie"
    )


def _format_query(trade_date: str | pd.Timestamp, template: str) -> str:
    ts = pd.Timestamp(str(trade_date))
    y, m, d = ts.year, ts.month, ts.day
    ymd = ts.strftime("%Y%m%d")
    ymd_dash = ts.strftime("%Y-%m-%d")
    return (
        template.replace("{Y}", str(y))
        .replace("{m}", str(m))
        .replace("{d}", str(d))
        .replace("{YYYYMMDD}", ymd)
        .replace("{YYYY-MM-DD}", ymd_dash)
    )


def _pick_column(columns: list[str], patterns: list[str]) -> str | None:
    for pattern in patterns:
        rx = re.compile(pattern, re.IGNORECASE)
        for col in columns:
            if rx.search(str(col)):
                return col
    return None


def _normalize_volamount_frame(
    raw: pd.DataFrame, trade_date: pd.Timestamp
) -> pd.DataFrame:
    if raw is None or not isinstance(raw, pd.DataFrame) or raw.empty:
        return pd.DataFrame(columns=["date", "code", "volamount"])

    cols = [str(c) for c in raw.columns]
    code_col = _pick_column(
        cols,
        [r"^股票代码$", r"^code$", r"代码", r"股票代码"],
    )
    vol_col = _pick_column(
        cols,
        [
            r"成交笔数",
            r"总笔数",
            r"成交次数",
            r"VOLAMOUNT",
            r"volamount",
            r"笔数",
        ],
    )
    if code_col is None or vol_col is None:
        raise ValueError(
            "问财返回列无法识别 code/volamount，"
            f"实际列: {cols[:20]}{'...' if len(cols) > 20 else ''}"
        )

    out = pd.DataFrame(
        {
            "date": pd.Timestamp(trade_date).normalize(),
            "code": raw[code_col].map(normalize_code),
            "volamount": pd.to_numeric(raw[vol_col], errors="coerce"),
        }
    )
    out = out.dropna(subset=["code"]).drop_duplicates(subset=["code"], keep="last")
    return out.reset_index(drop=True)


def fetch_wencai_volamount(
    trade_date: str | pd.Timestamp,
    *,
    cookie: str,
    query_template: str = "{Y}年{m}月{d}日A股成交笔数",
    loop: bool = True,
    page_sleep: float = 1.0,
    max_retries: int = 3,
    retry_pause: float = 2.0,
) -> pd.DataFrame:
    """
    按交易日拉取全市场成交笔数（VOLAMOUNT / 总笔数）。
    返回列: date, code, volamount
    """
    import pywencai  # 延迟导入，避免无 Node/cookie 时拖垮其他命令

    ts = pd.Timestamp(str(trade_date)).normalize()
    query = _format_query(ts, query_template)

    def _pull() -> pd.DataFrame:
        raw = pywencai.get(
            query=query,
            query_type="stock",
            loop=loop,
            sleep=page_sleep,
            cookie=cookie,
            retry=max_retries,
        )
        if isinstance(raw, dict):
            # 详情类返回；尝试取 table
            for key in ("table", "data", "result"):
                if key in raw and isinstance(raw[key], pd.DataFrame):
                    raw = raw[key]
                    break
            else:
                raise ValueError(f"问财返回非表格数据: keys={list(raw.keys())}")
        return _normalize_volamount_frame(raw, ts)

    return _with_retry(_pull, max_retries=max_retries, retry_pause=retry_pause)
