@echo off
rem 启动 mhxy-gui-automation GUI 组1（蓝，默认组；推荐用 start_group1.bat / start_group2.bat 区分多组）
cd /d "E:\DS\mhxy-gui-automation"
"E:\py\python.exe" main.py --group 1
if errorlevel 1 (
    echo.
    echo 启动失败，请查看上方错误信息。
    pause
)
