# a_share_data

A 股个股数据日常维护仓库：拉取股票列表 / 交易日历，按股票增量更新前复权日线，并用问财补全全市场 **VOLAMOUNT（总笔数）**，本地以 Parquet 存储。

## 结构

```
config/           # 配置与自选股
data/
  meta/           # 股票列表、交易日历
  daily/          # 个股日线：{code}.parquet
  raw/wencai/     # 问财横截面原始备份
src/a_share/      # 核心库
scripts/          # 一键脚本 / 计划任务
```

## 快速开始

```bash
python -m venv .venv
# Windows（务必用项目虚拟环境，避免与 Anaconda 全局包冲突）
.venv\Scripts\activate
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

依赖说明：

1. **Node.js v16+**（问财 `pywencai` 执行 JS 必需）
2. **问财 Cookie**：复制 `.env.example` 为 `.env`，填入 `WENCAI_COOKIE=...`  
   （浏览器登录 [问财](https://www.iwencai.com) → DevTools → Network → 请求头 Cookie）

初始化：

```bash
python -m a_share.cli init
python scripts/update_meta.py
```

## 日常更新

```bash
# 一键：元数据 + 日线 OHLCV + VOLAMOUNT
python scripts/sync_all.py

# 仅 OHLCV
python scripts/update_daily.py

# 仅 VOLAMOUNT（默认最近 1 个交易日；可回填）
python scripts/update_volamount.py
python scripts/update_volamount.py --days 5
python scripts/update_volamount.py --start 20240102 --end 20240110
```

### 自动每日更新（Windows）

```powershell
powershell -ExecutionPolicy Bypass -File scripts\register_daily_task.ps1
```

会注册计划任务 `AShareDataDailySync`：工作日 **16:00** 执行 `scripts/run_daily_sync.ps1`（自动加载 `.env`）。

## 配置

编辑 `config/settings.yaml`：

| 项 | 说明 |
| --- | --- |
| `universe.mode` | `all` 全市场，或 `watchlist` 自选 |
| `wencai.enabled` | 是否启用问财 VOLAMOUNT |
| `wencai.daily_days` | `sync_all` 每次补最近 N 个交易日 |
| `wencai.query_template` | 问句模板，默认 `{Y}年{m}月{d}日A股成交笔数` |

## 数据字段

日线列：`date, code, open, high, low, close, volume, amount, turnover, pct_chg, volamount`  

- OHLCV 等来自 AKShare（前复权）  
- `volamount` 来自问财（成交笔数 / 总笔数）  
- 原始横截面备份：`data/raw/wencai/volamount/{YYYYMMDD}.parquet`

> 大数据文件默认不进 Git。Cookie 仅放 `.env`，勿提交。

## 数据源

- [AKShare](https://github.com/akfamily/akshare)：列表、日历、日线  
- [pywencai](https://github.com/zsrl/pywencai)：全市场 VOLAMOUNT（需 Cookie，请低频使用）
