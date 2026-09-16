@echo off
title Shinkansen Custom Auto Updater

set "PYTHON=C:\Users\Ninjader\AppData\Local\Python\pythoncore-3.14-64\python.exe"
if not exist "%PYTHON%" (
    set "PYTHON=python.exe"
)

"%PYTHON%" "%~dp0scripts\update_upstream.py" %*

echo.
pause
