#!/usr/bin/env bash
# 等待日线任务结束后，自动启动问财 volamount 回填
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY="$(command -v python3)"
LOGDIR="${ROOT}/logs"
mkdir -p "$LOGDIR"
LOG="${LOGDIR}/volamount_backfill.log"

echo "[$(date -Iseconds)] 等待日线任务结束 (update_daily / initial_build) ..." | tee -a "$LOG"

while pgrep -f "scripts/(initial_build|update_daily)\.py" >/dev/null 2>&1; do
  n=$(find data/daily -name '*.parquet' 2>/dev/null | wc -l)
  echo "[$(date -Iseconds)] 仍在拉日线 ... daily 文件数: $n" | tee -a "$LOG"
  sleep 120
done

echo "[$(date -Iseconds)] 日线完成，开始 volamount 回填" | tee -a "$LOG"
"$PY" -u scripts/backfill_volamount.py --start 20100101 2>&1 | tee -a "$LOG"
echo "[$(date -Iseconds)] volamount 回填完成" | tee -a "$LOG"

echo "[$(date -Iseconds)] 注册 Linux 每日增量 cron" | tee -a "$LOG"
bash scripts/register_daily_cron.sh 2>&1 | tee -a "$LOG" || true

echo "[$(date -Iseconds)] 全部完成" | tee -a "$LOG"
