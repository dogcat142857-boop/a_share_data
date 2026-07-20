from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SETTINGS = ROOT / "config" / "settings.yaml"
DEFAULT_ENV = ROOT / ".env"


def load_dotenv(path: Path | None = None) -> None:
    """简易 .env 加载（不覆盖已有环境变量）。"""
    env_path = path or DEFAULT_ENV
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = value


def load_settings(path: Path | None = None) -> dict[str, Any]:
    load_dotenv()
    settings_path = path or DEFAULT_SETTINGS
    with settings_path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    storage = data.setdefault("storage", {})
    root = ROOT / storage.get("root", "data")
    storage["root_path"] = root
    storage["daily_path"] = root / storage.get("daily_dir", "daily")
    storage["meta_path"] = root / storage.get("meta_dir", "meta")
    storage["raw_path"] = root / storage.get("raw_dir", "raw")
    return data


def ensure_dirs(settings: dict[str, Any]) -> None:
    for key in ("daily_path", "meta_path", "raw_path"):
        Path(settings["storage"][key]).mkdir(parents=True, exist_ok=True)
    raw = Path(settings["storage"]["raw_path"])
    (raw / "wencai" / "volamount").mkdir(parents=True, exist_ok=True)
    (raw / "wencai" / "volamount_chunks").mkdir(parents=True, exist_ok=True)
    (raw / "wencai" / "ohlcv").mkdir(parents=True, exist_ok=True)
