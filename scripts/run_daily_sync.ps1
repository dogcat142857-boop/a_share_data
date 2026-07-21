# Daily sync: meta + daily OHLCV + VOLAMOUNT
# Invoked by Windows Scheduled Task; working directory = repo root.
#
# NOTE: Keep this file ASCII-only (or UTF-8 with BOM). Windows PowerShell
# defaults to system ANSI for .ps1 without BOM; Chinese literals break parsing.
# Data root comes from config/settings.yaml and/or .env A_SHARE_DATA_ROOT
# (loaded by Python); do not hardcode non-ASCII paths here.

# Continue: baostock may write "login failed!" to stderr; Stop would abort the task.
$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    $Python = "python"
}

$envFile = Join-Path $Root ".env"
if (Test-Path $envFile) {
    Get-Content $envFile -Encoding UTF8 | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) { return }
        $pair = $line.Split("=", 2)
        $key = $pair[0].Trim()
        $val = $pair[1].Trim().Trim("'").Trim('"')
        # Strip UTF-8 BOM if present on first key
        if ($key.Length -gt 0 -and [int][char]$key[0] -eq 0xFEFF) {
            $key = $key.Substring(1)
        }
        if ($key) { Set-Item -Path "Env:$key" -Value $val }
    }
}

$logDir = Join-Path $Root "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logFile = Join-Path $logDir "daily_sync_$stamp.log"

$syncScript = Join-Path $Root "scripts\sync_all.py"
# Redirect via cmd so PowerShell does not treat native stderr as terminating.
cmd /c "`"$Python`" `"$syncScript`" > `"$logFile`" 2>&1"
$exitCode = $LASTEXITCODE
Get-Content $logFile -ErrorAction SilentlyContinue | Select-Object -Last 30
exit $exitCode
