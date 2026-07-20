"""数据目录清理与全量构建辅助。"""

from __future__ import annotations

import shutil
from pathlib import Path

from .config import ROOT, ensure_dirs, load_settings


def clean_all_data(settings: dict | None = None, *, keep_logs: bool = False) -> dict[str, int]:
    """
    清空当前数据根目录下所有行情与问财缓存（保留 .gitkeep）。
    返回各目录删除的文件数。
    """
    settings = settings or load_settings()
    root = Path(settings["storage"]["root_path"])
    stats: dict[str, int] = {}

    targets = [
        root / "daily",
        root / "meta",
        root / "raw",
        root / "import",
    ]
    for path in targets:
        n = 0
        if path.exists():
            for item in path.rglob("*"):
                if item.is_file() and item.name != ".gitkeep":
                    item.unlink()
                    n += 1
            # 移除空子目录（保留顶层）
            for sub in sorted(path.rglob("*"), reverse=True):
                if sub.is_dir() and sub != path and not any(sub.iterdir()):
                    sub.rmdir()
        else:
            path.mkdir(parents=True, exist_ok=True)
        stats[path.name] = n

    if not keep_logs:
        # logs 始终在代码仓库下，不随外部数据根移动
        log_root = ROOT / "logs"
        if log_root.exists():
            n = 0
            for f in log_root.glob("*"):
                if f.is_file():
                    f.unlink()
                    n += 1
            stats["logs"] = n

    ensure_dirs(settings)
    return stats
