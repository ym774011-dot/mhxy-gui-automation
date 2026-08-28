# -*- coding: utf-8 -*-
"""网关自愈守卫：JHRW1/SYBUZ2 调用网关失败时，自动拉起/重启网关并 attach 当前游戏 PID。

背景（2026-08-24）：游戏重启（PID 变化）后 mhxy-mcp-gateway 未跟随重启，
JHRW1 直连 18082 报 WinError 10061。此模块让脚本调用网关失败时"自愈"，
无需手动双击 启动网关.bat。

用法（懒加载，函数内延迟 import，避免循环依赖）:
    from core.gateway_guard import ensure_gateway
    ok, info = ensure_gateway()           # 自动从 window_manager 单例取 PID
    ok, info = ensure_gateway(pid=12345)  # 或显式指定

依赖: E:/py/pythonw.exe + E:/DS/mhxy-mcp-gateway/gateway.py（--auto 或 <PID>）
"""
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request

# 独立运行（python core/gateway_guard.py）时确保项目根在 sys.path
_APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_ROOT not in sys.path:
    sys.path.insert(0, _APP_ROOT)

GATEWAY_HOST = "127.0.0.1"
# 2026-08-25：端口改为运行时按组解析（组1=18082，组2=18083...）。
# 旧模块常量 GATEWAY_PORT=18082 保留作 fallback（兼容独立 CLI 调用）。
GATEWAY_PORT = 18082
GATEWAY_URL = f"http://{GATEWAY_HOST}:{GATEWAY_PORT}"
GATEWAY_DIR = r"E:\DS\mhxy-mcp-gateway"
GATEWAY_PY = os.path.join(GATEWAY_DIR, "gateway.py")
PYW = r"E:\py\pythonw.exe"
CREATE_NO_WINDOW = 0x08000000

_lock = threading.Lock()


def _gw_port() -> int:
    """当前组的网关端口：优先 config/group<N>/settings.json gateway.port，
    无组配置时回退 18082（兼容 CLI 独立运行）。"""
    try:
        from core.group_config import gateway_port
        p = gateway_port()
        if p:
            return int(p)
    except Exception:
        pass
    return GATEWAY_PORT


def _gw_url() -> str:
    return f"http://{GATEWAY_HOST}:{_gw_port()}"


def _status(timeout: float = 3.0) -> dict:
    """GET /api/status。2026-08-27：timeout 1.2→3.0（游戏加载期 status 偶发慢）。"""
    try:
        req = urllib.request.Request(_gw_url() + "/api/status", timeout=timeout)
        with urllib.request.urlopen(req) as resp:
            d = json.loads(resp.read().decode("utf-8", "replace"))
        return d.get("result") or {}
    except Exception:
        return None


def _bound_pid():
    """取脚本绑定的窗口 PID（唯一权威）：
    1. window_manager 单例（GUI 运行时实时值，最优）
    2. config window.pid 回退（GUI 未初始化时，须校验进程存活且是游戏实例）
    """
    try:
        from core.window_manager import WindowManager
        wm = WindowManager()
        pid = getattr(wm, "pid", 0) or 0
        if pid > 0:
            return int(pid)
    except Exception:
        pass
    try:
        from config.config import config
        pid = config.get("window.pid")
        pid = int(pid) if pid else None
    except Exception:
        return None
    if pid and _is_game_process(pid):
        return pid
    return None


def _is_game_process(pid: int) -> bool:
    """校验 PID 是存活的游戏实例（tasklist /FI）。

    2026-08-27 修复：tasklist（不带 /V）只输出**映像名**，本游戏真实进程名是
    快乐西游.exe（窗口标题才是"十年一梦…"），旧判定 '十年一梦' in out 永远为假
    → config fallback 的合法 PID 全被误杀 → ensure_gateway 报 no_pid。
    """
    try:
        out = subprocess.check_output(
            f"tasklist /FI \"PID eq {pid}\" /FO CSV", shell=True).decode("gbk", "ignore")
        return any(k in out for k in ("十年一梦", "快乐西游")) or ("mhxy" in out.lower())
    except Exception:
        return False


def _listener_pid_on_port(port: int = None):
    """netstat 找占用端口的监听进程 PID（杀旧网关用）。"""
    if port is None:
        port = _gw_port()
    try:
        out = subprocess.check_output(
            f"netstat -ano | findstr :{port}", shell=True).decode("gbk", "ignore")
        for line in out.splitlines():
            if "LISTENING" in line:
                parts = line.split()
                if len(parts) >= 5 and parts[-1].isdigit():
                    return int(parts[-1])
    except Exception:
        pass
    return None


def _pid_alive(pid: int) -> bool:
    """进程是否存活（tasklist /FI，杀旧网关轮询用）。"""
    try:
        out = subprocess.check_output(
            f"tasklist /FI \"PID eq {pid}\" /FO CSV", shell=True).decode("gbk", "ignore")
        return str(pid) in out
    except Exception:
        return False


def _graceful_kill(pid: int, port: int = None) -> bool:
    """杀旧网关前先优雅 detach（2026-08-24 铁律）。

    强杀正在 frida-attach 的网关 → frida session 非正常中断 → 游戏端 agent
    异常 → **游戏闪退**（20:15/20:24 两次实测）。必须先调 /api/admin/shutdown
    让 gateway 先 session.detach() 再退出，taskkill 仅作兜底。

    2026-08-27 提速：固定 sleep(2.5) 改为轮询进程退出（0.3s 步进，上限 2.5s），
    正常 shutdown 后几百 ms 即可继续。
    """
    if port is None:
        port = _gw_port()
    try:
        req = urllib.request.Request(
            f"http://{GATEWAY_HOST}:{port}/api/admin/shutdown",
            data=b"{}", headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=3)
        t0 = time.time()
        while time.time() - t0 < 2.5:
            if not _pid_alive(pid):
                break
            time.sleep(0.3)
    except Exception:
        pass
    return _kill_pid(pid)


def _kill_pid(pid: int) -> bool:
    try:
        subprocess.call(f"taskkill /F /PID {pid}", shell=True)
        return True
    except Exception:
        return False


def _spawn(pid) -> bool:
    """拉起网关并 attach 指定 PID（多开场景禁止 --auto，避免 attach 错实例）。"""
    port = _gw_port()
    args = [PYW, GATEWAY_PY, str(pid), "--port", str(port)]
    try:
        # 2026-08-25: stdout/stderr 重定向到日志文件（pythonw 无控制台，print 全丢）
        # 2026-08-27: 日志按端口命名，GUI 关窗时 stop_gateway 只清本组日志
        import io
        logf = open(os.path.join(GATEWAY_DIR, f"gateway_spawn_{port}.log"),
                    "a", encoding="utf-8", buffering=1)
        subprocess.Popen(args, cwd=GATEWAY_DIR, creationflags=CREATE_NO_WINDOW,
                         stdout=logf, stderr=subprocess.STDOUT)
        return True
    except Exception:
        return False


def _ready(st: dict, pid: int) -> bool:
    """网关就绪判定：HTTP 通 + attach 目标 PID + lua 已捕获 + frida script 健康。
    script_status_error（如 script has been destroyed）= 旧会话随游戏重启失效，不算就绪。
    """
    return bool(st and st.get("attached") and st.get("pid") == pid
                and st.get("lua_state_captured")
                and not st.get("script_status_error"))


def ensure_gateway(pid=None, timeout: float = 120.0, verbose: bool = False):
    """幂等自愈：确保网关在线且 attach 到目标游戏 PID。

    - 在线且 PID 匹配       → 直接复用（reuse）
    - 在线但 PID 不匹配     → 杀旧进程 → 拉起（游戏重连/多开 attach 错场景）
    - 不在线               → 若有进程占端口先杀 → 拉起
    - 轮询等待就绪，返回 (ok, info)

    2026-08-27 提速（已验证）：gateway_run.log 打点显示本机冷启动
    attach+Lua 捕获+全脚本加载仅 ~1.0s；22:26 的 5m23s 根因不是 attach 慢，
    而是 /api/status 每次同步做 frida RPC（游戏加载期延迟秒级以上）→
    就绪轮询整段超时失明 300s。gateway.py 已给 script_status 加 2s TTL
    缓存（就绪字段零 RPC 即时返回），本模块 timeout 300→120s 兜底。
    """
    with _lock:
        if pid is None:
            pid = _bound_pid()
        if pid is None:
            return False, {"action": "no_pid",
                           "error": "无法确定游戏 PID（window_manager 未绑定）"}
        st = _status()
        if _ready(st, pid):
            return True, {"action": "reuse", "pid": st.get("pid")}

        if verbose:
            print(f"[gateway_guard] 网关不在线或 PID 不匹配（当前游戏 PID={pid}），自愈中...")

        # 端口被旧网关占用 → 先优雅 detach 再杀（强杀会导致游戏闪退）
        lp = _listener_pid_on_port()
        if lp:
            _graceful_kill(lp)
            time.sleep(1.0)

        _spawn(pid)

        t0 = time.time()
        last_poll_err = None
        last_poll_st = None
        next_progress = 10.0
        while time.time() - t0 < timeout:
            time.sleep(0.4)   # 2026-08-27: 0.8→0.4，就绪拾取更快
            st = _status()
            if _ready(st, pid):
                if verbose:
                    print(f"[gateway_guard] 网关就绪 action=started PID={st.get('pid')}"
                          f" 耗时 {time.time()-t0:.1f}s")
                return True, {"action": "started", "pid": st.get("pid"),
                              "wait": round(time.time() - t0, 1)}
            if isinstance(st, dict):
                last_poll_st, last_poll_err = st, None
            else:
                last_poll_err = "status 超时/不可达"
            if verbose and time.time() - t0 >= next_progress:
                print(f"[gateway_guard] 等待网关就绪 {time.time()-t0:.0f}s..."
                      f" status={last_poll_st or last_poll_err}")
                next_progress += 10.0
        return False, {"action": "timeout", "pid": pid,
                       "last_status": last_poll_st, "last_error": last_poll_err,
                       "error": "网关启动超时（确认游戏已启动、脚本有管理员权限）"}


def stop_gateway(timeout: float = 8.0, verbose: bool = False):
    """GUI 关闭时调用：强制停止本组网关并清空其运行数据。

    步骤（2026-08-27）：
      1. 先调 /api/admin/shutdown 优雅 detach（游戏运行中严禁直接强杀，
         frida session 非正常中断会崩游戏，见 gateway._admin_shutdown 铁律）；
      2. 端口仍被占（shutdown 失败/网关假死）→ taskkill 兜底；
      3. 轮询确认端口已释放；
      4. 清理本组网关运行日志（gateway_spawn_<port>.log），下次打开从零开始。

    多组安全：只操作本组端口（group_config 解析），不影响其它组的网关。
    返回 (ok, info)。
    """
    port = _gw_port()
    info = {"port": port}

    # 1. 优雅退出
    try:
        req = urllib.request.Request(
            f"http://{GATEWAY_HOST}:{port}/api/admin/shutdown",
            data=b"{}", headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=3)
        if verbose:
            print(f"[gateway_guard] 已发送 shutdown（端口 {port}）")
    except Exception:
        pass

    # 2. 兜底强杀（端口仍被占时）
    def _listener():
        return _listener_pid_on_port(port)

    t0 = time.time()
    lp = _listener()
    if lp:
        time.sleep(1.0)  # 给 detach 留时间
        lp = _listener()
        if lp:
            _kill_pid(lp)
            info["killed_pid"] = lp

    # 3. 轮询等待端口释放
    while time.time() - t0 < timeout:
        if _listener() is None:
            info["stopped"] = True
            break
        time.sleep(0.4)
    else:
        info["stopped"] = False
        info["error"] = f"端口 {port} 释放超时"

    # 4. 清理本组网关运行日志（重新打开 GUI 时网关从干净状态加载）
    # 2026-08-28 补丁2：gateway.py 运行日志已按端口隔离为 gateway_run_<port>.log
    for name in (f"gateway_spawn_{port}.log", f"gw_{port}.log", f"gateway_run_{port}.log"):
        p = os.path.join(GATEWAY_DIR, name)
        try:
            if os.path.exists(p):
                with open(p, "w", encoding="utf-8") as f:
                    f.write("")
                info.setdefault("cleaned", []).append(name)
        except Exception as e:
            info.setdefault("clean_errors", []).append(f"{name}: {e}")

    if verbose:
        print("[gateway_guard] stop:", info)
    return bool(info.get("stopped")), info


if __name__ == "__main__":
    # CLI 入口：python core/gateway_guard.py [PID]     → 拉起网关
    #           python core/gateway_guard.py --stop   → 停止网关（GUI 关闭同款逻辑）
    if len(sys.argv) > 1 and sys.argv[1] == "--stop":
        _ok, _info = stop_gateway(verbose=True)
    else:
        pid_arg = None
        if len(sys.argv) > 1 and sys.argv[1].isdigit():
            pid_arg = int(sys.argv[1])
        _ok, _info = ensure_gateway(pid=pid_arg, verbose=True)
    print("[gateway_guard]", "OK" if _ok else "FAIL", _info)
    raise SystemExit(0 if _ok else 1)
