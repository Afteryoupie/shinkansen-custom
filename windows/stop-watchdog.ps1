param([switch]$DryRun)
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$TrayScript = Join-Path $PSScriptRoot 'llm_tray.py'
if (-not $DryRun) {
    try { Invoke-RestMethod -Uri 'http://127.0.0.1:8080/api/stop' -Method Post -TimeoutSec 10 | Out-Null } catch {}
    Start-Sleep -Seconds 2
}
# Match this watchdog's Python processes, never the invoking shell or unrelated llama servers.
$procs = Get-CimInstance Win32_Process | Where-Object {
    $_.ProcessId -ne $PID -and $_.Name -in @('python.exe', 'pythonw.exe') -and $_.CommandLine -and
    ($_.CommandLine -like '*-m watchdog.llm_watchdog*' -or
     $_.CommandLine -like '*-m watchdog.laya_backend*' -or
     $_.CommandLine.Contains($TrayScript) -or
     $_.CommandLine.Contains((Join-Path $RepoRoot 'watchdog\laya_backend.py')))
}
foreach ($proc in $procs) {
    if ($DryRun) { Write-Host "[DryRun] 結束程序樹 $($proc.ProcessId)：$($proc.CommandLine)" }
    else { & "$env:SystemRoot\System32\taskkill.exe" /F /T /PID $proc.ProcessId | Out-Null }
}
if (-not $DryRun) {
    $listeners = Get-NetTCPConnection -LocalPort 8080,8081 -State Listen -ErrorAction SilentlyContinue
    if ($listeners) { throw '8080 或 8081 仍有服務監聽，請檢查殘留程序。' }
    Write-Host '[OK] LLM watchdog 與工具列已關閉。'
}
