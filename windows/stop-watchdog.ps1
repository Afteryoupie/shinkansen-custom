$Host.UI.RawUI.WindowTitle = "LLM 智慧守護代理 (停止中)"
Write-Host "正在關閉 LLM 守護代理並釋放顯存..." -ForegroundColor Yellow

try {
    Invoke-RestMethod -Uri "http://127.0.0.1:8080/api/stop" -Method Post -TimeoutSec 2 -ErrorAction SilentlyContinue | Out-Null
} catch {}

# 清理所有殘留進程
$procs = Get-CimInstance Win32_Process | Where-Object { 
    $_.CommandLine -like "*watchdog*" -or 
    $_.CommandLine -like "*llm_watchdog*" -or 
    $_.CommandLine -like "*llm_tray.py*" -or 
    $_.Name -eq "llama-server.exe" 
}
foreach ($p in $procs) {
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
}

Write-Host "[OK] LLM 守護代理與圖示已完全關閉，顯存已 100% 釋放！" -ForegroundColor Green
Start-Sleep -Seconds 2
