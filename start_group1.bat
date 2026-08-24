@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === 启动组1 (蓝) GUI ===
start "mhxy-gui-group1" /min cmd /k "E:\py\python.exe main.py --group 1"
