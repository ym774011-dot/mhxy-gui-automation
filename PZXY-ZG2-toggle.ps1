# PZXY-ZG2-toggle.ps1 — 抓鬼一键启停（方案②文件通道版，零网关）
# 逻辑：在跑 → 停；没跑 → 查 worker 心跳 → 死了自动播种（需登录界面）→ 启动跑批
$ErrorActionPreference = 'SilentlyContinue'
$pyExe  = 'E:\py\python.exe'
$repo   = 'E:\DS\mhxy-gui-automation'
$runner = Join-Path $repo 'run_unlimited_test.py'
$plant  = 'E:\DS\mhxy-mcp-gateway\tools\pzxy_plant.py'

Write-Host ''
Write-Host '==== 抓鬼启停（文件通道 / 无网关） ===='

# ---- 1) 停止：run_unlimited_test.py 在跑则全部结束 ----
$running = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -match 'run_unlimited_test\.py' })
if ($running.Count -gt 0) {
    Write-Host ''
    Write-Host ('[停] 检测到抓鬼跑批 ' + $running.Count + ' 个进程，停止中...')
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

# ---- 2) worker 心跳检查；死了尝试自动播种 ----
Write-Host '[检查] worker 心跳...'
$hb = & $pyExe -c "import sys; sys.path.insert(0,r'E:\DS\mhxy-gui-automation'); from library.pzxy_ipc import PzxyWorker; w=PzxyWorker(); print(('ALIVE ' + str(w.heartbeat()[0])) if w.is_alive() else 'DEAD')"
if ("$hb" -like 'ALIVE*') {
    Write-Host ('  worker 存活 frame=' + $hb.Split(' ')[1])
} else {
    Write-Host '  worker 不在线（游戏重启过/未播种）→ 尝试自动播种...'
    & $pyExe $plant
    if ($LASTEXITCODE -ne 0) {
        Write-Host ''
        Write-Host '[失败] 无法自动播种。操作步骤：'
        Write-Host '  1) 若跑批/TRAE 启动器还在跑，先停掉'
        Write-Host '  2) 关闭游戏窗口 → 多开器重开 → 停在登录界面（不要登录）'
        Write-Host '  3) 再双击本 bat（它会自动播种并启动）'
        Write-Host ''
        Write-Host '---- 按任意键退出 ----'
        $null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')
        exit 1
    }
}

# ---- 3) 启动跑批（file 通道，无网关） ----
Write-Host '[启动] run_unlimited_test.py --gateway file://pzxy --role 二号美人 ...'
Start-Process -FilePath $pyExe -ArgumentList @($runner, '--gateway', 'file://pzxy', '--role', '二号美人', '--timeout', '20', '--wait-dialog', '1.2') -WorkingDirectory $repo -WindowStyle Minimized
Write-Host '已启动（最小化窗口，jsonl 落 test_data/）。再次双击本 bat = 停止。'
Write-Host ''
Write-Host '---- 按任意键退出 ----'
$null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')
