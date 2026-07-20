"""对外可读 API：在其他项目中加载本仓库维护的 A 股个股数据。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .config import load_settings
from .storage import DAILY_COLUMNS, normalize_code, read_daily

ENV_DATA_ROOT = "A_SHARE_DATA_ROOT"


def resolve_data_root(root: str | Path | None = None) -> Path:
    """
    数据根目录解析顺序：
    1. 显式传入 root
    2. 环境变量 A_SHARE_DATA_ROOT
    3. config/settings.yaml 的 storage.root
    4. 仓库下 data/
    """
    if root is not None:
        return Path(root).expanduser().resolve()
    settings = load_settings()
    return Path(settings["storage"]["root_path"])


def daily_dir(root: str | Path | None = None) -> Path:
    return resolve_data_root(root) / "daily"


def meta_dir(root: str | Path | None = None) -> Path:
    return resolve_data_root(root) / "meta"


def volamount_raw_dir(root: str | Path | None = None) -> Path:
    return resolve_data_root(root) / "raw" / "wencai" / "volamount"


def list_codes(root: str | Path | None = None) -> list[str]:
    """列出本地已有日线文件的股票代码。"""
    path = daily_dir(root)
    if not path.exists():
        return []
    return sorted(p.stem for p in path.glob("*.parquet"))


def load_daily(
    code: str,
    *,
    root: str | Path | None = None,
    start: str | None = None,
    end: str | None = None,
    columns: list[str] | None = None,
) -> pd.DataFrame:
    """
    读取单只股票日线（含 volamount）。

    start/end: YYYYMMDD 或 YYYY-MM-DD，可选。
    """
    df = read_daily(daily_dir(root), normalize_code(code))
    if df.empty:
        return df if columns is None else df.reindex(columns=columns)

    if start:
        df = df[df["date"] >= pd.Timestamp(start).normalize()]
    if end:
        df = df[df["date"] <= pd.Timestamp(end).normalize()]
    if columns:
        keep = [c for c in columns if c in df.columns]
        df = df[keep]
    return df.reset_index(drop=True)


def load_many(
    codes: list[str],
    *,
    root: str | Path | None = None,
    start: str | None = None,
    end: str | None = None,
) -> pd.DataFrame:
    """批量读取多只股票，纵向拼接。"""
    frames = [
        load_daily(code, root=root, start=start, end=end) for code in codes
    ]
    frames = [f for f in frames if not f.empty]
    if not frames:
        return pd.DataFrame(columns=DAILY_COLUMNS)
    return pd.concat(frames, ignore_index=True).sort_values(["code", "date"])


def load_stock_list(root: str | Path | None = None) -> pd.DataFrame:
    path = meta_dir(root) / "stock_list.parquet"
    if not path.exists():
        return pd.DataFrame(columns=["code", "name"])
    df = pd.read_parquet(path)
    df["code"] = df["code"].map(normalize_code)
    return df


def load_trade_calendar(root: str | Path | None = None) -> pd.DataFrame:
    path = meta_dir(root) / "trade_calendar.parquet"
    if not path.exists():
        return pd.DataFrame(columns=["date"])
    df = pd.read_parquet(path)
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    return df.sort_values("date").reset_index(drop=True)


def load_volamount_snapshot(
    trade_date: str,
    *,
    root: str | Path | None = None,
) -> pd.DataFrame:
    """读取某日全市场 VOLAMOUNT 横截面（问财 raw）。"""
    ymd = pd.Timestamp(trade_date).strftime("%Y%m%d")
    path = volamount_raw_dir(root) / f"{ymd}.parquet"
    if not path.exists():
        return pd.DataFrame(columns=["date", "code", "volamount"])
    df = pd.read_parquet(path)
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    if "code" in df.columns:
        df["code"] = df["code"].map(normalize_code)
    return df
