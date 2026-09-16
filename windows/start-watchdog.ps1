param (
    [switch]$Silent
)

if (-not $Silent) {
    try { $Host.UI.RawUI.WindowTitle = "LLM 智慧守護代理 (啟動中)" } catch {}
}

# 檢查是否已在運行
$listening = Get-NetTCPConnection -State Listen -LocalPort 8080 -ErrorAction SilentlyContinue
if ($listening) {
    if (-not $Silent) {
        Write-Host "[OK] LLM 智慧守護代理已在後台運行中！" -ForegroundColor Green
        Write-Host "工作列系統匣圖示: 請查看右下角通知區 (或點選 ^ 展開)" -ForegroundColor Cyan
        Write-Host "正在開啟 Web 儀表板..." -ForegroundColor Yellow
        Start-Process "http://127.0.0.1:8080/status"
        Start-Sleep -Seconds 2
    }
    exit 0
}

$TrayScript     = Join-Path $PSScriptRoot "llm_tray.py"
# 優先判定當前 repo 是否自帶 watchdog，否則往上層搜尋
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (Test-Path (Join-Path $RepoRoot "watchdog\__init__.py")) {
    $RootDir = $RepoRoot
} else {
    $RootDir = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
}

# 尋找 pythonw.exe
$Pythonw = "C:\Users\Ninjader\AppData\Local\Python\pythoncore-3.14-64\pythonw.exe"
if (-not (Test-Path $Pythonw)) {
    $found = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
    if ($found) { $Pythonw = $found }
}

if (-not $Silent) {
    Write-Host "正在背景啟動 LLM 智慧守護代理 (連接埠 8080)..." -ForegroundColor Yellow
}
Start-Process -FilePath $Pythonw -ArgumentList "-m watchdog.llm_watchdog" -WorkingDirectory $RootDir -WindowStyle Hidden

Start-Sleep -Milliseconds 300

if (-not $Silent) {
    Write-Host "正在啟動工作列通知區 LLM 圖示..." -ForegroundColor Yellow
}
Start-Process -FilePath $Pythonw -ArgumentList "`"$TrayScript`"" -WorkingDirectory $RootDir -WindowStyle Hidden

if (-not $Silent) {
    Start-Sleep -Seconds 1
    Write-Host "[OK] 啟動完成！" -ForegroundColor Green
    Write-Host "  - 系統匣圖示: 右下角工作列 (鋼青藍灰=待命 / 翠綠=運行中 / 珊瑚朱紅=啟動中)" -ForegroundColor Cyan
    Write-Host "  - 控制儀表板: http://127.0.0.1:8080/status" -ForegroundColor Cyan
    Start-Sleep -Seconds 2
} else {
    Start-Sleep -Milliseconds 500
}
