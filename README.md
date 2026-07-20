# a_share_data

A 股个股数据日常维护仓库：

- **日线**：baostock 前复权（`adjustflag=2`），含 baostock 可提供的全部交易字段
- **VOLAMOUNT（总笔数）**：同花顺问财（`thsdk.wencai_nlp`）按区间批量拉取，合并进个股 parquet

## 字段

`date, code, open, high, low, close, preclose, volume, amount, turnover, pct_chg, tradestatus, pe_ttm, pb_mrq, ps_ttm, pcf_ncf_ttm, is_st, volamount`

## 数据目录

数据**不进 Git**（体积大）。本机默认根目录见 `config/settings.yaml` 的 `storage.root`：

`E:/FangcloudV2/独角汇/二级市场相关/数据/A股数据`

也可被环境变量 `A_SHARE_DATA_ROOT` 覆盖。仅使用该目录，不要写入方寸云其它文件夹。

```
{root}/
  meta/
    stock_list.parquet      # 股票列表（沪深 A，不含北交所）
    trade_calendar.parquet  # 交易日历
  daily/
    000001.parquet          # 个股日线（一股一文件）
    ...
  raw/wencai/volamount/
    20260717.parquet        # 问财单日全市场总笔数横截面
```

## 在其他项目里调用

### 1）只读数据（推荐）

```bash
pip install "a-share-data @ git+https://github.com/dogcat142857-boop/a_share_data.git"
```

```python
import os
from a_share import load_daily, list_codes, load_volamount_snapshot

os.environ["A_SHARE_DATA_ROOT"] = r"E:\FangcloudV2\独角汇\二级市场相关\数据\A股数据"

df = load_daily("000001", start="2024-01-01")
codes = list_codes()
snap = load_volamount_snapshot("2024-07-16")
```

也可不设环境变量，直接传路径：

```python
from a_share import load_daily
df = load_daily("600519", root=r"E:\FangcloudV2\独角汇\二级市场相关\数据\A股数据")
```

### 2）把数据包走（给另一台机器）

```bash
python scripts/pack_data_release.py              # 打 meta + daily
python scripts/pack_data_release.py --include-raw
```

生成 `dist/a_share_data_YYYYMMDD.zip`，解压后设置：

```bash
set A_SHARE_DATA_ROOT=D:\path\to\data
```

### 3）本机抓取 / 日更

```bash
pip install -e ".[sync]"
# 或
pip install -r requirements.txt
```

## 结构

```
config/           # 配置与自选股（含 storage.root）
src/a_share/      # 可读 API + 抓取管道
scripts/          # 一键脚本 / 计划任务
# 数据目录见 storage.root / A_SHARE_DATA_ROOT（默认在方寸云 A股数据）
```

## 快速开始（维护端）

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

1. （可选）同花顺账号：`.env` 中 `THS_USERNAME` / `THS_PASSWORD`；不填则 thsdk 游客模式  
2. VOLAMOUNT 用 `thsdk.wencai_nlp` 按月区间一次拉全市场多日总笔数

```bash
python -m a_share.cli init
python scripts/update_meta.py

# 首次全量（推荐：清空 → baostock 日线 → 问财 volamount → 合并）
python scripts/initial_build.py --workers 8

# 或分步：仅重建日线
python scripts/rebuild_from_baostock.py --workers 8
python scripts/update_daily.py --force --workers 8

# 问财补 VOLAMOUNT 并合并进日线
python scripts/backfill_volamount.py --start 20100101

# 日常一键增量
python scripts/sync_all.py
```

## 每日增量

`sync_all.py` 会：

- 更新 meta（股票列表 / 交易日历）
- baostock 增量补日线（跳过已是最新交易日的股票）
- **baostock 失败时**：问财按日补最近 N 个交易日前复权 OHLCV（`wencai.ohlcv_fallback`）
- 问财补最近 5 个交易日 volamount 并合并

### 自动日更

**Windows**（工作日 16:00）：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\register_daily_task.ps1
```

计划任务名：`AShareDataDailySync`（工作日 16:00）。

**Linux**：

```bash
bash scripts/register_daily_cron.sh
```

### VOLAMOUNT 全量回填（thsdk 按月区间）

```bash
# 问句类似：沪深A股,2024年1月2日至2024年1月31日总笔数
python scripts/backfill_volamount.py --start 20100101
```

## 数据源

- [baostock](http://baostock.com/)：沪深 A 股前复权日线、估值/状态字段、股票列表、交易日历  
- [thsdk](https://pypi.org/project/thsdk/)：`wencai_nlp` 全市场区间总笔数（VOLAMOUNT）；日线 OHLCV 兜底  
- [AKShare](https://github.com/akfamily/akshare)：列表/日历的备用回退
