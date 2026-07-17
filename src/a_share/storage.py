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
    "volamount",  # 总笔数 / VOLAMOUNT（问财补全）
]


def daily_path(daily_dir: Path, code: str) -> Path:
    return daily_dir / f"{normalize_code(code)}.parquet"


def normalize_code(code: str) -> str:
    """统一为 6 位数字代码。兼容 sh.600000 / 000001.SZ / 600000。"""
    code = str(code).strip().upper()
    if code.startswith(("SH.", "SZ.", "BJ.")):
        code = code.split(".", 1)[1]
    elif "." in code:
        left, right = code.split(".", 1)
        code = left if left[:1].isdigit() else right
    digits = "".join(ch for ch in code if ch.isdigit())
    if digits:
        return digits.zfill(6)[-6:]
    return code.zfill(6)


def _ensure_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in DAILY_COLUMNS:
        if col not in out.columns:
            out[col] = pd.NA
    return out


def read_daily(daily_dir: Path, code: str) -> pd.DataFrame:
    path = daily_path(daily_dir, code)
    if not path.exists():
        return pd.DataFrame(columns=DAILY_COLUMNS)
    df = _ensure_columns(pd.read_parquet(path))
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    return df.sort_values("date").reset_index(drop=True)


def write_daily(daily_dir: Path, code: str, df: pd.DataFrame) -> Path:
    path = daily_path(daily_dir, code)
    daily_dir.mkdir(parents=True, exist_ok=True)
    out = _ensure_columns(df)
    if out.empty:
        out = pd.DataFrame(columns=DAILY_COLUMNS)
    else:
        out["date"] = pd.to_datetime(out["date"]).dt.normalize()
        out["code"] = normalize_code(code)
        out = (
            out[DAILY_COLUMNS]
            .drop_duplicates(subset=["date"], keep="last")
            .sort_values("date")
            .reset_index(drop=True)
        )
    out.to_parquet(path, index=False)
    return path


def _last_non_null(series: pd.Series):
    vals = series.dropna()
    if vals.empty:
        return pd.NA
    return vals.iloc[-1]


def merge_daily(existing: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
    """按 date 合并；同日同列取最后一条非空值（避免 OHLCV 更新冲掉 volamount）。"""
    frames = [f for f in (existing, new) if f is not None and not f.empty]
    if not frames:
        return pd.DataFrame(columns=DAILY_COLUMNS)
    base = _ensure_columns(pd.concat(frames, ignore_index=True))
    base["date"] = pd.to_datetime(base["date"]).dt.normalize()
    agg = {col: _last_non_null for col in DAILY_COLUMNS if col != "date"}
    return (
        base.groupby("date", as_index=False)
        .agg(agg)
        .sort_values("date")
        .reset_index(drop=True)
    )


def last_trade_date(df: pd.DataFrame) -> pd.Timestamp | None:
    if df.empty or "date" not in df.columns:
        return None
    return pd.to_datetime(df["date"]).max()


def apply_volamount_snapshot(
    daily_dir: Path,
    trade_date: pd.Timestamp,
    snapshot: pd.DataFrame,
) -> dict[str, int]:
    """
    将单日全市场 volamount 横截面写入各股 parquet。
    snapshot 需含 code, volamount。
    """
    trade_date = pd.Timestamp(trade_date).normalize()
    if snapshot.empty:
        return {"updated": 0, "created": 0}

    snap = snapshot.copy()
    snap["code"] = snap["code"].map(normalize_code)
    snap["volamount"] = pd.to_numeric(snap["volamount"], errors="coerce")
    snap = snap.dropna(subset=["code"]).drop_duplicates(subset=["code"], keep="last")
    snap["date"] = trade_date

    return apply_volamount_frames(daily_dir, snap)


def apply_volamount_frames(daily_dir: Path, frames: pd.DataFrame) -> dict[str, int]:
    """
    批量把多日 volamount（列 date/code/volamount）合并进个股日线。
    按股票一次读写，适合全量回填。
    """
    if frames is None or frames.empty:
        return {"updated": 0, "created": 0}

    data = frames.copy()
    data["code"] = data["code"].map(normalize_code)
    data["date"] = pd.to_datetime(data["date"]).dt.normalize()
    data["volamount"] = pd.to_numeric(data["volamount"], errors="coerce")
    data = (
        data.dropna(subset=["code", "date"])
        .drop_duplicates(subset=["code", "date"], keep="last")
        .sort_values(["code", "date"])
    )

    updated = created = 0
    daily_dir.mkdir(parents=True, exist_ok=True)

    for code, grp in data.groupby("code", sort=False):
        path = daily_path(daily_dir, code)
        patch = grp[["date", "code", "volamount"]].copy()
        patch["code"] = code
        if path.exists():
            existing = read_daily(daily_dir, code)
            merged = merge_daily(existing, patch)
            write_daily(daily_dir, code, merged)
            updated += 1
        else:
            write_daily(daily_dir, code, patch)
            created += 1

    return {"updated": updated, "created": created}
