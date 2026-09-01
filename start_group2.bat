@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === 启动组2 (绿) GUI ===
rem ★2026-08-31 禁用独立 captcha watchdog/monitor（多窗口下绑错窗口乱发 PostMessage 干扰引擎，farm 内置 V7 直解自足）
set MHXY_NO_WATCHDOG=1
start "mhxy-gui-group2" /min cmd /k "E:\py\python.exe main.py --group 2"
