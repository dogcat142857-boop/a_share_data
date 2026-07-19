#!/usr/bin/env bash
# 等待 volamount 回填/合并结束后：打包 data → 创建 GitHub Release
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY="$(command -v python3)"
LOGDIR="${ROOT}/logs"
mkdir -p "$LOGDIR" dist
LOG="${LOGDIR}/release_after_build.log"

stamp="$(date +%Y%m%d)"
tag="data-${stamp}-full"
title="A股日线全量数据包 (baostock + volamount) ${stamp}"

log() { echo "[$(date -Iseconds)] $*" | tee -a "$LOG"; }

log "等待 backfill_volamount / update_daily / initial_build 结束 ..."
while pgrep -f "scripts/(backfill_volamount|fast_merge_volamount|update_daily|initial_build)\.py" >/dev/null 2>&1; do
  n=$(find data/daily -name '*.parquet' 2>/dev/null | wc -l)
  log "仍有数据任务在跑 ... daily=$n"
  sleep 120
done

log "数据任务已结束，开始质量抽查"
"$PY" - <<'PY' 2>&1 | tee -a "$LOG"
from pathlib import Path
import pandas as pd
daily = Path("data/daily")
files = list(daily.glob("*.parquet"))
assert len(files) >= 5000, f"daily 文件过少: {len(files)}"
df = pd.read_parquet(daily / "000001.parquet")
assert df["close"].notna().any(), "000001 无 close"
va = int(df["volamount"].notna().sum())
print(f"OK daily_files={len(files)} 000001_rows={len(df)} volamount_filled={va}")
if va < 100:
    raise SystemExit("volamount 合并似乎未完成（000001 填充过少）")
PY

log "打包 meta + daily（主包）"
"$PY" -u scripts/pack_data_release.py \
  -o "dist/a_share_data_${stamp}.zip" 2>&1 | tee -a "$LOG"

main_zip="dist/a_share_data_${stamp}.zip"
main_size=$(stat -c%s "$main_zip")
log "主包大小: $main_size bytes ($(( main_size / 1000000 )) MB)"

# GitHub 单文件约 2GB 上限，留余量
MAX=1900000000
assets=("$main_zip")

if [[ -d data/raw/wencai ]]; then
  log "尝试打包含 raw 的完整包"
  "$PY" -u scripts/pack_data_release.py --include-raw \
    -o "dist/a_share_data_${stamp}_with_raw.zip" 2>&1 | tee -a "$LOG" || true
  raw_zip="dist/a_share_data_${stamp}_with_raw.zip"
  if [[ -f "$raw_zip" ]]; then
    raw_size=$(stat -c%s "$raw_zip")
    log "含 raw 包大小: $raw_size bytes"
    if (( raw_size <= MAX )); then
      assets+=("$raw_zip")
    else
      log "含 raw 包超过 ${MAX}，不上传该文件"
      rm -f "$raw_zip"
    fi
  fi
fi

if (( main_size > MAX )); then
  log "ERROR: 主包超过 GitHub 2GB 限制，无法发布"
  exit 1
fi

# 写 release notes
notes="dist/release_notes_${stamp}.md"
n_daily=$(find data/daily -name '*.parquet' | wc -l)
cat > "$notes" <<EOF
## A股个股日线全量包 (${stamp})

### 内容
- \`data/meta/\`：股票列表、交易日历
- \`data/daily/{code}.parquet\`：个股日线（一股一文件）
- 可选 \`*_with_raw.zip\`：另含问财 volamount 原始缓存

### 覆盖
- 股票数：约 ${n_daily} 只沪深 A 股（不含北交所）
- 日线源：baostock 前复权（adjustflag=2），含 open/high/low/close/preclose/volume/amount/turnover/pct_chg/tradestatus/估值/is_st
- VOLAMOUNT：同花顺问财 thsdk（总笔数），已合并进 daily

### 使用
\`\`\`bash
unzip a_share_data_${stamp}.zip
# 解压后设置数据根目录
export A_SHARE_DATA_ROOT=/path/to/data
python -c "from a_share import load_daily; print(load_daily('000001').tail())"
\`\`\`

### 注意
数据不进 Git；本 Release 为体积较大的数据包，下载后本地维护可用 \`scripts/sync_all.py\` 做日更。
EOF

# 若 tag 已存在则删掉重建
if gh release view "$tag" >/dev/null 2>&1; then
  log "删除已有 release $tag"
  gh release delete "$tag" --yes || true
  git push origin ":refs/tags/$tag" 2>/dev/null || true
fi

log "创建 GitHub Release: $tag"
gh release create "$tag" \
  --title "$title" \
  --notes-file "$notes" \
  "${assets[@]}" 2>&1 | tee -a "$LOG"

log "发布完成: https://github.com/dogcat142857-boop/a_share_data/releases/tag/${tag}"
echo "RELEASE_DONE tag=$tag" | tee -a "$LOG"
