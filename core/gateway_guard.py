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

# 2026-08-28：localhost 探测强制不走系统代理（urllib 默认读注册表代理，
# 若代理进程不可用/规则拒绝 loopback，127.0.0.1 的 /api/status 探测会整段失明）。
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
# 最近一次探测的真实异常（轮询失败日志带上它，"探测失明"可一锤定音）
_last_status_err = ""

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
    """GET /api/status。2026-08-27：timeout 1.2→3.0（游戏加载期 status 偶发慢）。
    2026-08-28：无代理 opener + 记录真实异常（旧版 except 吞掉一切只剩 None，
    无法区分"网关没起"与"探测链路被堵"）。"""
    global _last_status_err
    try:
        req = urllib.request.Request(_gw_url() + "/api/status")
        with _OPENER.open(req, timeout=timeout) as resp:
            d = json.loads(resp.read().decode("utf-8", "replace"))
        return d.get("result") or {}
    except Exception as e:
        _last_status_err = repr(e)
        return None


_ROLE_ID_RE = None


def _extract_role_id(title: str):
    """从窗口标题提取角色 ID（'…然学[701529]…' → '701529'）。

    角色 ID 跨游戏重启稳定，是自动重绑的最可靠锚点；
    标题里的登录时间戳无方括号，不会误匹配。
    """
    global _ROLE_ID_RE
    if _ROLE_ID_RE is None:
        import re
        _ROLE_ID_RE = re.compile(r"\[(\d{4,})\]")
    m = _ROLE_ID_RE.search(title or "")
    return m.group(1) if m else None


def _role_id_of_binding(wm) -> str:
    """取当前绑定对应的角色 ID（如 '701529'），两级回退。

    ★ 2026-08-29 实锤坑：window_manager 的 window_title 不一定是游戏主窗口
    标题——find_by_pid 在多开器场景下命中的是 **GGESUB 聊天窗口**（title 就是
    ' 聊天窗口'），里面根本没有 '[角色ID]'，只取它会导致重绑永远失败
    （日志表现："无法确定游戏 PID（window_manager 未绑定）"）。
    第二级改读 config window.title —— bind() 持久化的是游戏主窗口标题
    （'鲜衣怒马 - 怀旧江南版 - (鲜衣怒马 - 然学[701529]) - ...'），稳定含角色 ID。
    """
    rid = _extract_role_id(getattr(wm, "window_title", "") or "")
    if rid:
        return rid
    try:
        from config.config import config
        rid = _extract_role_id(config.get("window.title") or "")
    except Exception:
        rid = None
    return rid


def _auto_rebind(old_pid: int):
    """绑定的游戏进程已死（游戏重启换 PID）→ 按角色 ID 自动重绑 window_manager。

    根因（2026-08-29 实锤）：GUI 长驻进程的 window_manager.pid 绑死旧游戏 PID，
    游戏重启后 farm/ensure_gateway 自愈循环永远 attach 死 PID，每 ~40s 拉起
    网关即秒退（gateway_run_<port>.log 刷屏 VirtualAllocEx 0x5），永不自愈。

    锚点：角色 ID（如 701529），取 _role_id_of_binding()（运行时标题 → 持久化标题）。
    成功绑定后 bind() 会同步持久化 config window.pid/title，monitor/下次启动
    恢复全部跟上。返回新 PID（int）或 None。
    """
    try:
        from core.window_manager import WindowManager
        wm = WindowManager()
        # 进程还活着且是游戏实例 → 无需重绑
        if _pid_alive(old_pid) and _is_game_process(old_pid):
            return int(old_pid)
        role_id = _role_id_of_binding(wm)
        if not role_id:
            return None
        token = f"[{role_id}]"
        for hwnd, title, pid, visible in WindowManager.list_game_windows():
            if not pid or pid == old_pid:
                continue
            # 带方括号匹配：GUI 自身标题（"MHXY GUI [组1]…"）不含角色 ID 括号串
            if token in (title or "") and _is_game_process(pid):
                if wm.bind(pid=int(pid)):
                    try:
                        from utils.logger import logger
                        logger.info(f"网关守卫自动重绑成功: 旧PID={old_pid} → 新PID={pid}"
                                    f"（角色ID {role_id}）")
                    except Exception:
                        print(f"[gateway_guard] 自动重绑: {old_pid} → {pid}")
                    return int(pid)
                return None
    except Exception:
        return None
    return None


def _bound_pid():
    """取脚本绑定的窗口 PID（唯一权威）：
    1. window_manager 单例（GUI 运行时实时值，最优）
    2. config window.pid 回退（GUI 未初始化时，须校验进程存活且是游戏实例）

    2026-08-29：绑定 PID 已死时不再原样返回（旧版导致自愈循环死绑死 PID），
    先尝试按角色 ID 自动重绑到新游戏进程。
    """
    try:
        from core.window_manager import WindowManager
        wm = WindowManager()
        pid = getattr(wm, "pid", 0) or 0
        if pid > 0:
            if _pid_alive(pid) and _is_game_process(pid):
                return int(pid)
            new_pid = _auto_rebind(int(pid))
            if new_pid:
                return new_pid
            return None
    except Exception:
        pass
    try:
        from config.config import config
        pid = config.get("window.pid")
        pid = int(pid) if pid else None
    except Exception:
        return None
    if pid and _pid_alive(pid) and _is_game_process(pid):
        return int(pid)
    # 持久化 PID 也已死（GUI 未启动、或 wm.pid 为 0 的纯脚本场景）→
    # 同样按角色 ID 找回新实例，避免整条 farm 链因 no_pid 直接瘫掉。
    if pid:
        try:
            new_pid = _auto_rebind(int(pid))
        except Exception:
            new_pid = None
        if new_pid:
            return new_pid
    return None


def _psutil():
    """psutil 可用则返回模块（2026-08-28：替代 tasklist/netstat 子进程，单次
    调用 0.2~0.3s → <5ms；这是开关路径上最便宜的提速）。"""
    try:
        import psutil
        return psutil
    except ImportError:
        return None


def _is_game_process(pid: int) -> bool:
    """校验 PID 是存活的游戏实例。

    优先 psutil（毫秒级）；无 psutil 时回退 tasklist /FI（~0.25s）。
    2026-08-27 修复：游戏真实进程名是 快乐西游.exe（窗口标题才是"十年一梦…"）。
    """
    psu = _psutil()
    if psu is not None:
        try:
            return any(k in psu.Process(pid).name() for k in ("十年一梦", "快乐西游", "mhxy"))
        except Exception:
            return False
    try:
        out = subprocess.check_output(
            f"tasklist /FI \"PID eq {pid}\" /FO CSV", shell=True).decode("gbk", "ignore")
        return any(k in out for k in ("十年一梦", "快乐西游")) or ("mhxy" in out.lower())
    except Exception:
        return False


def _listener_pid_on_port(port: int = None):
    """找占用端口的监听进程 PID。psutil 优先（毫秒级），回退 netstat。"""
    if port is None:
        port = _gw_port()
    psu = _psutil()
    if psu is not None:
        try:
            for c in psu.net_connections(kind="tcp"):
                if "LISTEN" in (c.status or "") and c.laddr \
                        and c.laddr.port == port and c.pid:
                    return int(c.pid)
        except Exception:
            pass
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
    """进程是否存活。psutil 优先（毫秒级），回退 tasklist。"""
    psu = _psutil()
    if psu is not None:
        try:
            return psu.pid_exists(int(pid))
        except Exception:
            return False
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

    2026-08-27 提速：固定 sleep(2.5) 改为轮询进程退出。
    2026-08-28 再提速：0.3s→0.1s 步进；进程已退出则**跳过 taskkill**
    （旧版无条件 taskkill 已死 PID 白耗 ~0.3s，且 /F 落在错误复用的 PID 上有风险）。
    """
    if port is None:
        port = _gw_port()
    try:
        req = urllib.request.Request(
            f"http://{GATEWAY_HOST}:{port}/api/admin/shutdown",
            data=b"{}", headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=3)
        t0 = time.time()
        while time.time() - t0 < 2.0:
            if not _pid_alive(pid):
                return True
            time.sleep(0.1)
    except Exception:
        pass
    # 仍存活才强杀兜底
    if _pid_alive(pid):
        return _kill_pid(pid)
    return True


def _kill_pid(pid: int) -> bool:
    try:
        subprocess.call(f"taskkill /F /PID {pid}", shell=True)
        return True
    except Exception:
        return False


def _spawn(pid):
    """拉起网关并 attach 指定 PID（多开场景禁止 --auto，避免 attach 错实例）。

    2026-08-28：返回 Popen 句柄（供 ensure_gateway 检测"进程秒退"早停），
    失败返回 None。调用方按真值判断即可。
    """
    port = _gw_port()
    args = [PYW, GATEWAY_PY, str(pid), "--port", str(port)]
    try:
        # 2026-08-25: stdout/stderr 重定向到日志文件（pythonw 无控制台，print 全丢）
        # 2026-08-27: 日志按端口命名，GUI 关窗时 stop_gateway 只清本组日志
        import io
        logf = open(os.path.join(GATEWAY_DIR, f"gateway_spawn_{port}.log"),
                    "a", encoding="utf-8", buffering=1)
        return subprocess.Popen(args, cwd=GATEWAY_DIR,
                                creationflags=CREATE_NO_WINDOW,
                                stdout=logf, stderr=subprocess.STDOUT)
    except Exception:
        return None


def _read_run_log_tail(port: int = None, lines: int = 30) -> str:
    """读网关运行日志尾部（spawn 秒退时报错定位用）。"""
    if port is None:
        port = _gw_port()
    p = os.path.join(GATEWAY_DIR, f"gateway_run_{port}.log")
    try:
        with open(p, "r", encoding="utf-8", errors="ignore") as f:
            return "".join(f.readlines()[-lines:])
    except Exception:
        return ""


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
            # 2026-08-28：删固定 sleep(1.0)——_graceful_kill 内部已轮询到进程退出
            # （0.1s 步进），进程没退也留了 2s 上限，这里再睡 1s 纯属白等。

        proc = _spawn(pid)

        t0 = time.time()
        last_poll_err = None
        last_poll_st = None
        next_progress = 10.0
        while time.time() - t0 < timeout:
            time.sleep(0.15)  # 2026-08-28: 0.4→0.15，就绪拾取更快（~1s 启动不再多等 0.4s）
            # 2026-08-28：网关进程秒退（PID 失效/attach 失败）→ 早停报错，
            # 旧行为会傻等满 120s（"打开很慢"的主要来源之一）
            if proc is not None and proc.poll() is not None:
                tail = _read_run_log_tail()
                return False, {"action": "spawn_died", "pid": pid,
                               "error": "网关进程启动即退出（游戏 PID 失效或 frida attach 失败）",
                               "log_tail": tail}
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
                # 2026-08-28：带上真实异常（ConnectionRefused/timeout/代理 502…）
                last_poll_err = f"status 超时/不可达 ({_last_status_err})"
            if verbose and time.time() - t0 >= next_progress:
                print(f"[gateway_guard] 等待网关就绪 {time.time()-t0:.0f}s..."
                      f" status={last_poll_st or last_poll_err}")
                next_progress += 10.0
        return False, {"action": "timeout", "pid": pid,
                       "last_status": last_poll_st, "last_error": last_poll_err,
                       "error": "网关启动超时（确认游戏已启动、脚本有管理员权限）"}


def stop_gateway(timeout: float = 8.0, verbose: bool = False, kill: bool = False):
    """停止本组网关（GUI 关闭 / 停网关按钮 / CLI --stop 统一入口）。

    ★★ 2026-08-31 实测定论：**同一游戏进程禁止反复 detach/re-attach** ★★
    证据：19:10:44 网关 stop→start 对仍在运行的 PID 13416 做第二次 frida
    attach，96s 后（期间游戏完全空闲、无任何自动化动作）游戏在 ntdll 栈上以
    0xc0000005（BEX/DEP，WER StackHash_2beb）硬崩；此前已有两次"强杀网关→
    游戏闪退"实测。机理：frida 会话先 detach 再 attach 同一活进程时，钩子
    卸载/重挂存在竞态，可能破坏进程内存，延迟几秒~几分钟后引爆访问违例。

    因此 **默认 kill=False 软停**：
      - **不调 /api/admin/shutdown、不 taskkill、不 session.detach()**
      - frida 会话常驻游戏、网关进程保留 → 下次 ensure_gateway 直接
        action=reuse（HTTP 在+attached+pid 匹配+lua 已捕获+script 健康），
        **永远不产生第二次 attach**，从根上消除该崩溃路径。
      - 只清理本组运行日志（gateway_run_<port>.log），保持"干净启动"观感。

    仅当 kill=True（GUI「彻底停网关(危险)」/ CLI --kill）才走旧硬停路径：
      1. 先调 /api/admin/shutdown 优雅 detach（严禁直接强杀，否则必崩游戏）；
      2. 端口仍被占（shutdown 失败/网关假死）→ taskkill 兜底；
      3. 轮询确认端口已释放。
    该路径本身仍有极低概率触发上述竞态，非必要不用。

    多组安全：只操作本组端口（group_config 解析），不影响其它组的网关。
    返回 (ok, info)。

    步骤（2026-08-27，硬停路径保留）：
      1. 先调 /api/admin/shutdown 优雅 detach；
      2. 端口仍被占 → taskkill 兜底；
      3. 轮询确认端口已释放；
      4. 清理本组网关运行日志。
    """
    port = _gw_port()
    info = {"port": port}

    def _clean_logs():
        # 清理本组网关运行日志，下次打开从零开始
        for name in (f"gateway_spawn_{port}.log", f"gw_{port}.log", f"gateway_run_{port}.log"):
            p = os.path.join(GATEWAY_DIR, name)
            try:
                if os.path.exists(p):
                    with open(p, "w", encoding="utf-8") as f:
                        f.write("")
                    info.setdefault("cleaned", []).append(name)
            except Exception as e:
                info.setdefault("clean_errors", []).append(f"{name}: {e}")

    if not kill:
        # ---- 软停：frida 会话常驻、网关进程保留，下次启动直接复用 ----
        _clean_logs()
        info.update(stopped=True, action="soft_stop",
                    note="会话保留：frida 未 detach、进程未杀；下次启动自动复用（防重复 attach 崩游戏）")
        if verbose:
            print("[gateway_guard] stop(soft):", info)
        return True, info

    # ---- 硬停（旧逻辑，kill=True 才走）：优雅 detach → 轮询释放 → taskkill 兜底 ----
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
    # 2026-08-28 提速：固定 sleep(1.0)+kill 改为"0.1s 步进轮询，端口释放即走，
    # 最多等 2s detach 宽限，仍在监听才强杀"。网关正常 shutdown 现在几十 ms
    # 内退出（gateway.py os._exit 延迟 0.5s→0.05s），快路径实测 <0.5s；
    # 宽限上限保留 2s 是安全底线（强杀正在 detach 的网关会崩游戏）。
    def _listener():
        return _listener_pid_on_port(port)

    t0 = time.time()
    while time.time() - t0 < 2.0:
        if _listener() is None:
            break
        time.sleep(0.1)
    else:
        lp = _listener()
        if lp:
            _kill_pid(lp)
            info["killed_pid"] = lp

    # 3. 轮询等待端口释放
    while time.time() - t0 < timeout:
        if _listener() is None:
            info["stopped"] = True
            break
        time.sleep(0.1)
    else:
        info["stopped"] = False
        info["error"] = f"端口 {port} 释放超时"

    _clean_logs()

    if verbose:
        print("[gateway_guard] stop(kill):", info)
    return bool(info.get("stopped")), info


if __name__ == "__main__":
    # CLI 入口：python core/gateway_guard.py [PID]           → 拉起/复用网关
    #           python core/gateway_guard.py --stop          → 软停（会话保留，默认）
    #           python core/gateway_guard.py --stop --kill   → 硬停（detach+杀进程，危险）
    if len(sys.argv) > 1 and sys.argv[1] == "--stop":
        _ok, _info = stop_gateway(verbose=True, kill=("--kill" in sys.argv))
    else:
        pid_arg = None
        if len(sys.argv) > 1 and sys.argv[1].isdigit():
            pid_arg = int(sys.argv[1])
        _ok, _info = ensure_gateway(pid=pid_arg, verbose=True)
    print("[gateway_guard]", "OK" if _ok else "FAIL", _info)
    raise SystemExit(0 if _ok else 1)
