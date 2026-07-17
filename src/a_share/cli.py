from __future__ import annotations

import sys
from pathlib import Path

import click

# 允许直接 python -m / scripts 调用时找到包
_SRC = Path(__file__).resolve().parents[1]
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from a_share.config import ensure_dirs, load_settings
from a_share.pipeline import resolve_universe, update_daily, update_meta, update_volamount
from a_share.storage import normalize_code, read_daily


@click.group()
@click.version_option(package_name=None, version="0.1.0")
def main() -> None:
    """A股个股数据日常维护 CLI。"""


@main.command("init")
def init_cmd() -> None:
    """创建数据目录。"""
    settings = load_settings()
    ensure_dirs(settings)
    click.echo(f"已就绪: {settings['storage']['root_path']}")


@main.command("update-meta")
def update_meta_cmd() -> None:
    """更新股票列表与交易日历。"""
    result = update_meta()
    click.echo(
        f"股票列表 {len(result['stock_list'])} 只，"
        f"交易日历 {len(result['trade_calendar'])} 天"
    )


@main.command("update-daily")
@click.option("--code", "-c", multiple=True, help="指定股票代码，可多次传入")
@click.option("--start", default=None, help="起始日期 YYYYMMDD（全量/强制时）")
@click.option("--end", default=None, help="结束日期 YYYYMMDD")
@click.option("--force", is_flag=True, help="忽略本地增量，按 start 重拉")
def update_daily_cmd(
    code: tuple[str, ...],
    start: str | None,
    end: str | None,
    force: bool,
) -> None:
    """增量更新个股日线（默认全市场或 watchlist）。"""
    codes = list(code) if code else None
    stats = update_daily(codes, start=start, end=end, force=force)
    click.echo(
        f"完成: 更新 {stats['ok']}，跳过 {stats['skip']}，"
        f"失败 {stats['fail']}，合计 {stats['total']}"
    )


@main.command("update-volamount")
@click.option("--start", default=None, help="起始交易日 YYYYMMDD")
@click.option("--end", default=None, help="结束交易日 YYYYMMDD")
@click.option("--days", type=int, default=None, help="最近 N 个交易日")
@click.option("--force", is_flag=True, help="忽略 raw 缓存重拉")
def update_volamount_cmd(
    start: str | None,
    end: str | None,
    days: int | None,
    force: bool,
) -> None:
    """问财补全全市场 VOLAMOUNT（总笔数）。"""
    stats = update_volamount(start=start, end=end, days=days, force=force)
    click.echo(
        f"完成: 拉取 {stats['ok']}，缓存跳过 {stats['skip']}，"
        f"失败 {stats['fail']}，合计 {stats['total']} 日，行数 {stats['rows']}"
    )


@main.command("show")
@click.argument("code")
@click.option("--tail", default=5, show_default=True, help="显示最近 N 行")
def show_cmd(code: str, tail: int) -> None:
    """查看本地某只股票日线末尾。"""
    settings = load_settings()
    df = read_daily(Path(settings["storage"]["daily_path"]), normalize_code(code))
    if df.empty:
        click.echo(f"本地无数据: {normalize_code(code)}")
        raise SystemExit(1)
    click.echo(df.tail(tail).to_string(index=False))


@main.command("universe")
def universe_cmd() -> None:
    """打印当前更新股票池规模。"""
    uni = resolve_universe()
    click.echo(f"股票池 {len(uni)} 只")
    click.echo(uni.head(10).to_string(index=False))


if __name__ == "__main__":
    main()
