# PZXY-ZG5-toggle.ps1 — 5 开小队一键启停（2026-09-06）
# 逻辑：小队任一进程在跑 → 全停；没跑 → 拉起 zhuagui_squad.py 编排器
#       （自动播种 5 窗口 → 观察登录顺序 → 第一个登录=队长完整跑批，其余=纯出售）
$ErrorActionPreference = 'SilentlyContinue'
$pyExe  = 'E:\py\python.exe'
$repo   = 'E:\DS\mhxy-gui-automation'
$squad  = Join-Path $repo 'tools\zhuagui_squad.py'

Write-Host ''
Write-Host '==== 5 开小队启停（文件通道 / 无网关） ===='

# ---- 1) 停止：小队相关进程任一在跑则全部结束 ----
$running = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -match 'zhuagui_squad|member_sell_loop|run_unlimited_test' })
if ($running.Count -gt 0) {
    Write-Host ('[停] 检测到小队进程 ' + $running.Count + ' 个，停止中...')
    foreach ($p in $running) {
        Stop-Process -Id $p.ProcessId -Force
        Write-Host ('  stopped PID ' + $p.ProcessId)
    }
    Write-Host '已停止。'
    Write-Host ''
    Write-Host '---- 按任意键退出 ----'
    $null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')
    exit
}

# ---- 2) 启动：拉起编排器（独立控制台窗口，播种/登录观察过程可见） ----
Write-Host '[启动] zhuagui_squad.py 编排器（新窗口打开，过程可见）...'
Write-Host '  前提：5 个游戏窗口全部停在登录界面。'
Write-Host '  编排器会自动播种 → 等你依次登录 → 第一个登录的自动当队长。'
Start-Process -FilePath $pyExe -ArgumentList @($squad) -WorkingDirectory $repo
Write-Host ''
Write-Host '---- 按任意键退出 ----'
$null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')
