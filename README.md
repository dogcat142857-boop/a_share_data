# a_share_data

A 股个股数据日常维护仓库：拉取股票列表 / 交易日历，按股票增量更新前复权日线，本地以 Parquet 存储。

## 结构

```
config/           # 配置与自选股
data/
  meta/           # 股票列表、交易日历
  daily/          # 个股日线：{code}.parquet
  raw/            # 原始备份（可选）
src/a_share/      # 核心库
scripts/          # 一键脚本
```

## 快速开始

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
pip install -r requirements.txt
# 或可编辑安装（注册 a-share 命令）
pip install -e .
```

初始化目录并更新元数据：

```bash
python -m a_share.cli init
python scripts/update_meta.py
```

更新日线（默认全市场；也可改 `config/settings.yaml` 为自选股模式）：

```bash
# 日常一键：元数据 + 日线增量
python scripts/sync_all.py

# 只更新日线
python scripts/update_daily.py

# 指定个股
python scripts/update_daily.py -c 000001 -c 600519
```

查看本地数据：

```bash
python -m a_share.cli show 000001 --tail 10
```

## 配置

编辑 `config/settings.yaml`：

| 项 | 说明 |
| --- | --- |
| `universe.mode` | `all` 全市场，或 `watchlist` 自选 |
| `universe.watchlist` | 自选列表路径，默认 `config/watchlist.txt` |
| `fetch.default_start` | 无本地数据时的起始日 |
| `fetch.request_pause` | 请求间隔，降低限流风险 |

自选股示例（`config/watchlist.txt`）：

```
000001
600519
300750
```

## 数据字段

日线 Parquet 列：`date, code, open, high, low, close, volume, amount, turnover, pct_chg`（前复权）。

> 大数据文件默认不进 Git（见 `.gitignore`）。建议本地维护，或用网盘 / 对象存储备份 `data/`。

## 数据源

当前使用 [AKShare](https://github.com/akfamily/akshare) 免费接口，无需 token。接口偶发失败时会自动重试，失败明细写入 `logs/`。
