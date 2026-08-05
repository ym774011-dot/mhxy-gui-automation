@echo off
rem 启动 mhxy-gui-automation GUI（用项目 venv 的 python，勿用 PATH 里的 python）
cd /d "E:\DS\mhxy-gui-automation"
"E:\py\python.exe" main.py
if errorlevel 1 (
    echo.
    echo 启动失败，请查看上方错误信息。
    pause
)
