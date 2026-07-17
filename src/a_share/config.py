from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SETTINGS = ROOT / "config" / "settings.yaml"


def load_settings(path: Path | None = None) -> dict[str, Any]:
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
