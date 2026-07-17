#!/usr/bin/env bash
# 注册 Linux cron：工作日 16:00 增量同步（meta + baostock 日线 + 问财 volamount）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="${ROOT}/.venv/bin/python3"
if [[ ! -x "$PY" ]]; then
  PY="$(command -v python3)"
fi
SYNC="${ROOT}/scripts/sync_all.py"
LOGDIR="${ROOT}/logs"
mkdir -p "$LOGDIR"

CRON_LINE="0 16 * * 1-5 cd ${ROOT} && ${PY} ${SYNC} >> ${LOGDIR}/cron_sync.log 2>&1"

if crontab -l 2>/dev/null | grep -Fq "$SYNC"; then
  echo "cron 已存在: $SYNC"
else
  (crontab -l 2>/dev/null; echo "$CRON_LINE") | crontab -
  echo "已注册 cron: 工作日 16:00"
fi
echo "$CRON_LINE"
echo "查看: crontab -l"
echo "删除: crontab -e  # 手动删掉对应行"
