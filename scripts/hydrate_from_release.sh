#!/usr/bin/env bash
# 把 GitHub Release 主包解压到固定目录，供 Cursor Environment 快照复用。
# 幂等：已有足够 daily 文件则跳过下载。
#
# 默认装到仓库外，避免和新研究仓库的工作区缠在一起：
#   export A_SHARE_DATA_ROOT=$HOME/datasets/a_share
#   bash scripts/hydrate_from_release.sh
#
# 可选环境变量：
#   A_SHARE_DATA_ROOT   数据根目录（含 daily/ meta/）
#   A_SHARE_RELEASE_TAG Release tag，默认 data-20260719-full
#   A_SHARE_RELEASE_ZIP 资产文件名，默认 a_share_data_20260719.zip
#   A_SHARE_MIN_DAILY   认为“已就绪”的最少个股文件数，默认 5000

set -euo pipefail

ROOT="${A_SHARE_DATA_ROOT:-$HOME/datasets/a_share}"
TAG="${A_SHARE_RELEASE_TAG:-data-20260719-full}"
ZIP_NAME="${A_SHARE_RELEASE_ZIP:-a_share_data_20260719.zip}"
MIN_DAILY="${A_SHARE_MIN_DAILY:-5000}"
REPO="${A_SHARE_RELEASE_REPO:-dogcat142857-boop/a_share_data}"
URL="https://github.com/${REPO}/releases/download/${TAG}/${ZIP_NAME}"

mkdir -p "$ROOT"
daily_n=0
if [[ -d "$ROOT/daily" ]]; then
  daily_n=$(find "$ROOT/daily" -name '*.parquet' 2>/dev/null | wc -l | tr -d ' ')
fi

if [[ "$daily_n" -ge "$MIN_DAILY" ]]; then
  echo "[hydrate] 已就绪: $ROOT (daily=$daily_n)，跳过下载"
  echo "export A_SHARE_DATA_ROOT=$ROOT"
  exit 0
fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
echo "[hydrate] 下载 $URL ..."
curl -fL --retry 5 --retry-delay 4 -o "$tmp/data.zip" "$URL"
echo "[hydrate] 解压到 $ROOT ..."
# zip 内通常含 data/daily data/meta；统一摊平到 ROOT
unzip -q "$tmp/data.zip" -d "$tmp/out"
if [[ -d "$tmp/out/data/daily" ]]; then
  mkdir -p "$ROOT"
  # 合并 meta/daily，不覆盖已有 raw（若有）
  cp -a "$tmp/out/data/." "$ROOT/"
elif [[ -d "$tmp/out/daily" ]]; then
  cp -a "$tmp/out/." "$ROOT/"
else
  echo "[hydrate] zip 结构异常，顶层：" >&2
  find "$tmp/out" -maxdepth 2 -type d >&2
  exit 1
fi

daily_n=$(find "$ROOT/daily" -name '*.parquet' | wc -l | tr -d ' ')
echo "[hydrate] 完成: daily=$daily_n root=$ROOT"
echo "export A_SHARE_DATA_ROOT=$ROOT"
