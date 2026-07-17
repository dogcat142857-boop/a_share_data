from __future__ import annotations

from pathlib import Path

import pandas as pd

DAILY_COLUMNS = [
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


def daily_path(daily_dir: Path, code: str) -> Path:
    return daily_dir / f"{normalize_code(code)}.parquet"


def normalize_code(code: str) -> str:
    code = str(code).strip().upper()
    if "." in code:
        code = code.split(".")[0]
    return code.zfill(6)


def read_daily(daily_dir: Path, code: str) -> pd.DataFrame:
    path = daily_path(daily_dir, code)
    if not path.exists():
        return pd.DataFrame(columns=DAILY_COLUMNS)
    df = pd.read_parquet(path)
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    return df.sort_values("date").reset_index(drop=True)


def write_daily(daily_dir: Path, code: str, df: pd.DataFrame) -> Path:
    path = daily_path(daily_dir, code)
    daily_dir.mkdir(parents=True, exist_ok=True)
    out = df.copy()
    if out.empty:
        out = pd.DataFrame(columns=DAILY_COLUMNS)
    else:
        out["date"] = pd.to_datetime(out["date"]).dt.normalize()
        out["code"] = normalize_code(code)
        for col in DAILY_COLUMNS:
            if col not in out.columns:
                out[col] = pd.NA
        out = (
            out[DAILY_COLUMNS]
            .drop_duplicates(subset=["date"], keep="last")
            .sort_values("date")
            .reset_index(drop=True)
        )
    out.to_parquet(path, index=False)
    return path


def merge_daily(existing: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
    if existing.empty:
        base = new
    elif new.empty:
        base = existing
    else:
        base = pd.concat([existing, new], ignore_index=True)
    if base.empty:
        return pd.DataFrame(columns=DAILY_COLUMNS)
    base["date"] = pd.to_datetime(base["date"]).dt.normalize()
    return (
        base.drop_duplicates(subset=["date"], keep="last")
        .sort_values("date")
        .reset_index(drop=True)
    )


def last_trade_date(df: pd.DataFrame) -> pd.Timestamp | None:
    if df.empty or "date" not in df.columns:
        return None
    return pd.to_datetime(df["date"]).max()
