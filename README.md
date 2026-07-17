# a_share_data

A 股个股数据日常维护仓库：

- **日线 OHLCV**：baostock 前复权（`adjustflag=2`）
- **VOLAMOUNT（总笔数）**：同花顺问财（`thsdk.wencai_nlp`）按区间批量拉取，合并进个股日线

## 数据存在哪

默认都在仓库下的 `data/`（**不进 Git**，体积大，本地/网盘维护）：

```
data/
  meta/
    stock_list.parquet      # 股票列表（沪深 A，不含北交所）
    trade_calendar.parquet  # 交易日历
  daily/
    000001.parquet          # 个股日线（一股一文件）
    ...
  raw/wencai/volamount/
    20260717.parquet        # 问财单日全市场总笔数横截面
```

日线字段：`date, code, open, high, low, close, volume, amount, turnover, pct_chg, volamount`

## 在其他项目里调用

### 1）只读数据（推荐）

```bash
pip install "a-share-data @ git+https://github.com/dogcat142857-boop/a_share_data.git"
```

```python
import os
from a_share import load_daily, list_codes, load_volamount_snapshot

os.environ["A_SHARE_DATA_ROOT"] = r"C:\Users\UnicornSelected-06\a_share_data\data"

df = load_daily("000001", start="2024-01-01")
codes = list_codes()
snap = load_volamount_snapshot("2024-07-16")
```

也可不设环境变量，直接传路径：

```python
from a_share import load_daily
df = load_daily("600519", root=r"D:\datasets\a_share_data\data")
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
config/           # 配置与自选股
data/             # 本地数据（见上）
src/a_share/      # 可读 API + 抓取管道
scripts/          # 一键脚本 / 计划任务
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
# 全量重建（清空 daily → baostock 重拉 → 合并已有 volamount）
python scripts/rebuild_from_baostock.py --workers 8
# 或增量/全量日线
python scripts/update_daily.py --force --workers 8
# 问财补 VOLAMOUNT 并合并进日线
python scripts/backfill_volamount.py --start 20100101
# 或日常一键
python scripts/sync_all.py
```

### 自动每日更新（Windows）

```powershell
powershell -ExecutionPolicy Bypass -File scripts\register_daily_task.ps1
```

计划任务名：`AShareDataDailySync`（工作日 16:00）。

### VOLAMOUNT 全量回填（thsdk 按月区间）

```bash
# 问句类似：沪深A股,2024年1月2日至2024年1月31日总笔数
python scripts/backfill_volamount.py --start 20100101
```

## 数据源

- [baostock](http://baostock.com/)：沪深 A 股前复权日线、股票列表、交易日历  
- [thsdk](https://pypi.org/project/thsdk/)：`wencai_nlp` 全市场区间总笔数（VOLAMOUNT）  
- [AKShare](https://github.com/akfamily/akshare)：列表/日历的备用回退
