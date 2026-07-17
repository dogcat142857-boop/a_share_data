# a_share_data

A 股个股数据日常维护仓库：

- **日线**：baostock 前复权（`adjustflag=2`），含 baostock 可提供的全部交易字段
- **VOLAMOUNT（总笔数）**：同花顺问财（`thsdk.wencai_nlp`）按区间批量拉取，合并进个股 parquet

## 字段

`date, code, open, high, low, close, preclose, volume, amount, turnover, pct_chg, tradestatus, pe_ttm, pb_mrq, ps_ttm, pcf_ncf_ttm, is_st, volamount`

## 数据目录

```
data/
  meta/           # 股票列表、交易日历
  daily/          # 一股一文件 {code}.parquet
  raw/wencai/     # 问财 volamount 原始缓存
```

## 首次全量构建

```bash
pip install -r requirements.txt
# .env 中配置 THS_USERNAME / THS_PASSWORD（问财，可选游客）

python scripts/initial_build.py --workers 8
```

流程：清空旧数据 → 更新 meta → baostock 全市场日线 → 问财 volamount 全量回填 → 合并。

仅重建日线（保留/跳过 volamount）：

```bash
python scripts/rebuild_from_baostock.py --workers 8
```

## 每日增量

```bash
python scripts/sync_all.py
```

- 更新 meta（股票列表 / 交易日历）
- baostock 增量补日线（跳过已是最新交易日的股票）
- 问财补最近 5 个交易日 volamount 并合并

### 自动日更

**Windows**（工作日 16:00）：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\register_daily_task.ps1
```

**Linux**：

```bash
bash scripts/register_daily_cron.sh
```

## 在其他项目读取

```python
from a_share import load_daily, list_codes
df = load_daily("600519", start="2024-01-01")
```

## 数据源

- [baostock](http://baostock.com/)：沪深 A 股前复权日线及估值/状态字段
- [thsdk](https://pypi.org/project/thsdk/)：问财 NLP 全市场 volamount
- [AKShare](https://github.com/akfamily/akshare)：列表/日历备用
