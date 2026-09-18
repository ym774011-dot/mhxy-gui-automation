# -*- coding: utf-8 -*-
"""PP GUI — 胖子西游启动/播种/掉线重连一体机（2026-09-06）。

功能：
  1. 选择游戏路径，点击【启动队长】/【启动队员】拉起任意多个游戏实例；
  2. 实例出现在登录界面后自动播种 worker（pzxy_plant，通道 pzxy_p<pid>）；
  3. 【记录登录点击】开关：打开后用户手动登录一次，GUI 录下每次左键点击
     （相对游戏窗口客户区坐标+间隔），保存到配置供掉线重放；
  4. 监控线程守护：实例掉线（进程消失/窗口消失/标题退回登录界面）→ 自动
     重启游戏 → 补种 → 重放登录点击 → 等登录成功 → 按角色自动拉起任务脚本
     （队长=run_unlimited_test.py 完整跑批，队员=member_sell_loop.py 纯出售）。

用法：
    E:/py/python.exe tools/pp_gui.py

配置落盘：test_data/pp_gui_config.json（游戏路径/登录点击/实例角色）。
"""
import json
import os
import random
import re
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

from zhuagui_squad import (LOGGED_IN_RE, ROLE_RE, enum_game_windows,      # noqa: E402
                           plant, process_alive_for, running_squad_cmdlines_ex)
from library.pzxy_ipc import PzxyWorker                                    # noqa: E402
import squad_auto_team as sat                                              # noqa: E402
from tasks.library import warehouse_store as wh                            # noqa: E402
import ctypes                                                              # noqa: E402
from ctypes import wintypes                                                # noqa: E402

# ★2026-09-07 修复：squad_auto_team 用 importlib 从 tasks/library/ZGUI.py 加载
#   了 ZGUI 模块，pp_gui 直接复用该实例。此前 pp_gui 里所有 ZGUI.* 调用
#   （看门狗 _team_stats/面板开关、zhuagui_teleport、_reteam 读数）全部
#   NameError 崩溃并被 except 吞掉——看门狗整夜没工作过（pp_gui.log 实证：
#   每 15s 报 "name 'ZGUI' is not defined"）。
ZGUI = sat.ZGUI
# ★2026-09-07 同款修复：_watch_team_stats/_reteam 里用到的 find_hwnd_by_pid
#   也没有 import（01:29 实证 "[看门狗] 异常: name 'find_hwnd_by_pid' is
#   not defined"），与 ZGUI 一样复用 squad_auto_team 的实例。
find_hwnd_by_pid = sat.find_hwnd_by_pid

PYEXE = sys.executable
GATEWAY_PLANT = r"E:\DS\mhxy-mcp-gateway\tools\pzxy_plant.py"
RUN_UNLIMITED = os.path.join(ROOT, "run_unlimited_test.py")
MEMBER_LOOP = os.path.join(HERE, "member_sell_loop.py")
CONFIG_PATH = os.path.join(ROOT, "test_data", "pp_gui_config.json")

# ★2026-09-13 脚本方案注册表（GUI 选择器）：
#   选定方案后，【启动脚本】/恢复/看门狗补拉均按方案拉起对应脚本；
#   组队流程本身不变（始终先自动组队，成功后拉所选脚本）。
#   约定：leader 脚本放项目根目录，member 脚本放 tools/；
#   新方案（如打副本）只需加一项，脚本支持
#   --gateway/--role（队长）或 --pid/--gateway（队员）参数即可。
#   例： "打副本": {"leader": "dungeon_leader.py", "member": "dungeon_member.py"},
SCRIPT_PROFILES = {
    "抓鬼+闯关+顺手打": {
        "leader": "run_unlimited_test.py",
        "member": "member_sell_loop.py",
        # ★2026-09-14 方案内分组：队长脚本专属参数（仅本方案传）
        "leader_args": ["--timeout", "20", "--wait-dialog", "1.2"],
    },
    "全地图刷怪": {
        "leader": "run_unlimited_hunt.py",
        "member": "member_sell_loop.py",
        "leader_args": [],
    },
    # ★2026-09-14 独立门派闯关方案：只做门派闯关（队长脚本 run_chuangguan.py
    #   循环 CHUANGGUAN.run），不掺抓鬼/扫怪；队员沿用 member_sell_loop。
    "门派闯关": {
        "leader": "run_chuangguan.py",
        "member": "member_sell_loop.py",
        "leader_args": [],
    },
    # ★2026-09-16 独立副本方案：快捷传送→快捷副本→红字识别开始XX副本→
    #   点进入XX副本→自动战斗（战斗中不 CALL）。三副本，单副本一天两次。
    "打副本": {
        "leader": "run_fuben.py",
        "member": "member_sell_loop.py",
        "leader_args": [],
    },
}
DEFAULT_PROFILE_NAME = "抓鬼+闯关+顺手打"


def profile_scripts(profile):
    """返回 (leader脚本路径, member脚本路径)；未知方案回落默认。"""
    p = SCRIPT_PROFILES.get(profile) or SCRIPT_PROFILES[DEFAULT_PROFILE_NAME]
    return (os.path.join(ROOT, p["leader"]), os.path.join(HERE, p["member"]))


def profile_task_names(profile):
    """该方案两个脚本的 basename 集合（去 .py，进程匹配用）。"""
    p = SCRIPT_PROFILES.get(profile) or SCRIPT_PROFILES[DEFAULT_PROFILE_NAME]
    return {os.path.splitext(p["leader"])[0], os.path.splitext(p["member"])[0]}


def profile_leader_args(profile):
    """该方案队长脚本额外参数（★2026-09-14 用户定案：按方案分组传参，
    不再给所有方案硬塞 抓鬼专用 --timeout/--wait-dialog）。"""
    p = SCRIPT_PROFILES.get(profile) or SCRIPT_PROFILES[DEFAULT_PROFILE_NAME]
    return list(p.get("leader_args") or [])


def profile_all_task_names():
    """全部方案脚本 basename 并集（清理/打断残留脚本用）。"""
    out = set()
    for _p in SCRIPT_PROFILES.values():
        out.add(os.path.splitext(_p["leader"])[0])
        out.add(os.path.splitext(_p["member"])[0])
    return out
PORTS = [18091, 18092, 18093, 18094, 18095, 18096, 18097, 18098]

user32 = ctypes.windll.user32

# ---- 全局鼠标钩子（低级钩子保证每次点击必捕获，轮询会漏快点击） ----
WH_MOUSE_LL = 14
WM_LBUTTONDOWN = 0x0201


class _MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("pt", wintypes.POINT), ("mouseData", wintypes.DWORD),
                ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_void_p)]


def start_mouse_hook(on_click):
    """装低级鼠标钩子，左键按下回调 on_click(sx, sy)。返回 (proc, hook)。"""
    # 必须显式声明 CallNextHookEx 签名：默认 argtypes 会把 l_param 大指针值
    # 按 c_int 转换 → OverflowError，每次鼠标事件都抛异常，导致 GUI 卡死关不掉
    user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                      wintypes.WPARAM, wintypes.LPARAM]
    user32.CallNextHookEx.restype = ctypes.c_void_p
    HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_void_p, ctypes.c_int,
                                  wintypes.WPARAM, wintypes.LPARAM)

    def handler(n_code, w_param, l_param):
        if n_code == 0 and w_param == WM_LBUTTONDOWN:
            s = ctypes.cast(l_param, ctypes.POINTER(_MSLLHOOKSTRUCT)).contents
            try:
                on_click(s.pt.x, s.pt.y)
            except Exception:
                pass
        return user32.CallNextHookEx(None, n_code, w_param, l_param)

    proc = HOOKPROC(handler)
    hook = user32.SetWindowsHookExW(WH_MOUSE_LL, proc, None, 0)

    def pump():
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0):
            pass

    threading.Thread(target=pump, daemon=True).start()
    return proc, hook

# ---- 状态常量 ----
S_LAUNCH = "启动中"
S_PLANT = "播种中"
S_WAIT = "待登录"
S_ONLINE = "已登录"
S_RESTART = "重启中"
S_TEAM = "组队中"


def post_click(hwnd, x, y):
    """后台左键点击（与 ZGUI 同款：MOVE→DOWN→UP）。"""
    WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP = 0x0200, 0x0201, 0x0202
    MK = 1  # MK_LBUTTON
    lparam = (y & 0xFFFF) << 16 | (x & 0xFFFF)
    user32.PostMessageW(hwnd, WM_MOUSEMOVE, 0, lparam)
    time.sleep(0.03)
    user32.PostMessageW(hwnd, WM_LBUTTONDOWN, MK, lparam)
    time.sleep(0.06)
    user32.PostMessageW(hwnd, WM_LBUTTONUP, 0, lparam)


def window_class(h):
    buf = ctypes.create_unicode_buffer(64)
    user32.GetClassNameW(h, buf, 64)
    return buf.value


def hwnd_at_screen(sx, sy):
    """屏幕点下的 Galaxy2DEngine 窗口（无则 None）。"""
    h = user32.WindowFromPoint(wintypes.POINT(sx, sy))
    if h and window_class(h) == "Galaxy2DEngine":
        return h
    return None


def screen_to_client(hwnd, sx, sy):
    pt = wintypes.POINT(sx, sy)
    user32.ScreenToClient(hwnd, ctypes.byref(pt))
    return pt.x, pt.y


def proc_alive(pid):
    if not pid:
        return False
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if h:
        k32.CloseHandle(h)
        return True
    return False


def kill_task_process(pid):
    """杀掉该实例旧的任务脚本（按 cmdline 通道名匹配）。"""
    token = "pzxy_p%d" % pid
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
          "Where-Object { $_.CommandLine -match '%s' -and $_.ProcessId -ne %d } | "
          "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" % (token, os.getpid()))
    subprocess.run(["powershell", "-NoProfile", "-c", ps],
                   capture_output=True, text=True, timeout=30)


# ---------- 内存清理（2026-09-07 用户需求：5 开内存压力大时修剪工作集） ----------
class _PMCI(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t)]


def _ws_bytes(pid):
    """读进程工作集字节数；失败返回 None。"""
    h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED
    if not h:
        return None
    try:
        pmc = _PMCI()
        pmc.cb = ctypes.sizeof(pmc)
        if ctypes.windll.psapi.GetProcessMemoryInfo(h, ctypes.byref(pmc), pmc.cb):
            return int(pmc.WorkingSetSize)
        return None
    finally:
        ctypes.windll.kernel32.CloseHandle(h)


def trim_process_ws(pid):
    """EmptyWorkingSet 修剪进程工作集（不终止进程，页按需换回）。

    返回 (前字节, 后字节)；打不开进程/修剪失败返回 None。
    """
    PROCESS_SET_QUOTA = 0x0100
    h = ctypes.windll.kernel32.OpenProcess(0x1000 | PROCESS_SET_QUOTA, False, pid)
    if not h:
        return None
    try:
        before = _ws_bytes(pid) or 0
        if not ctypes.windll.psapi.EmptyWorkingSet(h):
            return None
        after = _ws_bytes(pid) or 0
        return (before, after)
    finally:
        ctypes.windll.kernel32.CloseHandle(h)


def human_bytes(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return "%.0f%s" % (n, unit) if unit in ("B", "KB") else "%.1f%s" % (n, unit)
        n /= 1024.0
    return "%dGB" % n


# ---------- 弹窗检测与自动点掉（2026-09-07 用户需求） ----------
# 场景：崩溃弹窗（应用程序错误/WER 停止工作）不点掉，进程就卡着不退，
# 掉线闭环没法重新拉起游戏。策略：按进程名找弹窗宿主（游戏本尊 + WerFault），
# 枚举其 #32770 对话框，优先点「确定/关闭程序」按钮（PostMessage BM_CLICK）。
_POPUP_IMAGES = {"胖子西游.exe", "werfault.exe"}
_BTN_PREFER = ("确定", "关闭程序", "关闭", "是", "ok", "close")


def _pids_by_image():
    """按镜像名取弹窗宿主 PID 集合（胖子西游 + WerFault）。"""
    k32 = ctypes.windll.kernel32
    psapi = ctypes.windll.psapi
    arr = (wintypes.DWORD * 4096)()
    cb = wintypes.DWORD()
    if not psapi.EnumProcesses(ctypes.byref(arr), ctypes.sizeof(arr),
                               ctypes.byref(cb)):
        return set()
    n = min(4096, cb.value // ctypes.sizeof(wintypes.DWORD))
    out = set()
    for i in range(n):
        pid = arr[i]
        if not pid:
            continue
        h = k32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED
        if not h:
            continue
        try:
            buf = ctypes.create_unicode_buffer(512)
            size = wintypes.DWORD(512)
            # ★本机 kernel32 无 K32QueryFullProcessImageNameW 导出（实测），
            #   用无前缀版 QueryFullProcessImageNameW（Vista+ 内核32 自带）
            if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                img = (buf.value or "").rsplit("\\", 1)[-1].lower()
                if img in _POPUP_IMAGES:
                    out.add(int(pid))
        except Exception:
            pass
        finally:
            k32.CloseHandle(h)
    return out


def _enum_dialogs_of(pids):
    """枚举这些进程名下可见的 #32770 对话框 → [(hwnd, pid, 标题)]。"""
    user32 = ctypes.windll.user32
    hits = []
    PROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    def cb(h, _lp):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
        if pid.value in pids and user32.IsWindowVisible(h):
            cls = ctypes.create_unicode_buffer(64)
            user32.GetClassNameW(h, cls, 64)
            if cls.value == "#32770":
                n = user32.GetWindowTextLengthW(h)
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(h, buf, n + 1)
                hits.append((int(h), int(pid.value), buf.value))
        return True

    user32.EnumWindows(PROC(cb), 0)
    return hits


def _dialog_text(hwnd):
    """抓对话框内所有可见 Static 子控件的文本（诊断崩溃/弹窗原因用）。"""
    user32 = ctypes.windll.user32
    texts = []
    CB = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    def cb(h, _lp):
        cls = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(h, cls, 64)
        if cls.value == "Static" and user32.IsWindowVisible(h):
            buf = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(h, buf, 512)
            if buf.value.strip():
                texts.append(buf.value.strip())
        return True

    cbref = CB(cb)
    user32.EnumChildWindows(hwnd, cbref, 0)
    return " | ".join(texts)[:180]


def _dismiss_popup(hwnd):
    """点掉对话框：枚举子按钮，优先「确定/关闭程序/关闭」，BM_CLICK。"""
    user32 = ctypes.windll.user32
    buttons = []
    PROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    def cb(h, _lp):
        cls = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(h, cls, 64)
        if cls.value == "Button" and user32.IsWindowVisible(h):
            txt = ctypes.create_unicode_buffer(128)
            user32.GetWindowTextW(h, txt, 128)
            buttons.append((int(h), txt.value or ""))
        return True

    user32.EnumChildWindows(hwnd, PROC(cb), 0)
    if not buttons:
        return False

    def score(t):
        t = t.strip().lower()
        for i, p in enumerate(_BTN_PREFER):
            if p in t:
                return i
        return 99

    buttons.sort(key=lambda b: score(b[1]))
    user32.PostMessageW(buttons[0][0], 0x00F5, 0, 0)  # BM_CLICK
    return True


# ---------- 卫生机制（★残留自洁，用户 2026-09-10 定案保留） ----------
_IPC_TMP_DIR = r"E:\DS\tmp"          # pzxy IPC 文件目录（与 pzxy_ipc 默认一致）
_IPC_STALE_S = 24 * 3600.0           # 死 PID 文件保留期：整组 mtime 超 24h 才删
_TP_NIL_GRACE_S = 75.0               # tp=nil 宽限期：worker 存活时等自愈/重连再杀
_HYGIENE_INTERVAL_S = 24 * 3600.0    # 卫生循环周期
_LOG_ROTATE_BYTES = 20 * 1024 * 1024  # 日志轮转阈值 20MB
_IPC_PID_RE = re.compile(r"pzxy_p(\d+)_")


def _hygiene_scan(managed_pids, log=None):
    """IPC 死文件清理 + 日志轮转。返回 (cleaned, rotated)。

    - E:\\DS\\tmp\\pzxy_p<pid>_*：PID 不在托管实例里 且 整组 mtime 超 24h
      且 **进程已死** → 整组删除。三重保护：托管 PID 不动、新鲜文件不动、
      活进程（如独立编排器的 worker）绝不动。
    - pp_gui.log / logs/automation.log 超 20MB → 改名 .bak；被占用
      （常驻 FileHandler，WinError 32）时复制到 .bak 后原地截断——追加
      模式写者下次写入定位新 EOF，不产生空洞。
    """
    cleaned = rotated = 0
    now = time.time()
    groups = {}
    try:
        for f in os.listdir(_IPC_TMP_DIR):
            m = _IPC_PID_RE.match(f)
            if not m:
                continue
            p = os.path.join(_IPC_TMP_DIR, f)
            try:
                mt = os.path.getmtime(p)
            except OSError:
                continue
            groups.setdefault(int(m.group(1)), []).append((p, mt))
    except OSError:
        pass
    for pid, files in groups.items():
        if pid in managed_pids:
            continue
        if any(now - mt < _IPC_STALE_S for _p, mt in files):
            continue
        if proc_alive(pid):
            continue      # ★进程仍活着（如独立编排器的 worker）：绝不删
        for p, _mt in files:
            try:
                os.remove(p)
                cleaned += 1
            except OSError:
                pass
    for lp, limit in ((os.path.join(ROOT, "pp_gui.log"), _LOG_ROTATE_BYTES),
                      (os.path.join(ROOT, "logs", "automation.log"),
                       _LOG_ROTATE_BYTES)):
        try:
            if os.path.getsize(lp) > limit:
                os.replace(lp, lp + ".bak")
                rotated += 1
        except OSError:
            # 被常驻句柄持有（WinError 32）→ copy+truncate 兜底
            try:
                shutil.copyfile(lp, lp + ".bak")
                with open(lp, "w"):
                    pass
                rotated += 1
            except OSError as e:
                if log:
                    log("[卫生] 日志轮转兜底也失败: %s → %s" % (lp, e))
        except Exception as e:
            if log:
                log("[卫生] 日志轮转异常: %s → %s" % (lp, e))
    if log and (cleaned or rotated):
        log("[卫生] 清理旧 IPC 文件 %d 个，日志轮转 %d 个" % (cleaned, rotated))
    return cleaned, rotated


class Instance:
    _seq = 0
    _role_count = {}

    def __init__(self, role, pid=None, name=None, status=S_LAUNCH, title=""):
        Instance._seq += 1
        Instance._role_count[role] = Instance._role_count.get(role, 0) + 1
        self.seq = Instance._seq
        self.role = role            # 'leader' | 'member'
        self.slot = "%s#%d" % (role, Instance._role_count[role])  # 录制键
        self.pid = pid
        self.name = name or ("p%d" % pid if pid else "")
        self.status = status
        self.title = title
        self.note = ""

    @property
    def role_cn(self):
        return "队长" if self.role == "leader" else "队员"



TEAM_SIZE = 5   # ★2026-09-13 用户定案：组队必须满 5 人才算成功
class PPApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PP GUI — 胖子西游 启动/播种/掉线重连一体机")
        self.geometry("860x620")
        self.minsize(760, 520)

        self.cfg = self._load_cfg()
        self.script_profile = (self.cfg.get("script_profile")
                               or DEFAULT_PROFILE_NAME)
        self.lock = threading.Lock()
        self.instances = []
        self.logq = []
        self.recording_target = None   # 正在录制的实例（None=未录制）
        self._last_click_t = 0.0
        self._prev_btn = False
        self._port_i = 0
        # 组队协调：GUI 登录后只做播种+掉线监控；【启动脚本】才组队+拉任务
        self.cap_world = None       # 队长就绪后的世界坐标 [139,80]
        self.team_done = False      # 组队阶段结束
        self.scripts_started = False  # 已点过【启动脚本】（之后重登=自动归队）
        self.teamflow_running = False
        # 全局鼠标钩子：左键点击进队列，录制时消费
        import collections
        self._click_q = collections.deque(maxlen=80)
        self._hook_proc, self._hook = start_mouse_hook(self._on_global_click)
        # ★队伍完整性看门狗：队长侧随时判定队员数，缺员打断抓鬼→补组队→满员恢复
        self._team_watch_stop = threading.Event()
        self._watch_interrupted = False   # 当前处于"缺员已打断抓鬼"状态
        self._store_running = False       # 存仓流程进行中（挂起巡检/补组）
        self._reteam_running = False
        self._task_dead_n = {}            # 任务脚本巡检：连续判死计数（pid→n）
        self._watch_started = False
        # ★残留自洁循环（启动 20s 首轮，之后每 24h 一轮）
        threading.Thread(target=self._hygiene_loop, daemon=True,
                         name="hygiene").start()
        self._rejoining = set()           # 正在归队流程的实例 pid（防双驱动）
        self.paused = False               # ★暂停接管：True=自动化全面撒手
        # ★2026-09-09 tp 健康检查状态：pid -> 连续消失计数（服务器抹 tp 时
        #   进程活着/标题在线但 Lua 主状态亡，任务脚本会无限空转——用户指令：
        #   这种情况 GUI 直接杀游戏重启）
        self._tp_fail = {}
        self._tp_nil_since = {}           # tp=nil 宽限计时（worker 存活时等自愈）
        self._tp_tick = 0

        # ★2026-09-07 可观测性：squad_auto_team 的 _log 原本只 print 到
        #   stdout（GUI 无控制台 → 全程丢失）。组队/走位/建队每一步的内部
        #   日志因此不可见（只能靠肉眼观察客户端），桥接到 GUI 日志落地。
        self._bridge_sat_log()

        self._build_ui()
        threading.Thread(target=self._monitor_loop, daemon=True).start()
        threading.Thread(target=self._auto_trim_loop, daemon=True).start()
        threading.Thread(target=self._popup_loop, daemon=True).start()
        self.after(200, self._tick)

    def _bridge_sat_log(self):
        """把 squad_auto_team 的日志接进 GUI 日志（写 pp_gui.log）。

        建队/走位/申请等内部步骤原本只 print，GUI 无控制台时全部丢失，
        故障只能靠肉眼观察。此处包装 sat._log 同时落到 GUI 日志。
        """
        orig = getattr(sat, "_log", None)
        if orig is None:
            return

        def _bridge(msg, _orig=orig):
            try:
                _orig(msg)
            except Exception:
                pass
            try:
                self._log("[sat] %s" % (msg,))
            except Exception:
                pass

        sat._log = _bridge
        self._log("squad_auto_team 日志已桥接到 GUI（组队内部步骤可见）")

    # ---------- 配置 ----------
    def _load_cfg(self):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"game_path": "", "login_clicks": []}

    def _save_cfg(self):
        try:
            os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(self.cfg, f, ensure_ascii=False, indent=1)
        except Exception as e:
            self._log("配置保存失败: %s" % e)

    # ---------- UI ----------
    def _build_ui(self):
        top = ttk.Frame(self)
        top.pack(fill="x", padx=8, pady=6)
        ttk.Label(top, text="游戏路径:").pack(side="left")
        self.var_path = tk.StringVar(value=self.cfg.get("game_path", ""))
        ttk.Entry(top, textvariable=self.var_path).pack(
            side="left", fill="x", expand=True, padx=4)
        ttk.Button(top, text="浏览…", width=8,
                   command=self._browse).pack(side="left")
        ttk.Button(top, text="全部停止", width=10,
                   command=self._stop_all).pack(side="left", padx=4)
        # ★2026-09-07 内存清理：EmptyWorkingSet 修剪游戏进程工作集（不杀进程）
        ttk.Button(top, text="清理内存", width=10,
                   command=self._trim_memory).pack(side="left", padx=4)
        self.var_auto_trim = tk.BooleanVar(
            value=bool(self.cfg.get("auto_trim", False)))
        ttk.Checkbutton(top, text="每30分钟自动", variable=self.var_auto_trim,
                        command=self._toggle_auto_trim).pack(side="left")

        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=8, pady=2)
        self.btn_leader = ttk.Button(bar, text="启动队长", width=12,
                                     command=lambda: self._launch("leader"))
        self.btn_leader.pack(side="left")
        self.btn_member = ttk.Button(bar, text="启动队员", width=12,
                                     command=lambda: self._launch("member"))
        self.btn_member.pack(side="left", padx=6)
        ttk.Label(bar, text="脚本方案:").pack(side="left")
        self.var_profile = tk.StringVar(value=self.script_profile)
        self.cb_profile = ttk.Combobox(bar, textvariable=self.var_profile,
                                       values=list(SCRIPT_PROFILES.keys()),
                                       state="readonly", width=18)
        self.cb_profile.pack(side="left", padx=(0, 8))
        self.cb_profile.bind("<<ComboboxSelected>>", self._on_profile_sel)
        ttk.Button(bar, text="启动脚本", width=12,
                   command=self._start_all_tasks).pack(side="left", padx=6)
        # ★2026-09-07 暂停/恢复：暂停=人工接管（停任务脚本+冻结看门狗/掉线闭环）；
        #   恢复=跳过组队直接拉任务脚本（与【启动脚本】的组队流程区分开）
        self.btn_pause = ttk.Button(bar, text="⏸ 暂停接管", width=12,
                                    command=self._toggle_pause)
        self.btn_pause.pack(side="left", padx=6)
        # 录制：先在列表选中实例，再点此按钮；该号登录成功自动停止
        self.btn_rec = ttk.Button(bar, text="录制登录点击", width=14,
                                  command=self._toggle_rec)
        self.btn_rec.pack(side="left", padx=12)
        self.lbl_rec = ttk.Label(bar, text="未选中实例")
        self.lbl_rec.pack(side="left")
        ttk.Button(bar, text="清空选中录制", width=12,
                   command=self._clear_rec).pack(side="left", padx=4)

        cols = ("pid", "role", "status", "title", "note")
        self.tree = ttk.Treeview(self, columns=cols, show="headings", height=12)
        for c, w, t in (("pid", 80, "PID"), ("role", 60, "角色"),
                        ("status", 80, "状态"), ("title", 320, "窗口标题"),
                        ("note", 240, "备注")):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor="w")
        self.tree.pack(fill="both", expand=True, padx=8, pady=4)

        self.txt = tk.Text(self, height=9, state="disabled", font=("Consolas", 9))
        self.txt.pack(fill="both", padx=8, pady=6)

    def _on_profile_sel(self, _ev=None):
        """脚本方案选择：只影响之后【启动脚本】/恢复/补拉拉起的脚本，
        已运行的脚本按原方案跑到结束，不打断。"""
        v = self.var_profile.get()
        if v not in SCRIPT_PROFILES:
            return
        self.script_profile = v
        self.cfg["script_profile"] = v
        self._save_cfg()
        self._log("脚本方案 → %s（下次拉起任务时生效）" % v)

    def _browse(self):
        p = filedialog.askopenfilename(
            title="选择游戏(或多开器) exe",
            filetypes=[("可执行文件", "*.exe"), ("全部", "*.*")])
        if p:
            self.var_path.set(p)
            self.cfg["game_path"] = p
            self._save_cfg()

    # ---------- 录制（按实例单独记录，该号登录成功自动停止） ----------
    def _inst_by_seq(self, seq):
        with self.lock:
            for i in self.instances:
                if i.seq == seq:
                    return i
        return None

    def _clicks_store(self):
        return self.cfg.setdefault("login_clicks_by_slot", {})

    def _on_global_click(self, sx, sy):
        """鼠标钩子回调（钩子线程调用）：入队等 UI 线程消费。"""
        self._click_q.append((sx, sy))

    def _toggle_rec(self):
        if self.recording_target is not None:
            self._stop_rec("手动停止")
            return
        sel = self.tree.selection()
        inst = self._inst_by_seq(int(sel[0])) if sel else None
        if inst is None:
            # 没选中：自动挑第一个"待登录且未录制"的实例
            with self.lock:
                cands = [i for i in self.instances
                         if i.status in (S_WAIT, S_PLANT)
                         and not self._clicks_store().get(i.slot)]
            if not cands:
                self._log("没有可录制的实例（请先启动游戏并播种，或选中列表实例）")
                return
            inst = cands[0]
            self._log("未选中行，自动选择 %s（p%s）" % (inst.slot, inst.pid))
        self.recording_target = inst
        self.btn_rec.config(text="停止录制(%s)" % inst.slot)
        n = len(self._clicks_store().get(inst.slot, []))
        self.lbl_rec.config(text="录制中: %s（已录 %d 步）" % (inst.slot, n))
        self._log("开始录制 %s 的登录点击——到该号窗口手动登录一次，"
                  "其登录成功后自动停止" % inst.slot)

    def _stop_rec(self, reason):
        inst = self.recording_target
        self.recording_target = None
        self.btn_rec.config(text="录制登录点击")
        n = len(self._clicks_store().get(inst.slot, [])) if inst else 0
        self.lbl_rec.config(text="未选中实例")
        self._save_cfg()
        self._log("录制停止（%s）：%s 共 %d 步" % (reason, inst.slot if inst else "?", n))

    def _clear_rec(self):
        sel = self.tree.selection()
        if not sel:
            self._log("请先在列表中选中要清空录制的实例")
            return
        inst = self._inst_by_seq(int(sel[0]))
        if inst is None:
            return
        self._clicks_store().pop(inst.slot, None)
        self._save_cfg()
        self._log("已清空 %s 的登录点击录制" % inst.slot)

    # ---------- 启动实例 ----------
    def _launch(self, role):
        gp = self.var_path.get().strip()
        if not gp or not os.path.exists(gp):
            messagebox.showwarning("PP GUI", "请先选择有效的游戏路径")
            return
        self.cfg["game_path"] = gp
        self._save_cfg()
        try:
            CREATE_NO_WINDOW = 0x08000000
            popen = subprocess.Popen([gp], cwd=os.path.dirname(gp),
                                     creationflags=CREATE_NO_WINDOW)
        except Exception as e:
            messagebox.showerror("PP GUI", "启动失败: %s" % e)
            return
        inst = Instance(role, pid=popen.pid)
        with self.lock:
            self.instances.append(inst)
        self._log("已启动%s进程 PID=%s，等待登录界面窗口…"
                  % ("队长" if role == "leader" else "队员", popen.pid))
        threading.Thread(target=self._wait_login_window,
                         args=(inst,), daemon=True).start()

    def _wait_login_window(self, inst):
        """等游戏窗口出现并播种（播种成功后才标记可用，用户再去登录）。"""
        deadline = time.time() + 120
        while time.time() < deadline:
            time.sleep(1.0)
            if not proc_alive(inst.pid):
                # 启动器型 exe：主进程退出但真客户端窗口已出现 → 收养
                adopted = self._maybe_adopt(inst)
                if adopted:
                    if "([0])" in adopted[2]:
                        self._do_plant(inst, adopted[1])
                    elif LOGGED_IN_RE.search(adopted[2]):
                        inst.status = S_ONLINE
                        self._after_login(inst)
                    return
                inst.status, inst.note = S_LAUNCH, "进程消失，等监控重启"
                return
            for pid, hwnd, title in enum_game_windows():
                if pid == inst.pid:
                    inst.title = title
                    if "([0])" in title:
                        self._do_plant(inst, hwnd)
                        return
                    if LOGGED_IN_RE.search(title):
                        # 已经是登录好的窗口（异常情况），直接当在线
                        inst.status, inst.note = S_ONLINE, "窗口已登录"
                        self._after_login(inst)
                        return
        inst.status, inst.note = S_LAUNCH, "120s 未见到窗口"

    def _do_plant(self, inst, hwnd):
        inst.status, inst.note = S_PLANT, ""
        self._log("p%d 检测到登录界面，开始播种…" % inst.pid)
        attempt, ok, why, retried = 0, False, "", False
        while True:
            attempt += 1
            ok, why = self._plant_try(inst)
            retried = attempt > 1
            if ok:
                break
            # ★2026-09-07 失败原因落日志（此前只打控制台，pythonw 下丢失）
            if attempt == 1:
                self._log("p%d 播种失败：%s（3s 后重试）" % (inst.pid, why))
                inst.status, inst.note = S_PLANT, "播种失败，重试中"
                time.sleep(3)
                continue
            # ★2026-09-08 修复：播种失败后实例曾永久卡在 S_PLANT——
            #   _monitor_once 对该状态无条件跳过，无人再管（10:09 p11728
            #   四连败后停在登录界面、队伍 4/5 空转实锤）。改为低频重试环：
            #   每 60s 再播种一次（最多 10 次）；期间进程消失/已登录/窗口
            #   不在登录界面 → 退出交回监控，绝不悬死。
            self._log("p%d 播种失败(第%d次)：%s（60s 后再试，窗口登录/消失则停）"
                      % (inst.pid, attempt, why))
            inst.status, inst.note = S_PLANT, "播种失败，低频重试中"
            if attempt > 11:
                self._log("p%d 播种连续 11 次失败，放弃（保持登录界面，等掉线闭环重启）"
                          % inst.pid)
                break
            rearm = time.time() + 60
            while time.time() < rearm:
                time.sleep(2)
                if not proc_alive(inst.pid):
                    return
                w = next((t for p, _h, t in enum_game_windows() if p == inst.pid), None)
                if w and LOGGED_IN_RE.search(w):
                    inst.status, inst.note = S_WAIT, "手动登录，免播种"
                    self._log("p%d 等待期间检测到已登录 → 交回监控" % inst.pid)
                    return
                if w and "([0])" not in w:
                    return   # 窗口状态变了，交回监控判定
            hwnd = next((h for p, h, t in enum_game_windows()
                         if p == inst.pid and "([0])" in t), None)
            if hwnd is None:
                return
        if ok:
            inst.status, inst.note = S_WAIT, "播种成功" + ("(重试)" if retried else "")
            self._log("p%d %s ✓" % (inst.pid, inst.note))
            # ★2026-09-07 修复：登录点击重放必须覆盖"重试成功"路径——旧代码
            #   只在首次成功分支里做，重试成功后实例停在登录界面永不登录
            #   （01:34 四连 / 10:21 共 5 例实锤）。
            if self._clicks_store().get(inst.slot):
                threading.Thread(target=self._replay_login,
                                 args=(inst, hwnd), daemon=True).start()
            else:
                self._log("p%d 等待手动登录（%s 无登录录制：选中该实例点【录制登录点击】"
                          "后手动登录一次即可）" % (inst.pid, inst.slot))

    def _plant_try(self, inst):
        """单次播种尝试；每次换一个端口（首试失败可能是端口/网关残留竞争）。"""
        port = PORTS[self._port_i % len(PORTS)]
        self._port_i += 1
        return plant(inst.pid, inst.name, port)

    def _replay_login(self, inst, hwnd):
        """重放该实例自己录制的登录点击（掉线重登录闭环）。"""
        clicks = self._clicks_store().get(inst.slot) or []
        if not clicks:
            self._log("p%d 没有 %s 的登录录制，等待手动登录" % (inst.pid, inst.slot))
            return
        self._log("p%d 重放 %s 登录点击 %d 步…" % (inst.pid, inst.slot, len(clicks)))
        for c in clicks:
            delay = min(max(float(c.get("dt", 0.6)), 0.4), 4.0)
            time.sleep(delay)
            if not proc_alive(inst.pid):
                return
            post_click(hwnd, int(c["x"]) + random.randint(-2, 2),
                       int(c["y"]) + random.randint(-2, 2))
        self._log("p%d 登录点击重放完毕，等待进入场景…" % inst.pid)

    # ---------- 组队协调 ----------
    # GUI 登录后只做播种+掉线监控；【启动脚本】= 组队→天覆阵→按角色拉任务。
    # 脚本开工后若实例掉线重登，自动归队（传送+申请）并补拉任务。
    def _after_login(self, inst):
        if not self.scripts_started:
            inst.note = "已登录，待【启动脚本】"
            return
        # 脚本已开工：这是掉线重登 → 自动归队 + 补拉任务
        inst.status, inst.note = S_TEAM, "重登回归：传送+归队"
        threading.Thread(target=self._rejoin_flow,
                         args=(inst,), daemon=True).start()

    def _find_cap_world(self):
        """从在线队长客户端读队长世界坐标（★read_pos_closed 保证面板关闭）。"""
        with self.lock:
            leaders = [i for i in self.instances
                       if i.role == "leader" and i.status == S_ONLINE]
        if not leaders:
            return None
        return sat.read_pos_closed(find_hwnd_by_pid(leaders[0].pid),
                                   "file://pzxy_p%d" % leaders[0].pid)

    def _leader_live(self, want_pos=False):
        """取“真正在线的队长”。返回 pid，或 (pid, 坐标)。

        ★2026-09-15 用户实锤（pp_gui.log 12:45:19～12:49:59，连刷 4 分半）：
          队长侧每 20s 反复打印“联动信号已发布: 队长 p18368 就位 (2778, 1601)”，
          队员侧同步每 20s 打印“联动校验未过（队长掉线/重启中）”。
          两边都在说真话，却互相矛盾。
        根因：旧判据用 `i.status == S_ONLINE`（字符串标签）断生死，但组队流程
          一进阶段1 就把队长标成 S_TEAM（“组队中”，第 1014 行），要等流程走
          到 _finish_tasks:1349 才回写 S_ONLINE。而本次队员进程死掉重启、成员卡在
          4/5 < 5，approve_loop 永不满足退出条件 → 流程永不收尾 → 标签永不回写
          → 归队队员被误判队长掉线 → 无法归队 → 成员数永远到不了 5
          → 自锁死循环，不修不可能自愈。
        更糟的是：旧写法第①条直接 return，后两条（信号 pid 比对、
          坐标 ±60 校验）根本没机会执行——队员压根不去读队长坐标，
          仅凭一个标签就判死刑。信号通道完全逆畅，是校验器自己把门
          焊死了。
        修法：不用状态标签断生死，改读队长的客观实时事实——窗口存活 +
          坐标可读。status 属于“流程推进标记”，不应当“在线真相”。
        want_pos=True 时同时返回已读到的坐标，供 _leader_link_ok 第③条
          复用，免同一坐标读两次（省一条 Lua IPC 往返，也避免两处不一致）。
        """
        with self.lock:
            lds = [i for i in self.instances if i.role == "leader"]
        if not lds:
            return (None, None) if want_pos else None
        lds.sort(key=lambda i: i.status != S_ONLINE)
        for _l in lds:
            if find_hwnd_by_pid(_l.pid) is None:
                continue
            if _l.status in (S_RESTART, S_LAUNCH, S_PLANT, S_WAIT):
                continue
            _p = sat.read_pos_closed(find_hwnd_by_pid(_l.pid),
                                     "file://pzxy_p%d" % _l.pid)
            if _p is None:
                continue
            if _l.status != S_ONLINE:
                self._log("[联动] 队长 p%d 状态为“%s”但实际在线（窗口+坐标可读）→ 放行联动"
                          % (_l.pid, _l.status))
            return (_l.pid, _p) if want_pos else _l.pid
        return (None, None) if want_pos else None

    def _leader_link_ok(self, cand):
        """联动信号三重校验（★2026-09-10 用户重申的铁律）：

        ① 当前有在线队长；② 信号由这位队长发布（旧队长/换队长的信号拒收）；
        ③ 这位队长**此刻**就位在大唐官府 [139,80] ±3 格（实时读坐标，不信
        30min 内的旧信号——队长掉线/没到锚点时队员绝不传送）。
        返回 (True, leader_pid) 或 (False, 原因串)。

        ★2026-09-15：第①条从“查 status 标签”改为 _leader_live()（查窗口/坐标
        客观事实）——否则队长挂着 S_TEAM 时会被误判“掉线/重启中”，
        导致后两条校验校不到、信号反复重发也无人接。
        ★2026-09-15：改用 _leader_live(want_pos=True)，复用它已读到的坐标，
        避免同一坐标读两次（少一条 Lua IPC 往返，也不会两处不一致）。
        """
        _lp, lpos = self._leader_live(want_pos=True)
        if _lp is None:
            return False, "队长掉线/重启中"
        if int(cand.get("leader_pid", -1)) != _lp:
            return False, "信号非当前队长 p%d 发布" % _lp
        if lpos is None:
            return False, "队长坐标读不到"
        if (abs(sat.CAP_TARGET[0] - lpos[0]) > 60
                or abs(sat.CAP_TARGET[1] - lpos[1]) > 60):
            return False, "队长未到 [139,80]（现 %s）" % (lpos,)
        return True, _lp

    def _rejoin_flow(self, inst):
        try:
            if self.paused:
                self._log("p%d 暂停中，跳过自动归队" % inst.pid)
                return
            if inst.pid in self._rejoining:
                return
            self._rejoining.add(inst.pid)
            if inst.role == "leader":
                sat.prep_leader(inst.pid)
            else:
                # ★2026-09-09 用户定案（队长先行联动）：队员没有联动信号一律
                #   不动——等队长到大唐官府[139,80]就位且建队成功后发布的
                #   信号（_reteam/组队流程发布），收到才去进队伍。队长掉线/
                #   未就位期间原地干等，绝不自行传送/申请（旧代码 cap 读不到
                #   还无条件传送队员，已废除）。
                # ★2026-09-15：同 _leader_link_ok 的修法——判“队长在不在”
                #   不能靠 status 标签（队长组队期间挂 S_TEAM 会被误判掉线）。
                _lp = self._leader_live()
                self._log("p%d 重登待命：等队长联动信号（队长%s未就位/未建队则不动）"
                          % (inst.pid, ("p%d " % _lp) if _lp else ""))
                deadline = time.time() + 3600.0
                link, _lp = None, None
                while link is None and time.time() < deadline:
                    cand = sat.read_link()
                    if cand is not None:
                        # ★2026-09-10 三重校验：当前在线队长 + 信号确为其发布
                        #   + 队长此刻就位 [139,80]±3格。任一不过 → 继续等，
                        #   绝不传送（队长没到队员不动，躺平等信号）。
                        ok, info = self._leader_link_ok(cand)
                        if ok:
                            link, _lp = cand, info
                            break
                        self._log("p%d 联动校验未过（%s）→ 继续等，不传送"
                                  % (inst.pid, info))
                    time.sleep(20.0)
                if link is None:
                    self._log("p%d 等队长联动超时（1h），放弃本轮归队" % inst.pid)
                    return
                self._log("p%d 队长已就位 [139,80] 且建队成功 → 传送+申请归队"
                          % inst.pid)
                sat.member_tp_and_apply(inst.pid, link["cap_world"], tries=3,
                                        tp_first=True, leader_pid=_lp)
        except Exception as e:
            self._log("p%d 归队异常: %s" % (inst.pid, e))
        finally:
            self._rejoining.discard(inst.pid)
            inst.status, inst.note = S_ONLINE, "重登完成"
            if not self.paused:
                time.sleep(2.0)
                self._spawn_task(inst, skip_team=True)

    def _start_all_tasks(self):
        """【启动脚本】= 组队（传送/走位/申请/批准/天覆阵）→ 按角色拉任务。"""
        if self.paused:
            self._log("[暂停中] 请先点【恢复挂机】再启动脚本")
            return
        if self.teamflow_running:
            self._log("组队流程进行中，请稍候…")
            return
        with self.lock:
            insts = [i for i in self.instances if i.status == S_ONLINE]
        if not insts:
            self._log("没有已登录实例，无法启动脚本")
            return
        self.teamflow_running = True
        threading.Thread(target=self._teamflow_and_tasks,
                         args=(insts,), daemon=True).start()

    def _teamflow_and_tasks(self, insts):
        """★多线程并行版：阶段内各实例并行，阶段间保持顺序铁律。

        ★2026-09-09 队长先行联动（用户定案）：队长到大唐官府[139,80]建队
        成功后发布联动信号，队员凭信号才行动；没有信号一律原地等。
        阶段1 队长先行 传送+走位[139,80]（走位途中不点组队图标）
        阶段2 建队 → 发布联动信号
        阶段3 队员并行 传送+申请入队（收到联动信号才动）
        阶段4 队长批准至满员 → 天覆阵
        任一阶段失败的兜底与旧版一致：降级为"只拉任务不组队"。
        """
        try:
            leader = next((i for i in insts if i.role == "leader"), None)
            members = [i for i in insts if i.role != "leader"]

            # ---- 阶段0：满员检查（2026-09-07 用户规则）----
            #   先 Lua 读队伍信息：已有队伍且满员 → 跳过整个组队流程直接跑
            #   任务（重复组队会白传送/点面板，还对在队成员传送无效）。
            if leader is not None:
                lw = "file://pzxy_p%d" % leader.pid
                st = ZGUI.team_stats_topbar(lw)
                if st is None:
                    st = ZGUI._team_stats(lw)
                mem = st[0] if st else -1
                if mem >= TEAM_SIZE:
                    self._log("[autoTeam] Lua 队伍读数 %d/%d 已满员 → 跳过组队，直接执行任务"
                              % (mem, TEAM_SIZE))
                    self._finish_tasks(insts)
                    return
                self._log("[autoTeam] Lua 队伍读数 %d/%d 未满员 → 走组队流程"
                          % (mem, TEAM_SIZE))

            # ---- 阶段1：队长先行（★2026-09-09 用户定案：队长没到，队员不动）----
            #   废除旧"阶段1 全员传送"——队员传送也是"动"，必须等队长就位+
            #   建队成功的联动信号。队长不在线 = 队员原地待命，只拉任务。
            if leader is None:
                self._log("[autoTeam] 无队长在线，队员原地待命（等队长联动），只拉任务")
                self._finish_tasks(insts)
                return
            leader.status, leader.note = S_TEAM, "走位[139,80]"
            self._log("[autoTeam] 阶段1: 队长先行 传送+走位[139,80]")
            cap = sat.prep_leader(leader.pid)
            if cap is None:
                self._log("[autoTeam] 队长准备失败，20s 后重试一次")
                time.sleep(20)
                cap = sat.prep_leader(leader.pid)
            if cap is None:
                self._log("[autoTeam] 队长走位失败，只拉任务不组队")
                self._finish_tasks(insts)
                return
            self.cap_world = cap

            # ---- 阶段2：建队 → 成功即发布联动信号（队员行动依据）----
            self._log("[autoTeam] 阶段2: 建队")
            if not sat.create_team(leader.pid, cap):
                self._log("[autoTeam] 建队失败，重试一次")
                if not sat.create_team(leader.pid, cap):
                    self._log("[autoTeam] 建队失败，只拉任务不组队（不发布联动信号）")
                    self._finish_tasks(insts)
                    return
            sat.publish_link(leader.pid, cap)

            # ---- 阶段3：队员并行 传送+申请（联动信号已发布，此刻才允许动）----
            self._log("[autoTeam] 阶段3: %d 名队员并行传送+申请入队" % len(members))

            def _apply_one(m):
                m.status, m.note = S_TEAM, "申请入队"
                try:
                    # 队员此刻仍是散人（未入队）可传送；传 leader_pid 供地图对账
                    # ★2026-09-13 用户定案：每名队员只申请一次（tries=1），
                    #   申请点击偶发未生效由阶段4 on_stall/看门狗补组兜底再叫。
                    sat.member_tp_and_apply(m.pid, cap, tries=1,
                                            tp_first=True,
                                            leader_pid=leader.pid)
                except Exception as e:
                    self._log("p%d 申请异常: %s" % (m.pid, e))

            ts = [threading.Thread(target=_apply_one, args=(m,), daemon=True)
                  for m in members]
            for t in ts:
                t.start()
            for t in ts:
                t.join(900)

            # ★2026-09-11 批次空洞修补：阶段3 的成员名单是批次启动瞬间的
            #   快照——掉线重登正好撞上批次窗口的队员（批次时旧进程刚死）
            #   会被整批漏掉。补一轮：在线但不在队的队员再驱动一次申请
            #   （此时批准循环还没跑，晚到的申请会被正常批准）。
            time.sleep(8.0)   # 给重登/登录收尾留时间

            def _not_in_team(m):
                try:
                    st = ZGUI.team_stats_topbar("file://pzxy_p%d" % m.pid)
                except Exception:
                    return True
                return not (st and st[0] >= 1 and bool(st[2]))

            late = [m for m in members
                    if m.status == S_ONLINE and _not_in_team(m)]
            if late:
                self._log("[autoTeam] 批次补漏：%d 名队员未入队 → 再次驱动申请"
                          % len(late))
                ts2 = [threading.Thread(target=_apply_one, args=(m,), daemon=True)
                       for m in late]
                for t in ts2:
                    t.start()
                for t in ts2:
                    t.join(600)

            # ---- 阶段4：批准 + 天覆阵 ----
            # ★2026-09-13 用户定案："组不到，就要联动再叫队员一次"——
            #   approve_loop 队列空(缺员)时触发 on_stall：重新发布联动信号
            #   并并行再叫"不在队"的队员申请（批次快照漏掉的晚登录队员
            #   由此自动收尾，不再干等 600s 超时）。
            self._log("[autoTeam] 阶段4: 队长批准申请（缺员自动联动再叫队员）")
            _reapply_ts = [0.0]

            def _reapply_phase4():
                now = time.time()
                if now - _reapply_ts[0] < 30.0:      # 节流：≥30s 才再叫一轮
                    return
                _reapply_ts[0] = now
                try:
                    sat.publish_link(leader.pid, self.cap_world or cap)
                except Exception:
                    pass
                _ms = []
                with self.lock:
                    _regs = list(self.instances)
                for _m in _regs:
                    if _m.role == "leader" or _m.pid in self._rejoining:
                        continue
                    try:
                        _st = ZGUI.team_stats_topbar("file://pzxy_p%d" % _m.pid)
                        _in = _st and _st[0] >= 1 and bool(_st[2])
                    except Exception:
                        _in = False
                    # 不限 S_ONLINE：晚登录状态未同步者也纳入，靠顶栏判在队
                    if not _in and find_hwnd_by_pid(_m.pid):
                        _ms.append(_m)
                if not _ms:
                    return

                def _a(m):
                    try:
                        # 只申请一次（30s 节流再叫已保证重试节奏）
                        sat.member_tp_and_apply(m.pid, cap, tries=1,
                                                tp_first=False,
                                                leader_pid=leader.pid)
                    except Exception:
                        pass

                _ts = [threading.Thread(target=_a, args=(m,), daemon=True)
                       for m in _ms]
                for _t in _ts:
                    _t.start()
                for _t in _ts:
                    _t.join(240)

            mem = sat.approve_loop(leader.pid, TEAM_SIZE, timeout_s=600.0,
                                   on_stall=_reapply_phase4)
            self._log("[autoTeam] 批准结束: 成员=%s/目标=%s"
                      % (mem, TEAM_SIZE))
            if mem and mem >= TEAM_SIZE:
                if sat.do_formation(leader.pid):
                    self._log("[autoTeam] 天覆阵完成 ✓")
                else:
                    self._log("[autoTeam] 阵法未确认（不阻断任务）")
            else:
                # ★2026-09-15 用户事件：组队都没完成，刷怪脚本已经点快捷传送了。
                #   根因：本分支原先只打一条“未满员”日志，随后**无条件**落到
                #   _finish_tasks → 拉起队长 run_unlimited_hunt.py → 立即用香 +
                #   快捷传送（而此刻队伍根本没组好）。现改为：关掉队伍
                #   面板后 **直接 return，不放行任务**；交给看门狗 _reteam 补齐后
                #   走正规路径拉起。
                #   ★队伍成员不能传送（对话框都不弹），必须散人状态传送后再
                #   组队；未组好就拉脚本既无效又扰民。
                self._log("[自动队] 未满员，跳过阵法；"
                          "不拉任务脚本（等看门狗补组）")
                # approve_loop 结束时队伍面板是开着的，先关掉
                lhwnd = find_hwnd_by_pid(leader.pid)
                if lhwnd:
                    ZGUI.post_click(lhwnd, 570, 583,
                                    gateway="file://pzxy_p%d" % leader.pid)
                # 置 note 标记“未就绪”；status 的归位统一由本函数末尾 finally 兜底
                #   （见 finally 中的统一归位逻辑）：只改 note 不改 status 会把全队
                #   永久卡在 S_TEAM，导致监控/看门狗/_reteam/人工恢复全部不可达
                with self.lock:
                    for i in insts:
                        if i.status == S_TEAM:
                            i.note = "组队未完成，等看门狗补组"
                # ★2026-09-15 修法１完善：未满员时**必须把看门狗启动起来**，
                #   否则没人补组。看门狗的“缺员”分支会调 _reteam 补齐，
                #   补满后走 _spawn_task 正常拉起（届时队长闸已满足）。
                #   注意：scripts_started 置 True＝“启动流程已走过”（看门狗需要），
                #   但 team_done 保持 False（组队尚未成功），队长脚本不拉。
                self.team_done = False
                # scripts_started 无条件置 True：看门狗缺员分支需要它为真，
                #   若看门狗已存在（_watch_started 已 True）也要保证不被拦。
                self.scripts_started = True
                leader = next((i for i in insts if i.role == "leader"), None)
                if leader is not None and not self._watch_started:
                    self._watch_started = True
                    threading.Thread(target=self._team_watchdog,
                                     args=(leader.pid, TEAM_SIZE),
                                     daemon=True).start()
                    self._log("[看门狗] 组队未完成，已启动补组看门狗")
                self._log("[自动队] 组队环节结束（未满员），不启动任务脚本")
                return
            self._finish_tasks(insts)
        except Exception as e:
            import traceback
            self._log("[autoTeam] 组队流程异常: %s" % e)
            self._log(traceback.format_exc())
        finally:
            self.teamflow_running = False
            # ★2026-09-18 治本（用户定案）：本函数是初始组队的**总入口**，离开时
            #   不得有任何实例停在 S_TEAM。未满员出口(return)与异常出口(except)
            #   只改 note 不改 status → 全队永久卡"组队中"：监控跳过 S_TEAM、
            #   看门狗要求队长 S_ONLINE、_reteam 只挑 S_ONLINE、
            #   _finish_tasks 未被调用、人工恢复也只认 S_ONLINE
            #   → 五路全闭、永久悬死（QA 11/11 实证）。这里统一兜回 S_ONLINE，
            #   让看门狗"缺员"分支能接手补组（_reteam → 满员后走正规路径拉起）。
            #   满员路径已由 _finish_tasks 归位，此处为幂等 no-op。
            try:
                with self.lock:
                    for i in insts:
                        if i.status == S_TEAM:
                            i.status = S_ONLINE
                            if not i.note or "未完成" in i.note:
                                i.note = "组队未完成，等看门狗补组"
                            self._log("p%d 组队流程退出时仍在 S_TEAM → 兜回 S_ONLINE（防悬死）"
                                      % i.pid)
            except Exception as e:
                self._log("[autoTeam] finally 归位异常: %s" % e)

    # ---------- 暂停接管 / 恢复挂机（2026-09-07 用户需求） ----------
    def _toggle_pause(self):
        """暂停⇄恢复切换。杀任务脚本/扫描可能耗时（PowerShell 查询），
        放后台线程跑，UI 只即时改按钮文字与状态。"""
        if self.teamflow_running or self._reteam_running:
            self._log("组队/补组流程进行中，等本轮结束再暂停")
            return
        self.btn_pause.config(state="disabled")
        if not self.paused:
            self.paused = True            # 先立旗，防看门狗/监控再发起新动作
            self.btn_pause.config(text="▶ 恢复挂机")
            threading.Thread(target=self._pause_all, daemon=True).start()
        else:
            self.paused = False            # ★2026-09-07 修复：漏置回 False
            self.btn_pause.config(text="⏸ 暂停接管")   # → 恢复后永远冻结
            threading.Thread(target=self._resume_all, daemon=True).start()

    def _pause_all(self):
        """暂停：人工接管游戏。停全部任务脚本 + 冻结看门狗/掉线闭环。

        与【全部停止】的区别：不杀游戏进程、worker 不动；暂停期间窗口
        掉线/崩溃等一律不自动处理（用户在玩，GUI 完全撒手）。
        """
        try:
            self._log("[暂停] 自动化冻结：停任务脚本，看门狗/掉线闭环挂起（可人工接管）")
            with self.lock:
                insts = [i for i in self.instances if i.status == S_ONLINE]
            for i in insts:
                i.note = "已暂停(人工接管)"
                self._kill_task_for(i.pid, leader=(i.role == "leader"))
            self._log("[暂停] 完成：任务脚本已全部停止")
        finally:
            self.after(0, lambda: self.btn_pause.config(state="normal"))

    def _resume_all(self):
        """恢复：跳过组队（不跑【启动脚本】的组队流程），按角色直接
        重新拉起任务脚本 + 解冻看门狗/掉线闭环。

        若接管期间队伍散了，看门狗检测缺员后会按需自动补组——那是
        看门狗自身的常驻逻辑，与本按钮无关（本按钮永不触发组队）。
        """
        try:
            self._log("[恢复] 解冻：跳过组队，按角色直接拉起任务脚本")
            with self.lock:
                insts = [i for i in self.instances if i.status == S_ONLINE]
            for i in insts:
                i.note = "运行中"
                self._spawn_task(i, skip_team=True)
            self.scripts_started = True
            self._log("[恢复] 完成：任务脚本已拉起，看门狗/掉线闭环恢复"
                      "（缺员时看门狗自动补组）")
        finally:
            self.after(0, lambda: self.btn_pause.config(state="normal"))

    # ---------- 内存清理（手动按钮 + 每30分钟自动） ----------
    def _trim_memory(self):
        threading.Thread(target=self._trim_memory_work, daemon=True).start()

    def _trim_memory_work(self):
        """修剪全部游戏进程工作集（EmptyWorkingSet，不杀进程不断线）。

        注意：修剪后游戏页按需换回，角色下一次操作可能轻微卡顿一下——
        所以自动清理默认关，且只在用户勾选后每 30 分钟做一次。
        """
        wins = enum_game_windows()
        if not wins:
            self._log("[内存] 没有游戏进程可清理")
            return
        total_b = total_a = 0
        n = 0
        for pid, _h, _t in wins:
            r = trim_process_ws(pid)
            if r:
                total_b += r[0]
                total_a += r[1]
                n += 1
        if n:
            self._log("[内存] 已修剪 %d 个游戏进程：%s → %s（释放 %s）"
                      % (n, human_bytes(total_b), human_bytes(total_a),
                         human_bytes(max(0, total_b - total_a))))
        else:
            self._log("[内存] 修剪失败（进程打不开，权限不足？）")

    def _toggle_auto_trim(self):
        self.cfg["auto_trim"] = bool(self.var_auto_trim.get())
        self._save_cfg()
        self._log("[内存] 自动清理%s" % ("已开启（每30分钟）" if self.cfg["auto_trim"]
                                    else "已关闭"))

    def _auto_trim_loop(self):
        last = 0.0
        while True:
            time.sleep(30)
            try:
                if self.var_auto_trim.get() and time.time() - last >= 1800:
                    last = time.time()
                    self._trim_memory_work()
            except Exception:
                pass

    def _popup_loop(self):
        """每 5s 扫游戏/WerFault 名下的系统弹窗并点掉（用户需求：弹窗不点掉
        进程卡住不掉 → 掉线闭环拉不起游戏）。暂停接管时不代点（用户在玩）。"""
        while True:
            time.sleep(5)
            try:
                if self.paused:
                    continue
                pids = _pids_by_image()
                if not pids:
                    continue
                for hwnd, pid, title in _enum_dialogs_of(pids):
                    txt = _dialog_text(hwnd)     # ★先取文本再点掉（点掉即消失）
                    if _dismiss_popup(hwnd):
                        self._log("p%d 检测到系统弹窗(%s) → 已点确定/关闭 文本:%s"
                                  % (pid, (title or "")[:30], txt or "无"))
            except Exception:
                pass

    def _finish_tasks(self, insts):
        # ★2026-09-15 用户事件（修法２）：这里是拉起任务脚本的**唯一出口**，之前
        #   缺少最后一道校验，导致组队未完成也能把刷怪脚本拉起来
        #   （随即快捷传送）。此处复用 _leader_wait_reason：未到齐则
        #   **不拉起任何实例（含队长）**，不置 scripts_started/team_done，
        #   交给看门狗后续补组后重试。
        #   注意：单队长配置（无队友）时返回 None，不会误拦。
        # ★2026-09-15 用户实锤（01:32:47）：天覆阵已完成，闸门却报
        #   "无在线队长"，随后重试又报"没有已登录实例"。
        #   根因：阶段1 把队长置为 S_TEAM（"组队中"，第 1014 行），
        #   组队成功后**无人回写 S_ONLINE**；而本函数末尾的回写在
        #   闸门**之后**，return 后永不执行（先检查后修复的顺序错误）。
        #   共同因果：这个中间态还把三条恢复路径全堵住了——
        #     看门狗（1622 行）、_reteam（1851 行）、监控（1928 行）
        #     均以 "status == S_ONLINE" 为前提，队长永远不在名单内 → 死锁。
        #   修法：闸门前先把参与组队的实例状态归位。组队流程都跑
        #   完了，说明它们必然已登录在线；S_TEAM 只是流程中间态，
        #   应在出口处落回 S_ONLINE，再让闸门基于真实在线状态判定。
        #   仅限 insts（刚跑完组队流程的批次），不用扫 self.instances，
        #   也不误动真正掉线/重登中的实例。
        _fixed = []
        with self.lock:
            for _i in insts:
                if _i.status == S_TEAM:
                    _i.status, _i.note = S_ONLINE, "已在线"
                    _fixed.append(_i.pid)
        if _fixed:
            self._log("[任务闸] 组队流程已完成，状态归位 S_TEAM→S_ONLINE：%s"
                      % ",".join("p%d" % _p for _p in _fixed))
        _block = self._leader_wait_reason()
        if _block:
            self._log("[任务闸] 组队未完成，不启动任务脚本：%s" % _block)
            with self.lock:
                for i in insts:
                    if i.status in (S_TEAM, S_ONLINE):
                        i.note = "等待组队完成"
            return
        self.scripts_started = True
        self.team_done = True
        for i in insts:
            i.status, i.note = S_ONLINE, "运行中"
            self._spawn_task(i)
        self._log("[autoTeam] 组队+任务脚本启动完成")
        # 启动队伍完整性看门狗（有队长才启动；仅启动一次）
        leader = next((i for i in insts if i.role == "leader"), None)
        if leader is not None and not self._watch_started:
            self._watch_started = True
            threading.Thread(target=self._team_watchdog,
                             args=(leader.pid, TEAM_SIZE),
                             daemon=True).start()

    def _leader_wait_reason(self):
        """★2026-09-09 用户定案：队长必须等所有队友到齐才能开始任务。

        到齐 = 所有队员实例均 S_ONLINE 且队长顶栏队伍数 >= 注册总人数。
        返回 None（到齐，可启动）或提示串（明确列出未到齐的队友）。
        """
        with self.lock:
            insts = list(self.instances)
        leader = next((i for i in insts if i.role == "leader"), None)
        members = [i for i in insts if i.role != "leader"]
        if leader is None or leader.status != S_ONLINE:
            return "无在线队长"
        if not members:
            return None          # 单队长配置：无队友可等
        missing = []
        for m in members:
            if m.status != S_ONLINE:
                missing.append("%s p%d（掉线/未登录）" % (m.name or m.role_cn, m.pid))
        st = ZGUI.team_stats_topbar("file://pzxy_p%d" % leader.pid)
        mem = st[0] if st else -1
        expect = TEAM_SIZE
        if mem >= 0 and mem < expect:
            short = expect - mem
            for m in [x for x in members if x.status == S_ONLINE][:short]:
                missing.append("%s p%d（在线但未入队）" % (m.name or m.role_cn, m.pid))
        elif mem < 0 and not missing:
            return "队长顶栏队伍数据读不到（通道/面板），暂缓启动"
        if missing:
            return ("未到齐：%s（队伍 %s/%s）——请先完成组队或确认队友在线"
                    % ("、".join(missing), mem if mem >= 0 else "?", expect))
        return None

    # ---------- 卫生循环（启动 20s 首轮，之后每 24h 一轮） ----------
    def _hygiene_once(self):
        try:
            with self.lock:
                managed = {i.pid for i in self.instances}
            _hygiene_scan(managed, log=self._log)
        except Exception as e:
            self._log("[卫生] 异常: %s" % e)

    def _hygiene_loop(self):
        time.sleep(20.0)          # 等实例表初始化完再首轮清扫
        while True:
            self._hygiene_once()
            time.sleep(_HYGIENE_INTERVAL_S)

    def _spawn_task(self, inst, skip_team=False):
        """按角色拉起任务脚本（已在跑则跳过）。

        skip_team ☆2026-09-17 用户定案：本次拉起属于"**跳过组队**"路径
          （看门狗补拉 / 【恢复挂机】 / 重登归队；组队阶段没跑过，
          快捷传送对话框 [8] 未开）→ 给队长脚本追加 --skip-team，
          允许它在运行中补点快捷传送开关。
          常规【启动脚本】组队完成后的拉起（_finish_tasks）不传，
          因为组队阶段已把 [8] 开好，运行中不应再点开关。
        """
        # ★2026-09-09 用户定案（单点闸）：队长必须等所有队友到齐才能开始
        #   任务——初始组队/重登归队/看门狗补拉/满员恢复全部走这里，未到齐
        #   一律阻止队长任务启动并明确提示缺谁；队员出售脚本不在此限。
        if inst.role == "leader":
            reason = self._leader_wait_reason()
            if reason:
                self._log("[任务闸] 队长任务暂不启动：%s" % reason)
                return
        # ★2026-09-07 加固：区分"扫描失败"与"真的没在跑"。此前扫描异常返回
        #   空列表 → 防重失效 → 同客户端可能被拉起两个任务脚本互抢背包；
        #   但也不能把"真的没在跑"（如 00:59 手动全停后）误判为失败拒拉
        #   （01:21 实证五实例全部跳过拉起）。以 PowerShell 返回码为准。
        ok, cmdlines = running_squad_cmdlines_ex()
        if not ok:
            self._log("p%d 任务进程扫描失败，重扫一次" % inst.pid)
            time.sleep(1.5)
            ok, cmdlines = running_squad_cmdlines_ex()
            if not ok:
                self._log("p%d 进程扫描两次失败，跳过拉起（结果不可信防双跑）" % inst.pid)
                return
        if process_alive_for(cmdlines, inst.pid, inst.role == "leader",
                             names=profile_task_names(self.script_profile)):
            self._log("p%d 任务脚本已在跑，跳过" % inst.pid)
            return
        gw = "file://pzxy_p%d" % inst.pid
        title = inst.title or next(
            (t for p, _h, t in enum_game_windows() if p == inst.pid), "")
        rm = ROLE_RE.search(title or "")
        role_name = rm.group(1).strip() if rm else ("p%d" % inst.pid)
        try:
            CREATE_NO_WINDOW = 0x08000000
            lscript, mscript = profile_scripts(self.script_profile)
            if inst.role == "leader":
                cmd = ([PYEXE, lscript, "--gateway", gw, "--role", role_name]
                       + profile_leader_args(self.script_profile))
                if skip_team:
                    cmd.append("--skip-team")
            else:
                cmd = [PYEXE, mscript, "--pid", str(inst.pid), "--gateway", gw]
            # ★2026-09-09 尸检通道：此前 stderr=DEVNULL，任务脚本崩溃 traceback
            #   直接丢弃（07:28 leader 闯关完成后静默死亡、昨夜 04:38 同款，
            #   死因永远查不到）。stdout/stderr 全落 logs/task_p<pid>_run.log。
            #   （08:00 事故注：本次编辑曾把上面 cmd 构造块吞掉，导致
            #   "name 'cmd' is not defined" 补拉全灭——编辑后必须 grep 校验。）
            try:
                _runlog = open(os.path.join(ROOT, "logs",
                                "task_p%d_run.log" % inst.pid), "ab")
            except Exception:
                _runlog = None
            subprocess.Popen(cmd, cwd=ROOT, creationflags=CREATE_NO_WINDOW,
                             stdout=_runlog or subprocess.DEVNULL,
                             stderr=_runlog or subprocess.DEVNULL)
            self._log("p%d 已拉起任务脚本（%s·%s gw=%s）"
                      % (inst.pid, inst.role_cn, role_name, gw))
        except Exception as e:
            self._log("p%d 任务脚本启动失败: %s" % (inst.pid, e))

    def _task_script_alive(self, inst):
        """队长/队员任务脚本当前是否确实在跑（看门狗补拉前用）。

        ★2026-09-17 用户定案：看门狗"满员恢复"调 _spawn_task 前先问一句——
          脚本一直在跑（队伍数据抖动）→ 传 skip_team=False，运行中不点
          快捷传送开关；脚本确实没在跑（崩溃/被杀/掉线重登）→ 传
          skip_team=True，允许补拉后补点开关。
        扫描失败一律返回 False（宁可按"没在跑"处理，让 _spawn_task 内部
          再做二次扫描与防双跑，不在本函数里替它下结论）。
        """
        try:
            ok, cmdlines = running_squad_cmdlines_ex()
            if not ok:
                return False
            return bool(process_alive_for(
                cmdlines, inst.pid, inst.role == "leader",
                names=profile_task_names(self.script_profile)))
        except Exception:
            return False

    # ---------- 队伍完整性看门狗（队长侧） ----------
    # ---------- 背包满 → 全队存仓（2026-09-12 用户定案 4a） ----------
    def _bag_used(self, inst):
        """点开背包读占用格数（读不到返回 -1）。零副作用：读完即关。"""
        gw = "file://pzxy_p%d" % inst.pid
        hwnd = find_hwnd_by_pid(inst.pid)
        if not hwnd:
            return -1
        try:
            ZGUI._bag_ensure_open(gw, hwnd)
            n = ZGUI._bag_used_count(gw)
            ZGUI._bag_ensure_close(gw, hwnd)
            if n is None:
                return -1
            return int(n)
        except Exception:
            return -1

    def _bag_store_check(self):
        """巡检在线实例背包；任一满（>=20 格）→ 触发全队存仓流程。"""
        with self.lock:
            online = [i for i in self.instances if i.status == S_ONLINE]
        if len(online) < 2:
            return
        full = []
        for it in online:
            n = self._bag_used(it)
            if n >= 20:
                full.append((it.pid, n))
        if not full:
            return
        self._log("[存仓] 巡检发现背包满: %s → 启动全队存仓流程"
                  % ", ".join("p%d(%d格)" % (p, n) for p, n in full))
        self._store_running = True
        threading.Thread(target=self._bag_store_flow, daemon=True).start()

    def _bag_store_flow(self):
        """全队存仓：停脚本 → 队长解散 → 逐人存仓 → 重新组队 → 恢复任务。

        ★用户定案：一个角色背包满 → 所有人都去存一次；组队下无法存仓，
          必须先解散；存完走现成组队流程重组并拉起任务脚本。
        """
        try:
            with self.lock:
                insts = list(self.instances)
            # 1) 停任务脚本（存仓期间不让脚本抢客户端）
            for it in insts:
                try:
                    self._kill_task_for(it.pid, leader=(it.role == "leader"))
                except Exception:
                    pass
            time.sleep(2.0)
            # 2) 队长解散队伍（全员退队）——★2026-09-13 用户定案：直接队长解散。
            #    组队下队员无法与仓库管理员互动，解散必须成功才存仓；
            #    解散失败（顶栏仍有人）→ 中止本轮存仓，等下一轮再触发。
            leader = next((i for i in insts if i.role == "leader"), None)
            if leader is not None:
                try:
                    sat.disband_team(leader.pid)
                except Exception as e:
                    self._log("[存仓] 解散异常: %s" % e)
            try:
                sts = ZGUI.team_stats_topbar("file://pzxy_p%d" % leader.pid)
            except Exception:
                sts = None
            if not (sts and sts[0] == 0):
                self._log("[存仓] 队伍未解散（顶栏%s人），组队下无法存仓 → 跳过本轮"
                          % (sts[0] if sts else "?"))
                return
            # 3) 逐人存仓（★用户 2026-09-12：可以并行——各角色独立客户端、
            #    仓库也是角色各自独立的；并行把 5 人从 ~15min 压到 ~3-4min。
            #    Lua 调用有全局限速锁自动串行化，每次毫秒级不影响。）
            results = {}

            def _store_one(it):
                try:
                    # ★2026-09-17 用户定案：先卖后存（zhuagui_bag_full_handle 内部
                    #   先 zhuagui_sell_junk 出售垃圾腾空间，再 zhuagui_store_all 存仓）。
                    sell, ok, n, msg = wh.zhuagui_bag_full_handle(it.pid)
                    results[it.pid] = (ok, n, "售出%d件; " % sell + msg)
                except Exception as e:
                    results[it.pid] = (False, 0, "异常: %s" % e)

            ts = [threading.Thread(target=_store_one, args=(it,), daemon=True)
                  for it in insts]
            for t in ts:
                t.start()
            for t in ts:
                t.join(1200)
            total = 0
            for it in insts:
                ok, n, msg = results.get(it.pid, (False, 0, "无结果"))
                total += n or 0
                self._log("[存仓] p%d ok=%s 存入%s件（%s）" % (it.pid, ok, n, msg))
            self._log("[存仓] 全队完成，共存入 %d 件 → 重新组队" % total)
            # 4) 重新组队 + 拉起任务（复用现成流程）
            with self.lock:
                online = [i for i in self.instances if i.status == S_ONLINE]
            self._teamflow_and_tasks(online)
        except Exception as e:
            self._log("[存仓] 流程异常: %s" % e)
        finally:
            self._store_running = False

    def _team_watchdog(self, leader_pid, expect_members):
        """每 5s 判定队伍人数：满员不动；缺员 → 打断抓鬼 → 补组队 →
        满员自动恢复抓鬼。队员掉线由 GUI 重启重登后走 _rejoin_flow 归队，
        这里只负责队长侧的判定/打断/批准/恢复。"""
        self._log("[看门狗] 启动（目标 %d 人，每 5s 判定）" % expect_members)
        stale_scan_n = 0
        hb_n = 0
        bskip_n = 0
        self._kill_stale_tasks()   # 启动先清一遍历史僵尸
        while not self._team_watch_stop.wait(5):   # ★2026-09-13 15s→5s(更快联动登录队员)
            try:
                if self.paused:
                    continue   # ★暂停接管：看门狗只挂起不动作（恢复后自动续）
                stale_scan_n += 1
                hb_n += 1
                if stale_scan_n % 4 == 0:   # ~每分钟清一次残留任务脚本
                    self._kill_stale_tasks()
                # ★2026-09-12 背包满 → 全队存仓（用户定案 4a：每 10 分钟巡检一次）
                #   任一角色背包 20/20 满 → 解散 → 全员存仓 → 重新组队 → 恢复任务。
                if (stale_scan_n % 40 == 0 and not self.teamflow_running
                        and not self._reteam_running and not self._store_running
                        and not self._rejoining):
                    self._bag_store_check()
                # ★2026-09-09 任务脚本死亡自动补拉：07:28 实证 leader 脚本闯关
                #   完成后静默死亡（stderr 被 DEVNULL 吞掉），全队发呆无人管——
                #   掉线闭环只管游戏进程，没人管任务脚本进程。每 ~1min 巡检
                #   在线实例，任务脚本不在了就补拉（_spawn_task 自带防双跑）。
                # ★2026-09-10 两项收紧（11:49 实锤误报）：①补组进行中不巡检
                #   ——补组自己会打断/重拉任务，高负载下 PowerShell 扫描还易
                #   漏报（p4120 "已死"补拉 1s 后 "已在跑"=假死误报）；②同一
                #   PID 连续 2 轮扫描未命中才补拉（1 轮≈1min，真死最多晚 1min）。
                if (stale_scan_n % 4 == 2 and not self.teamflow_running
                        and not self._reteam_running and not self._store_running):
                    with self.lock:
                        _online = [i for i in self.instances
                                   if i.status == S_ONLINE]
                    for it in _online:
                        try:
                            _ok, _cls = running_squad_cmdlines_ex()
                            # ★2026-09-14 修复：存活巡检必须按当前方案传 names，
                            #   否则 process_alive_for 回落默认抓鬼脚本名
                            #   (run_unlimited_test)，"全地图刷怪"队长脚本
                            #   (run_unlimited_hunt) 恒匹配不上 → 误判已死 →
                            #   每轮补拉（补拉又"已在跑跳过"），噪音+资源浪费。
                            _alive = _ok and process_alive_for(
                                _cls, it.pid, it.role == "leader",
                                names=profile_task_names(self.script_profile))
                        except Exception as e:
                            self._log("p%d 任务脚本巡检异常: %s" % (it.pid, e))
                            continue
                        if _alive:
                            self._task_dead_n.pop(it.pid, None)
                            continue
                        _n = self._task_dead_n.get(it.pid, 0) + 1
                        self._task_dead_n[it.pid] = _n
                        if _n < 2:
                            self._log("p%d 任务脚本扫描未命中（第%d次），下轮复验"
                                      % (it.pid, _n))
                            continue
                        self._task_dead_n.pop(it.pid, None)
                        self._log("p%d 任务脚本已死（连续2轮未命中）→ 自动补拉"
                                  % it.pid)
                        self._spawn_task(it, skip_team=True)
                if not self.scripts_started or self.teamflow_running:
                    continue
                # ★2026-09-07：队长重登后 PID 会变（02:21 实证 p9472→24712）。
                #   旧代码拿启动时的 leader_pid 死查，重启后一直在读死通道
                #   → 看门狗永久失明。改为每轮按 role 重新解析当前队长。
                with self.lock:
                    leader = next((i for i in self.instances
                                   if i.role == "leader"), None)
                    if leader is None:
                        leader = next((i for i in self.instances
                                       if i.pid == leader_pid), None)
                if leader is not None and leader.pid != leader_pid:
                    self._log("[看门狗] 队长 PID 变更 %d → %d，跟随新通道"
                              % (leader_pid, leader.pid))
                    leader_pid = leader.pid
                if leader is None or leader.status != S_ONLINE:
                    continue   # 队长不在（掉线重登中），等归队流程
                # ★2026-09-08 深夜用户定案：战斗中不要检查队伍数据——
                #   23:41:50 实证战斗中顶栏连续 16 轮读不到刷"检查通道/面板"
                #   误报，且战斗中也不可能补组。战斗证据为真即跳过本轮判定，
                #   脱战后自动恢复；连续跳过 40 轮（~10 分钟）兜底恢复判定，
                #   防战斗信号残留导致看门狗永久失明。
                try:
                    if ZGUI.zhuagui_in_battle("file://pzxy_p%d" % leader_pid):
                        bskip_n += 1
                        if bskip_n <= 40:
                            continue
                    else:
                        bskip_n = 0
                except Exception:
                    bskip_n = 0
                # ★2026-09-07：顶栏读数零点击，战斗中也可判缺员
                st = self._watch_team_stats(leader_pid)
                mem = st[0] if st else -1
                if mem < 0:
                    if hb_n % 4 == 0:
                        self._log("[看门狗] 队伍数据连续读不到（%d 轮），检查通道/面板" % hb_n)
                    continue   # 瞬时读不到（通道/面板），下轮再看
                if hb_n % 8 == 0:
                    self._log("[看门狗] 心跳: %d/%d" % (mem, expect_members))
                if mem >= expect_members:
                    if self._watch_interrupted:
                        self._watch_interrupted = False
                        self._log("[看门狗] 队伍满员 %d/%d，恢复抓鬼"
                                  % (mem, expect_members))
                        with self.lock:
                            online = [i for i in self.instances
                                      if i.status == S_ONLINE]
                        for i in online:
                            # ★2026-09-17 用户定案：仅当脚本确实没在跑才
                            #   带 skip_team（允许补点快捷传送开关）；在跑
                            #   则普通拉起（运行中不点开关）。
                            self._spawn_task(
                                i, skip_team=not self._task_script_alive(i))
                    continue
                # 缺员
                # ★2026-09-12 存仓流程进行中：队员是"故意"退队的（存仓需要
                #   解散队伍），此处绝不能触发补组，否则与存仓抢客户端。
                if self._store_running:
                    continue
                if not self._watch_interrupted:
                    self._watch_interrupted = True
                    self._log("[看门狗] 检测到缺员 %d/%d → 打断抓鬼，启动补组队"
                              % (mem, expect_members))
                    self._kill_task_for(leader_pid, leader=True)
                if not self._reteam_running:
                    threading.Thread(target=self._reteam,
                                     args=(leader_pid, expect_members),
                                     daemon=True).start()
            except Exception as e:
                self._log("[看门狗] 异常: %s" % e)

    def _watch_team_stats(self, leader_pid):
        """读队伍统计。

        ★2026-09-07 改用顶部头像栏（tp.窗口.人物框.队伍数据）：
          游戏实时渲染刷新，无 p7 面板懒加载脏快照问题（02:14 退队标定：
          退队后顶栏立即 count=0，p7 仍残留 5），且零点击——
          旧方案每 30s 点图标开面板，抓鬼中反复弹面板扰民（用户明令禁止）。
          战斗中也可读（纯 Lua 读，不碰 UI），缺员判定不再有战斗盲区。
        """
        lw = "file://pzxy_p%d" % leader_pid
        return ZGUI.team_stats_topbar(lw)

    def _kill_task_for(self, pid, leader=True):
        """按网关通道打断该实例的任务脚本进程（打断抓鬼用）。"""
        _names = profile_all_task_names()
        ps = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
              "Where-Object { $_.CommandLine -match "
              "'%s' } | "
              "ForEach-Object { \"$($_.ProcessId)|$($_.CommandLine)\" }"
              % "|".join(sorted(_names)))
        try:
            r = subprocess.run(["powershell", "-NoProfile", "-c", ps],
                               capture_output=True, encoding="gbk",
                               errors="replace", timeout=30)
        except Exception as e:
            self._log("打断任务脚本查询失败: %s" % e)
            return
        token = "pzxy_p%d" % pid
        _names = profile_all_task_names()
        for line in (r.stdout or "").splitlines():
            line = line.strip()
            if "|" not in line:
                continue
            cp, cl = line.split("|", 1)
            if any(nm in cl for nm in _names) and token in cl:
                try:
                    subprocess.run(["taskkill", "/F", "/PID", cp.strip()],
                                   capture_output=True, timeout=15)
                    self._log("已打断 p%d 任务脚本（系统 PID %s）"
                              % (pid, cp.strip()))
                except Exception:
                    pass

    def _kill_stale_tasks(self):
        """★2026-09-07 新增：清理绑定已死游戏 PID 的残留任务脚本。

        客户端崩溃重启后 PID 变化，旧任务脚本（cmdline 含 pzxy_p<旧pid>）
        不会自己退出，整夜累积（00:59 实证一次清出 9 个）。僵尸脚本虽不直接
        点击现役客户端，但持续空转重试死通道耗 CPU，且干扰进程防重扫描。
        """
        _names = profile_all_task_names()
        ps = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
              "Where-Object { $_.CommandLine -match "
              "'%s' } | "
              "ForEach-Object { \"$($_.ProcessId)|$($_.CommandLine)\" }"
              % "|".join(sorted(_names)))
        try:
            r = subprocess.run(["powershell", "-NoProfile", "-c", ps],
                               capture_output=True, encoding="gbk",
                               errors="replace", timeout=30)
        except Exception as e:
            self._log("残留任务清理查询失败: %s" % e)
            return
        alive = {p for p, _h, _t in enum_game_windows()}
        for line in (r.stdout or "").splitlines():
            line = line.strip()
            if "|" not in line:
                continue
            cp, cl = line.split("|", 1)
            m = re.search(r"pzxy_p(\d+)", cl)
            if not m:
                continue
            bind_pid = int(m.group(1))
            if bind_pid in alive:
                continue
            try:
                subprocess.run(["taskkill", "/F", "/PID", cp.strip()],
                               capture_output=True, timeout=15)
                self._log("已清理残留任务脚本（绑定死 PID %d，系统 PID %s）"
                          % (bind_pid, cp.strip()))
            except Exception:
                pass

    def _reteam(self, leader_pid, expect_members):
        """缺员补救：队长回[139,80] →（散队先重建）→ 在线队员并行申请
        （跳过正在归队的，防双驱动同一客户端）→ 批准至满员 → 天覆阵 →
        恢复任务。★时序铁律：approve_loop 结束面板开着 → 直接 do_formation
        （其自管图标开关与双窗口关闭），中间不得插关面板点击。"""
        self._reteam_running = True
        try:
            if self.paused:
                self._log("[看门狗] 暂停生效，跳过本轮补组")
                return
            lw = "file://pzxy_p%d" % leader_pid
            # ★2026-09-08 时序铁律（用户定案）：队长必须真正到达 [139,80]
            #   （±3 格，实测确认），队员才能开始组队操作。队长没到就让队员
            #   点击 = 朝锚点/旧坐标投影点空地，既无效又打乱双方坐标
            #   （12:41 实锤：队长卡传送落点，成员按旧锚点坐标点击全落空）。
            #   未就位 → 本轮直接放弃，等下一轮看门狗重来；中途队员掉线也
            #   一样：掉线队员由下一轮（队长重新就位后）再归队。
            cap = sat.prep_leader(leader_pid)
            if cap is None:
                self._log("[看门狗] 队长未就位 [139,80] → 本轮跳过队员归队"
                          "（等下一轮，防打乱坐标）")
                return
            self.cap_world = cap
            cap = self.cap_world
            # ★散队判定必须读顶栏：p7 面板数据是懒加载快照，队员掉线后
            #   会残留旧的满员数据 → 判定为"队伍还在"而永不重建（02:14 实证）
            st = ZGUI.team_stats_topbar(lw)
            if st is None:
                st = ZGUI._team_stats(lw)
            mem = st[0] if st else 0
            if mem <= 1:
                self._log("[看门狗] 队伍已散（%s 人）→ 重新建队" % mem)
                if not sat.create_team(leader_pid, cap):
                    self._log("[看门狗] 重新建队失败，下轮再试")
                    return
            # ★2026-09-09 队长先行联动：就位(+建队成功/队伍仍在)才发布信号，
            #   队员（含重登待命线程）凭信号才行动；上面任何失败分支不发布。
            sat.publish_link(leader_pid, cap)
            with self.lock:
                members = [i for i in self.instances
                           if i.role != "leader" and i.status == S_ONLINE
                           and i.pid not in self._rejoining]
            if members:
                self._log("[看门狗] %d 名在线队员并行申请归队" % len(members))

                def _apply(m):
                    try:
                        # ★传 leader_pid：地图对账联动（异图就地传送/视野外走近）
                        sat.member_tp_and_apply(m.pid, cap, tries=3,
                                                tp_first=False,
                                                leader_pid=leader_pid)
                    except Exception as e:
                        self._log("p%d 归队申请异常: %s" % (m.pid, e))

                ts = [threading.Thread(target=_apply, args=(m,), daemon=True)
                      for m in members]
                for t in ts:
                    t.start()
                for t in ts:
                    t.join(600)
            def _reapply():
                """队列空回调(2026-09-13)：自动再叫在线队员并行申请一轮，
                避免'队伍一直差人却干等空队列'。依赖外层 cap/leader_pid。"""
                try:
                    with self.lock:
                        _ms = [i for i in self.instances
                               if i.role != "leader" and i.status == S_ONLINE
                               and i.pid not in self._rejoining]
                    if not _ms:
                        return

                    def _a(m):
                        try:
                            sat.member_tp_and_apply(m.pid, cap, tries=3,
                                                    tp_first=False,
                                                    leader_pid=leader_pid)
                        except Exception:
                            pass

                    _ts = [threading.Thread(target=_a, args=(m,), daemon=True)
                           for m in _ms]
                    for _t in _ts:
                        _t.start()
                    for _t in _ts:
                        _t.join(300)
                except Exception:
                    pass
            got = sat.approve_loop(leader_pid, expect_members, timeout_s=420.0, on_stall=_reapply)
            self._log("[看门狗] 补组批准结束: %s/%s" % (got, expect_members))
            if got and got >= expect_members:
                sat.do_formation(leader_pid)
                self._watch_interrupted = False
                with self.lock:
                    online = [i for i in self.instances
                              if i.status == S_ONLINE]
                for i in online:
                    # ★2026-09-17 用户定案：仅脚本确实没在跑才带 skip_team
                    #   （允许补点快捷传送开关），在跑则普通拉起。
                    self._spawn_task(i, skip_team=not self._task_script_alive(i))
                self._log("[看门狗] 满员，抓鬼已恢复 ✓")
            else:
                # 未满员：关掉批准面板再等下一轮，不给任务留遮挡
                hwnd = find_hwnd_by_pid(leader_pid)
                if hwnd:
                    ZGUI.post_click(hwnd, 570, 583, gateway=lw)
                self._log("[看门狗] 仍未满员，掉线队员回来后继续下一轮")
        finally:
            self._reteam_running = False

    # ---------- 监控（掉线闭环） ----------
    def _monitor_loop(self):
        while True:
            time.sleep(2.0)
            try:
                self._monitor_once()
            except Exception as e:
                self._log("监控异常: %s" % e)

    def _untracked_windows(self):
        with self.lock:
            managed = {i.pid for i in self.instances}
        return [(p, h, t) for p, h, t in enum_game_windows() if p not in managed]

    def _maybe_adopt(self, inst):
        """进程消失但存在游离游戏窗口（启动器型 exe 拉起真客户端后自己退出）
        ★2026-09-07 加固（02:21 实证坑）：此前直接收养 orphans[0]，把刚重启的
          队长新进程（PID=24712）误收养成"一号美人"槽 → 两个槽位驱动同一客户端
          （双驱动：抢点击/抢面板，表现就是"组队不行"）。现在必须同时满足：
            1) 窗口标题里的角色名与本实例角色名一致（ROLE_RE 提取）；
            2) 该 PID 未被其它实例占用。
        """
        orphans = self._untracked_windows()
        if not orphans:
            return None
        m = ROLE_RE.search(inst.title or "")
        want = m.group(1).strip() if m else ""
        if not want:
            self._log("p%s 进程消失，但实例角色名未知 → 不收养，按掉线重启"
                      % inst.pid)
            return None
        with self.lock:
            others = {i.pid for i in self.instances if i is not inst}
        for pid, hwnd, title in orphans:
            m2 = ROLE_RE.search(title or "")
            name2 = m2.group(1).strip() if m2 else ""
            if name2 != want or pid in others:
                continue
            old = inst.pid
            inst.pid, inst.name, inst.title = pid, "p%d" % pid, title
            self._log("p%s 进程消失，收养同名角色窗口 PID=%d（%s）" % (old, pid, want))
            return (pid, hwnd, title)
        self._log("p%s 进程消失，无同名(%s)游离窗口 → 不收养（防误绑）"
                  % (inst.pid, want))
        return None

    def _monitor_once(self):
        if self.paused:
            return   # ★暂停接管：不掉线判定/不重启/不播种（用户在玩，GUI 撒手）
        with self.lock:
            insts = list(self.instances)
        wins = {pid: (pid, hwnd, title) for pid, hwnd, title in enum_game_windows()}
        for inst in insts:
            # ★2026-09-08 全状态进程死活巡检（仅 S_RESTART 例外，其自管新进程生死）：
            #   异步流程（组队/播种/启动等待）遇客户端死亡会永久卡在原状态——
            #   18:32 实锤：帅哥客户端死于组队阶段，状态停在"组队中"，监控因
            #   下方状态白名单无条件跳过 → 表里 5 个实例只剩 4 个窗口，队伍
            #   看门狗 4/5 永远补不齐（死锁）。进程死了无论什么状态都走重启闭环。
            if inst.status != S_RESTART and not proc_alive(inst.pid):
                self._log("p%d 进程已死（状态=%s）→ 重启闭环"
                          % (inst.pid, inst.status))
                self._begin_restart(inst)
                continue
            if inst.status in (S_LAUNCH, S_PLANT, S_RESTART, S_TEAM):
                continue  # 由各自的异步流程负责
            w = wins.get(inst.pid)
            logged = bool(w and LOGGED_IN_RE.search(w[2]))
            if inst.status == S_WAIT:
                if logged:
                    inst.status = S_ONLINE
                    inst.title = w[2]
                    self._log("p%d 检测到已登录 ✓" % inst.pid)
                    self._after_login(inst)
                elif not w:
                    adopted = self._maybe_adopt(inst)
                    if adopted and LOGGED_IN_RE.search(adopted[2]):
                        inst.status = S_ONLINE
                        self._after_login(inst)
                    elif adopted and "([0])" in adopted[2]:
                        inst.status = S_PLANT
                        threading.Thread(target=self._do_plant,
                                         args=(inst, adopted[1]),
                                         daemon=True).start()
                    else:
                        self._log("p%d 窗口消失（待登录阶段）→ 重启闭环" % inst.pid)
                        self._begin_restart(inst)
            elif inst.status == S_ONLINE:
                if not logged:
                    adopted = self._maybe_adopt(inst)
                    if adopted and LOGGED_IN_RE.search(adopted[2]):
                        inst.status, inst.title = S_ONLINE, adopted[2]
                        self._log("p%d 收养后仍在线 ✓" % inst.pid)
                    elif adopted and "([0])" in adopted[2]:
                        inst.status = S_PLANT
                        threading.Thread(target=self._do_plant,
                                         args=(inst, adopted[1]),
                                         daemon=True).start()
                    else:
                        reason = "进程消失" if not proc_alive(inst.pid) else \
                            ("退回登录界面" if (w and "([0])" in w[2]) else "窗口/标题异常")
                        self._log("p%d 掉线判定: %s → 重启闭环" % (inst.pid, reason))
                        self._begin_restart(inst)
                # ★2026-09-09 tp 健康检查（用户指令：tp 被服务器抹掉时 GUI 直接
                #   杀游戏重启，不再让任务脚本空转）——仅标题仍在线的实例查。
                #   每 4 轮查一次（监控 2s/轮 → ~8s 一次）。
                # ★2026-09-10 重连宽限（用户选 a，13:43 风暴复盘）：r=False
                #   本身就代表 worker 心跳存活、只是 tp=nil——这可能是服务端
                #   脚本热更新/客户端自愈重连中（实锤持续 ~15min 也会自愈）。
                #   改为时间宽限：首次 nil 起 75s 内不动，超时仍 nil 才杀重启。
                #   超时/未知（None）不计数不计时（防游戏忙碌误杀）。
                if inst.status == S_ONLINE and logged and not self.teamflow_running:
                    self._tp_tick += 1
                    if self._tp_tick % 4 == 0:
                        r = self._tp_alive(inst.pid)
                        if r is True:
                            self._tp_fail.pop(inst.pid, None)
                            self._tp_nil_since.pop(inst.pid, None)
                        elif r is False:
                            _now = time.time()
                            _since = self._tp_nil_since.get(inst.pid)
                            if _since is None:
                                self._tp_nil_since[inst.pid] = _now
                                self._log("p%d tp 状态消失（worker存活）→ 宽限%ds 等待自愈/重连，期间不杀"
                                          % (inst.pid, int(_TP_NIL_GRACE_S)))
                            elif _now - _since < _TP_NIL_GRACE_S:
                                pass          # 宽限期内：不杀，等自愈
                            else:
                                self._tp_nil_since.pop(inst.pid, None)
                                self._log("p%d tp 持续 nil 超 %ds（worker存活）→ 状态确认丢失，杀游戏重启闭环"
                                          % (inst.pid, int(_TP_NIL_GRACE_S)))
                                self._begin_restart(inst)
                        else:
                            # None=worker 未应答（未知）：清宽限计时，避免把
                            # "worker 恢复后的新鲜观察"错接到旧窗口上
                            self._tp_nil_since.pop(inst.pid, None)

    def _begin_restart(self, inst):
        inst.status = S_RESTART
        inst.note = "掉线重启中"
        self._tp_fail.pop(inst.pid, None)   # 重启即清 tp 失败计数
        self._tp_nil_since.pop(inst.pid, None)  # 同时清 tp 宽限计时
        # ★2026-09-10 联动铁律（用户重申）：队长掉线/重启 → 立即撤销旧信号。
        #   否则旧 team_link.json 在 30min TTL 内仍有效，队员重登读到就传送，
        #   而队长根本还没到 [139,80]（22:14 实锤场景）。
        if inst.role == "leader":
            try:
                sat.revoke_link()
            except Exception as e:
                self._log("[联动] 撤销信号异常: %s" % e)
        threading.Thread(target=self._restart_flow, args=(inst,), daemon=True).start()

    def _tp_alive(self, pid):
        """Lua 主状态存活检查（★2026-09-09 掉线闭环；★2026-09-10 B方案双旗）。

        此检查返回：
          True  = tp 或 引擎.场景 任一存活（含服务端脚本热更新窗口——
                  tp 别名被清但引擎场景存活 → 不杀，自动化经场景降级读取）
          False = tp 与 引擎.场景 双双为 nil（状态真死）→ 计数杀重启
          None  = worker 死/超时/执行失败（未知，不计数，防误杀）
        """
        try:
            w = PzxyWorker(name="p%d" % pid)
            if not w.is_alive():
                return None
            # ★2026-09-10 B方案：tp 别名被服务端脚本重载清掉 ≠ 客户端死——
            #   引擎.场景（与 tp 同一对象）仍存活。双旗探测：
            #   场景或 tp 任一存在 = 存活（返回 True，不杀）；
            #   双双为 nil = 状态真死（返回 False，计数）。
            ok, val = w.cmd("__out = tostring(((tp) or ((_G.引擎) and (_G.引擎.场景))) ~= nil) .. '|' .. tostring(tp ~= nil)",
                            timeout=2.5)
            if not ok:
                return None
            flags = str(val).strip().split("|")
            scene_alive = flags[0] == "true"
            tp_gone = flags[1] == "false"
            if scene_alive:
                return True
            return False if tp_gone else None
        except Exception:
            return None
        except Exception:
            return None

    def _restart_flow(self, inst):
        """掉线全闭环：杀旧任务 → 强杀卡死旧进程 → 重启游戏 → 补种 → 重放登录 → 拉起任务。"""
        old_pid = inst.pid
        try:
            kill_task_process(old_pid)
        except Exception:
            pass
        # ★2026-09-07 用户实锤：崩溃弹窗不点掉时旧游戏进程卡着不退，
        #   直接拉新窗口会挤在一起/登录冲突。重启前强制结束旧进程。
        if proc_alive(old_pid):
            try:
                subprocess.run(["taskkill", "/F", "/PID", str(old_pid)],
                               capture_output=True, timeout=15)
                self._log("p%d 旧游戏进程卡死，已强制结束" % old_pid)
                time.sleep(1.0)
            except Exception:
                pass
        gp = self.var_path.get().strip()
        if not gp or not os.path.exists(gp):
            inst.note = "游戏路径无效，重启挂起"
            self._log("[fail] 游戏路径无效，无法重启 p%d" % old_pid)
            return
        try:
            CREATE_NO_WINDOW = 0x08000000
            popen = subprocess.Popen([gp], cwd=os.path.dirname(gp),
                                     creationflags=CREATE_NO_WINDOW)
        except Exception as e:
            inst.note = "重启失败: %s" % e
            self._log("[fail] p%d 重启游戏失败: %s" % (old_pid, e))
            return
        new_pid = popen.pid
        self._log("p%d 已重启为新进程 PID=%d，等待登录界面…" % (old_pid, new_pid))
        # 等新窗口到登录界面
        hwnd, title = None, ""
        deadline = time.time() + 120
        while time.time() < deadline:
            time.sleep(1.0)
            if not proc_alive(new_pid):
                self._log("[fail] 新进程 %d 启动后消失，稍后整轮重试" % new_pid)
                inst.note = "新进程消失"
                time.sleep(10)
                inst.status = S_RESTART
                threading.Thread(target=self._restart_flow,
                                 args=(inst,), daemon=True).start()
                return
            for pid, h, t in enum_game_windows():
                if pid == new_pid:
                    hwnd, title = h, t
                    if "([0])" in t:
                        break
            if hwnd and "([0])" in (title or ""):
                break
        if not (hwnd and "([0])" in (title or "")):
            inst.note = "重启后未见登录界面"
            self._log("[fail] p%d 重启后 120s 未见登录界面" % old_pid)
            return
        # 换绑并补种
        inst.pid = new_pid
        inst.name = "p%d" % new_pid
        inst.title = title
        self._do_plant(inst, hwnd)   # 成功→S_WAIT；之后监控自动拉任务
        self._log("p%d → 新 PID=%d 播种/登录流程接管完成" % (old_pid, new_pid))

    # ---------- 录制轮询 ----------
    def _tick(self):
        try:
            self._poll_record()
        except Exception:
            pass
        self._refresh_tree()
        self._drain_log()
        self.after(150, self._tick)

    def _poll_record(self):
        inst = self.recording_target
        if inst is None:
            self._click_q.clear()
            return
        # ★该号登录成功即自动停止（登录后的游戏点击不录）
        if inst.status == S_ONLINE or LOGGED_IN_RE.search(inst.title or ""):
            self._click_q.clear()
            self._stop_rec("%s 已登录" % inst.slot)
            return
        clicks = self._clicks_store().setdefault(inst.slot, [])
        while self._click_q:
            sx, sy = self._click_q.popleft()
            h = hwnd_at_screen(sx, sy)
            if not h:
                continue
            cx, cy = screen_to_client(h, sx, sy)
            now = time.time()
            dt = round(now - self._last_click_t, 2) if self._last_click_t else 0.6
            self._last_click_t = now
            clicks.append({"x": int(cx), "y": int(cy), "dt": dt})
            if len(clicks) > 40:
                del clicks[:-40]
            self.lbl_rec.config(text="录制中: %s（已录 %d 步）" % (inst.slot, len(clicks)))
            self._log("录制 %s 点击 (%d,%d) dt=%.2f" % (inst.slot, cx, cy, dt))

    def _refresh_tree(self):
        with self.lock:
            insts = list(self.instances)
        self.tree.delete(*self.tree.get_children())
        for i in insts:
            self.tree.insert("", "end", iid=str(i.seq), values=(
                i.pid or "-", i.role_cn, i.status, i.title or "", i.note or ""))

    def _drain_log(self):
        if not self.logq:
            return
        self.txt.config(state="normal")
        while self.logq:
            self.txt.insert("end", self.logq.pop(0) + "\n")
        self.txt.see("end")
        self.txt.config(state="disabled")

    def _log(self, msg):
        stamp = time.strftime("%H:%M:%S")
        line = "%s %s" % (stamp, msg)
        self.logq.append(line)
        if len(self.logq) > 400:
            del self.logq[:-200]
        # ★日志落盘：GUI 关掉/异常退出后仍有完整证据可查
        try:
            with open(os.path.join(ROOT, "pp_gui.log"), "a",
                      encoding="utf-8", errors="replace") as f:
                f.write(time.strftime("%m-%d ") + line + "\n")
        except Exception:
            pass

    def _on_close(self):
        """关闭兜底：存配置 → 卸载鼠标钩子 → 强制退出（钩子/后台线程不清场
        会导致窗口关不掉，os._exit 保证必关）。"""
        try:
            self._persist_instances()
        except Exception:
            pass
        try:
            self._team_watch_stop.set()
        except Exception:
            pass
        try:
            if getattr(self, "_hook", None):
                user32.UnhookWindowsHookEx(self._hook)
        except Exception:
            pass
        try:
            self.destroy()
        except Exception:
            pass
        os._exit(0)

    def _persist_instances(self):
        with self.lock:
            self.cfg["instances"] = [
                {"role": i.role, "pid": i.pid, "name": i.name, "title": i.title}
                for i in self.instances]
        self._save_cfg()

    def _stop_all(self):
        ps = ("Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match "
              "'run_unlimited_test|member_sell_loop' -and $_.ProcessId -ne %d } | "
              "ForEach-Object { Stop-Process -Id $_.ProcessId -Force; "
              "Write-Output $_.ProcessId }" % os.getpid())
        r = subprocess.run(["powershell", "-NoProfile", "-c", ps],
                           capture_output=True, text=True, timeout=30)
        killed = [x for x in (r.stdout or "").split() if x.isdigit()]
        self._log("已停止任务进程 %d 个: %s" % (len(killed), ",".join(killed) or "无"))
        self._persist_instances()


if __name__ == "__main__":
    app = PPApp()
    app.protocol("WM_DELETE_WINDOW", app._on_close)
    app.mainloop()
