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
GATEWAY_PORT = 18082
GATEWAY_URL = f"http://{GATEWAY_HOST}:{GATEWAY_PORT}"
GATEWAY_DIR = r"E:\DS\mhxy-mcp-gateway"
GATEWAY_PY = os.path.join(GATEWAY_DIR, "gateway.py")
PYW = r"E:\py\pythonw.exe"
CREATE_NO_WINDOW = 0x08000000

_lock = threading.Lock()


def _status(timeout: float = 1.2) -> dict:
    try:
        req = urllib.request.Request(GATEWAY_URL + "/api/status", timeout=timeout)
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
    """校验 PID 是存活的游戏实例（tasklist /FI）。"""
    try:
        out = subprocess.check_output(
            f"tasklist /FI \"PID eq {pid}\" /FO CSV", shell=True).decode("gbk", "ignore")
        return ("十年一梦" in out) or ("mhxy" in out.lower())
    except Exception:
        return False


def _listener_pid_on_port(port: int = GATEWAY_PORT):
    """netstat 找占用端口的监听进程 PID（杀旧网关用）。"""
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


def _graceful_kill(pid: int, port: int = GATEWAY_PORT) -> bool:
    """杀旧网关前先优雅 detach（2026-08-24 铁律）。

    强杀正在 frida-attach 的网关 → frida session 非正常中断 → 游戏端 agent
    异常 → **游戏闪退**（20:15/20:24 两次实测）。必须先调 /api/admin/shutdown
    让 gateway 先 session.detach() 再退出，taskkill 仅作兜底。
    """
    try:
        req = urllib.request.Request(
            f"http://{GATEWAY_HOST}:{port}/api/admin/shutdown",
            data=b"{}", headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=3)
        time.sleep(2.5)  # 等 detach + 退出
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
    args = [PYW, GATEWAY_PY, str(pid), "--port", str(GATEWAY_PORT)]
    try:
        subprocess.Popen(args, cwd=GATEWAY_DIR, creationflags=CREATE_NO_WINDOW)
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


def ensure_gateway(pid=None, timeout: float = 90.0, verbose: bool = False):
    """幂等自愈：确保网关在线且 attach 到目标游戏 PID。

    - 在线且 PID 匹配       → 直接复用（reuse）
    - 在线但 PID 不匹配     → 杀旧进程 → 拉起（游戏重连/多开 attach 错场景）
    - 不在线               → 若有进程占端口先杀 → 拉起
    - 轮询等待就绪，返回 (ok, info)

    注意：pid 必须显式指定（或 window_manager 已绑定）。多开/守护场景
    严禁走 --auto，否则会 attach 到任意实例。
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
        while time.time() - t0 < timeout:
            time.sleep(0.8)
            st = _status()
            if _ready(st, pid):
                if verbose:
                    print(f"[gateway_guard] 网关就绪 action=started PID={st.get('pid')}")
                return True, {"action": "started", "pid": st.get("pid")}
        return False, {"action": "timeout", "pid": pid,
                       "error": "网关启动超时（确认游戏已启动、脚本有管理员权限）"}


if __name__ == "__main__":
    # CLI 入口：python core/gateway_guard.py [PID]（bat 与 GUI 自愈共用同一逻辑）
    pid_arg = None
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        pid_arg = int(sys.argv[1])
    _ok, _info = ensure_gateway(pid=pid_arg, verbose=True)
    print("[gateway_guard]", "OK" if _ok else "FAIL", _info)
    raise SystemExit(0 if _ok else 1)
