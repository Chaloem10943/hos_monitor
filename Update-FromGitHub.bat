@echo off
setlocal
title HosMonitor Update from GitHub
echo =======================================================
echo          HosMonitor 1-Click Update from GitHub
echo =======================================================
echo.
echo Running update script...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\Update-HosMonitorFromGitHub.ps1" -Install
if %ERRORLEVEL% neq 0 (
    echo.
    echo [ERROR] Update process encountered an error (Exit Code: %ERRORLEVEL%).
)
echo.
pause
