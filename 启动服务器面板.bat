@echo off
rem ============================================================
rem  Miruku panel one-click launcher
rem  1) SSH tunnel  6185 / 5099 / 6081 / 14100
rem  2) local panel http://127.0.0.1:8642/
rem  3) opens the browser
rem  Closing this window tears down the tunnel and the panel.
rem  Real logic lives in panel\panel-start.ps1 (kept ASCII-only).
rem ============================================================
title Miruku Panel
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0panel\panel-start.ps1"
set RC=%ERRORLEVEL%
if not "%RC%"=="0" (
  echo.
  echo Launcher exited with code %RC%.
  pause
)
exit /b %RC%
