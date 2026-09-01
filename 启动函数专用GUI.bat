@echo off
rem 启动「函数专用」精简 GUI（只支持现有任务库函数，无 watchdog/monitor 等多余组件）
cd /d "E:\DS\mhxy-gui-automation"
"E:\py\python.exe" "E:\DS\mhxy-gui-automation\函数专用\main.py"
if errorlevel 1 (
    echo.
    echo 启动失败，请查看上方错误信息。
    pause
)