# 本机一键全量：清空 data → baostock 日线 → 问财 volamount →（可选）注册每日增量
# 用法：
#   powershell -ExecutionPolicy Bypass -File scripts\run_initial_build.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\run_initial_build.ps1 -Workers 8 -RegisterDailyTask

param(
    [int]$Workers = 8,
    [switch]$RegisterDailyTask,
    [switch]$SkipVolamount
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    Write-Host "未找到 .venv，请先: python -m venv .venv && .\.venv\Scripts\activate && pip install -r requirements.txt"
    exit 1
}

$envFile = Join-Path $Root ".env"
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) { return }
        $pair = $line.Split("=", 2)
        $key = $pair[0].Trim()
        $val = $pair[1].Trim().Trim("'").Trim('"')
        if ($key) { Set-Item -Path "Env:$key" -Value $val }
    }
}

$logDir = Join-Path $Root "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logFile = Join-Path $logDir "initial_build_$stamp.log"

Write-Host "=== 本机全量构建 ==="
Write-Host "数据目录: $(Join-Path $Root 'data')"
Write-Host "Workers: $Workers"
Write-Host "日志: $logFile"
Write-Host ""

$buildArgs = @(
    (Join-Path $Root "scripts\initial_build.py"),
    "--workers", $Workers
)
if ($SkipVolamount) { $buildArgs += "--skip-volamount" }

& $Python @buildArgs *>&1 | Tee-Object -FilePath $logFile
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if ($RegisterDailyTask) {
    Write-Host ""
    Write-Host "=== 注册 Windows 每日增量计划任务 ==="
    & powershell -ExecutionPolicy Bypass -File (Join-Path $Root "scripts\register_daily_task.ps1")
}

Write-Host ""
Write-Host "完成。数据在: $(Join-Path $Root 'data\daily')"
