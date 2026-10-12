param ([switch]$Silent)
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$TrayScript = Join-Path $PSScriptRoot 'llm_tray.py'
$Pythonw = 'C:\Users\Ninjader\AppData\Local\Python\pythoncore-3.14-64\pythonw.exe'
$VenvPythonw = Join-Path $RepoRoot '.venv\Scripts\pythonw.exe'
if (Test-Path -LiteralPath $VenvPythonw) { $Pythonw = $VenvPythonw }
if (-not (Test-Path -LiteralPath $Pythonw)) {
    throw '找不到 pythonw.exe，請設定 LLM watchdog 的 Python 核心路徑。'
}
$backend = $null
try { $backend = Invoke-RestMethod -Uri 'http://127.0.0.1:8080/api/status' -TimeoutSec 2 } catch {}
if (-not $backend) {
    Start-Process -FilePath $Pythonw -ArgumentList '-m watchdog.llm_watchdog' -WorkingDirectory $RepoRoot -WindowStyle Hidden
    $deadline = (Get-Date).AddSeconds(15)
    do {
        Start-Sleep -Milliseconds 200
        try { $backend = Invoke-RestMethod -Uri 'http://127.0.0.1:8080/api/status' -TimeoutSec 2 } catch {}
    } while (-not $backend -and (Get-Date) -lt $deadline)
    if (-not $backend) { throw 'LLM watchdog 啟動失敗：無法連接本機 API。' }
}
$trays = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -eq 'pythonw.exe' -and $_.CommandLine -and $_.CommandLine.Contains($TrayScript)
}
if (-not $trays) {
    Start-Process -FilePath $Pythonw -ArgumentList "`"$TrayScript`"" -WorkingDirectory $RepoRoot -WindowStyle Hidden
}
if (-not $Silent) {
    Write-Host '[OK] LLM watchdog 已啟動。右鍵點擊系統匣圖示可開啟控制選單。' -ForegroundColor Green
    Write-Host '網頁控制台：http://127.0.0.1:8080/status'
}
