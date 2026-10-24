@echo off
chcp 65001 >nul
set "WEBVIEW2_USER_DATA_FOLDER=%LOCALAPPDATA%\miruku-astrbot-launcher-webview-recovery"
cd /d "%~dp0AstrBot Launcher"
start "" "%cd%\astrbot-launcher.exe"
