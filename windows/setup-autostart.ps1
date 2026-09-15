param (
    [switch]$Uninstall
)

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$RegPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
$RegName = "LLM_Watchdog"
$TargetScript = Join-Path $PSScriptRoot "start-watchdog.ps1"
$Command = "powershell.exe -ExecutionPolicy Bypass -NoProfile -WindowStyle Hidden -File `"$TargetScript`" -Silent"

if ($Uninstall) {
    $exists = (Get-ItemProperty -Path $RegPath -Name $RegName -ErrorAction SilentlyContinue)
    if ($exists) {
        Remove-ItemProperty -Path $RegPath -Name $RegName -Force
        Write-Host "==========================================" -ForegroundColor Cyan
        Write-Host "[OK] 已成功解除開機自動啟動！" -ForegroundColor Green
        Write-Host "已從 Windows 登入自啟動清單 (Registry Run) 移除。" -ForegroundColor Yellow
        Write-Host "==========================================" -ForegroundColor Cyan
    } else {
        Write-Host "[提示] 尚未設定開機自動啟動，無需解除。" -ForegroundColor Yellow
    }
    Start-Sleep -Seconds 2
    exit 0
}

# 寫入 Windows 原生自啟動註冊表 (完全靜默，無確認畫面跳出)
Set-ItemProperty -Path $RegPath -Name $RegName -Value $Command

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  LLM 智慧守護代理 - 開機自動啟動設定" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "[OK] 已更新為「開機靜默啟動（無確認視窗）」！" -ForegroundColor Green
Write-Host ""
Write-Host "啟動設定詳情：" -ForegroundColor White
Write-Host "  • 註冊表位置：HKCU\Software\Microsoft\Windows\CurrentVersion\Run" -ForegroundColor Gray
Write-Host "  • 啟動命令：$Command" -ForegroundColor DarkGray
Write-Host ""
Write-Host "說明事項：" -ForegroundColor White
Write-Host "  1. 開機登入時將完全在背景啟動，不會有任何黑視窗或確認畫面閃爍。" -ForegroundColor Gray
Write-Host "  2. 啟動後可直接在右下角系統匣看到 LLM 狀態圖示。" -ForegroundColor Gray
Write-Host "  3. 若手動點擊「啟動LLM守護代理.bat」，依然會正常顯示狀態與網址。" -ForegroundColor Gray
Write-Host "==========================================" -ForegroundColor Cyan
Start-Sleep -Seconds 3
