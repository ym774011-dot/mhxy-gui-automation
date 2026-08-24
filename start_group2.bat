@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === 启动组2 (绿) GUI ===
start "mhxy-gui-group2" /min cmd /k "E:\py\python.exe main.py --group 2"
