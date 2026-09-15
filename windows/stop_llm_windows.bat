@echo off
where pwsh.exe >nul 2>&1
if %errorlevel% equ 0 (
    pwsh.exe -ExecutionPolicy Bypass -NoProfile -File "%~dp0stop-watchdog.ps1"
) else (
    powershell.exe -ExecutionPolicy Bypass -NoProfile -File "%~dp0stop-watchdog.ps1"
)
