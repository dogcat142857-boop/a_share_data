# 注册 Windows 计划任务：每个交易日习惯在 16:00 跑 sync（跳过非交易日由脚本侧日历控制）
# 需要管理员或当前用户计划任务权限。用法：
#   powershell -ExecutionPolicy Bypass -File scripts\register_daily_task.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Script = Join-Path $Root "scripts\run_daily_sync.ps1"
$TaskName = "AShareDataDailySync"

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$Script`"" `
    -WorkingDirectory $Root

# 工作日 16:00（含法定节假日仍会触发，无交易日则 volamount/日线会快速跳过）
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 4:00PM
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Force | Out-Null

Write-Host "已注册计划任务: $TaskName"
Write-Host "触发: 工作日 16:00"
Write-Host "脚本: $Script"
Write-Host "查看: Get-ScheduledTask -TaskName $TaskName"
Write-Host "删除: Unregister-ScheduledTask -TaskName $TaskName -Confirm:`$false"
