# 每日收盘后自动同步 A 股数据（元数据 + 日线 + VOLAMOUNT）
# 由 Windows 计划任务调用；工作目录为仓库根目录

# Continue：baostock 等会往 stderr 打 "login failed!"，Stop 会导致计划任务误失败
$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    $Python = "python"
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
$logFile = Join-Path $logDir "daily_sync_$stamp.log"

$syncScript = Join-Path $Root "scripts\sync_all.py"
# 用 cmd 重定向，避免 PowerShell 把 native stderr 当成终止错误
cmd /c "`"$Python`" `"$syncScript`" > `"$logFile`" 2>&1"
$exitCode = $LASTEXITCODE
Get-Content $logFile -ErrorAction SilentlyContinue | Select-Object -Last 30
exit $exitCode
