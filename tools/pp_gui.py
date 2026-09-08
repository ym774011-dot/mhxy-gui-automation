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


class PPApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PP GUI — 胖子西游 启动/播种/掉线重连一体机")
        self.geometry("860x620")
        self.minsize(760, 520)

        self.cfg = self._load_cfg()
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
        self._reteam_running = False
        self._watch_started = False
        self._rejoining = set()           # 正在归队流程的实例 pid（防双驱动）
        self.paused = False               # ★暂停接管：True=自动化全面撒手
        # ★2026-09-09 tp 健康检查状态：pid -> 连续消失计数（服务器抹 tp 时
        #   进程活着/标题在线但 Lua 主状态亡，任务脚本会无限空转——用户指令：
        #   这种情况 GUI 直接杀游戏重启）
        self._tp_fail = {}
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
                cap = self.cap_world or self._find_cap_world()
                if cap:
                    _lp = next((i.pid for i in self.instances
                                if i.role == "leader" and i.status == S_ONLINE), None)
                    sat.member_tp_and_apply(inst.pid, cap, tries=3,
                                            leader_pid=_lp)
                else:
                    ZGUI.zhuagui_teleport("file://pzxy_p%d" % inst.pid,
                                          hwnd=find_hwnd_by_pid(inst.pid),
                                          dest="大唐官府", verbose=True)
        except Exception as e:
            self._log("p%d 归队异常: %s" % (inst.pid, e))
        finally:
            self._rejoining.discard(inst.pid)
            inst.status, inst.note = S_ONLINE, "重登完成"
            if not self.paused:
                time.sleep(2.0)
                self._spawn_task(inst)

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

        阶段1 全员并行散人传送（先传后组：队伍成员不能传送）
        阶段2 队长走位[139,80]（走位途中不点组队图标）
        阶段3 建队
        阶段4 队员并行申请入队
        阶段5 队长批准至满员 → 天覆阵
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
                if mem >= len(insts):
                    self._log("[autoTeam] Lua 队伍读数 %d/%d 已满员 → 跳过组队，直接执行任务"
                              % (mem, len(insts)))
                    self._finish_tasks(insts)
                    return
                self._log("[autoTeam] Lua 队伍读数 %d/%d 未满员 → 走组队流程"
                          % (mem, len(insts)))

            # ---- 阶段1：队员并行传送（队长不传） ----
            # ★2026-09-08 冗余消除：阶段2 prep_leader 第一步就是队长传送+走位，
            #   这里再传队长 = 队长连传两次（12:55 实锤：阶段1 传送完成 1s 后
            #   prep_leader 又传一次）。队长由阶段2 统一负责。
            movers = [i for i in insts if i.role != "leader"]
            self._log("[autoTeam] 阶段1: %d 名队员并行传送 %s（队长由阶段2 负责）"
                      % (len(movers), sat.TP_DEST))
            tp_ok = {}

            def _tp_one(inst):
                inst.status, inst.note = S_TEAM, "传送%s" % sat.TP_DEST
                try:
                    tp_ok[inst.pid] = sat._teleport(inst.pid)
                    self._log("p%d 传送%s" % (inst.pid,
                              "完成 ✓" if tp_ok.get(inst.pid) else "失败"))
                except Exception as e:
                    tp_ok[inst.pid] = False
                    self._log("p%d 传送异常: %s" % (inst.pid, e))

            ts = [threading.Thread(target=_tp_one, args=(i,), daemon=True)
                  for i in movers]
            for t in ts:
                t.start()
            for t in ts:
                t.join(180)

            if leader is None:
                self._log("[autoTeam] 无队长在线，队员只传送待命")
                self._finish_tasks(insts)
                return

            # ---- 阶段2：队长走位 [139,80] ----
            leader.status, leader.note = S_TEAM, "走位[139,80]"
            self._log("[autoTeam] 阶段2: 队长走位[139,80]")
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

            # ---- 阶段3：建队 ----
            self._log("[autoTeam] 阶段3: 建队")
            if not sat.create_team(leader.pid, cap):
                self._log("[autoTeam] 建队失败，重试一次")
                if not sat.create_team(leader.pid, cap):
                    self._log("[autoTeam] 建队失败，只拉任务不组队")
                    self._finish_tasks(insts)
                    return

            # ---- 阶段4：队员并行申请（阶段1 已传送，不再重复传）----
            self._log("[autoTeam] 阶段4: %d 名队员并行申请入队" % len(members))

            def _apply_one(m):
                m.status, m.note = S_TEAM, "申请入队"
                try:
                    # 阶段1 传送失败的就地补传；传 leader_pid 供地图对账联动
                    sat.member_tp_and_apply(m.pid, cap, tries=2,
                                            tp_first=not tp_ok.get(m.pid),
                                            leader_pid=leader.pid)
                except Exception as e:
                    self._log("p%d 申请异常: %s" % (m.pid, e))

            ts = [threading.Thread(target=_apply_one, args=(m,), daemon=True)
                  for m in members]
            for t in ts:
                t.start()
            for t in ts:
                t.join(900)

            # ---- 阶段5：批准 + 天覆阵 ----
            self._log("[autoTeam] 阶段5: 队长批准申请")
            mem = sat.approve_loop(leader.pid, 1 + len(members),
                                   timeout_s=600.0)
            self._log("[autoTeam] 批准结束: 成员=%s/目标=%s"
                      % (mem, 1 + len(members)))
            if mem and mem >= 1 + len(members):
                if sat.do_formation(leader.pid):
                    self._log("[autoTeam] 天覆阵完成 ✓")
                else:
                    self._log("[autoTeam] 阵法未确认（不阻断任务）")
            else:
                self._log("[autoTeam] 未满员，跳过阵法")
                # approve_loop 结束时队伍面板是开着的，关掉再拉任务，
                # 否则任务点击落在面板上
                lhwnd = find_hwnd_by_pid(leader.pid)
                if lhwnd:
                    ZGUI.post_click(lhwnd, 570, 583,
                                    gateway="file://pzxy_p%d" % leader.pid)
            self._finish_tasks(insts)
        except Exception as e:
            import traceback
            self._log("[autoTeam] 组队流程异常: %s" % e)
            self._log(traceback.format_exc())
        finally:
            self.teamflow_running = False

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
                self._spawn_task(i)
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
                    if _dismiss_popup(hwnd):
                        self._log("p%d 检测到系统弹窗(%s) → 已点确定/关闭"
                                  % (pid, (title or "")[:30]))
            except Exception:
                pass

    def _finish_tasks(self, insts):
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
                             args=(leader.pid, len(insts)),
                             daemon=True).start()

    def _spawn_task(self, inst):
        """按角色拉起任务脚本（已在跑则跳过）。"""
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
        if process_alive_for(cmdlines, inst.pid, inst.role == "leader"):
            self._log("p%d 任务脚本已在跑，跳过" % inst.pid)
            return
        gw = "file://pzxy_p%d" % inst.pid
        title = inst.title or next(
            (t for p, _h, t in enum_game_windows() if p == inst.pid), "")
        rm = ROLE_RE.search(title or "")
        role_name = rm.group(1).strip() if rm else ("p%d" % inst.pid)
        try:
            CREATE_NO_WINDOW = 0x08000000
            # ★2026-09-09 尸检通道：此前 stderr=DEVNULL，任务脚本崩溃 traceback
            #   直接丢弃（07:28 leader 闯关完成后静默死亡、昨夜 04:38 同款，
            #   死因永远查不到）。stdout/stderr 全落 logs/task_p<pid>_run.log。
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

    # ---------- 队伍完整性看门狗（队长侧） ----------
    def _team_watchdog(self, leader_pid, expect_members):
        """每 15s 判定队伍人数：满员不动；缺员 → 打断抓鬼 → 补组队 →
        满员自动恢复抓鬼。队员掉线由 GUI 重启重登后走 _rejoin_flow 归队，
        这里只负责队长侧的判定/打断/批准/恢复。"""
        self._log("[看门狗] 启动（目标 %d 人，每 15s 判定）" % expect_members)
        stale_scan_n = 0
        hb_n = 0
        bskip_n = 0
        self._kill_stale_tasks()   # 启动先清一遍历史僵尸
        while not self._team_watch_stop.wait(15):
            try:
                if self.paused:
                    continue   # ★暂停接管：看门狗只挂起不动作（恢复后自动续）
                stale_scan_n += 1
                hb_n += 1
                if stale_scan_n % 4 == 0:   # ~每分钟清一次残留任务脚本
                    self._kill_stale_tasks()
                # ★2026-09-09 任务脚本死亡自动补拉：07:28 实证 leader 脚本闯关
                #   完成后静默死亡（stderr 被 DEVNULL 吞掉），全队发呆无人管——
                #   掉线闭环只管游戏进程，没人管任务脚本进程。每 ~1min 巡检
                #   在线实例，任务脚本不在了就补拉（_spawn_task 自带防双跑）。
                if stale_scan_n % 4 == 2 and not self.teamflow_running:
                    with self.lock:
                        _online = [i for i in self.instances
                                   if i.status == S_ONLINE]
                    for it in _online:
                        try:
                            _ok, _cls = running_squad_cmdlines_ex()
                            if _ok and not process_alive_for(
                                    _cls, it.pid, it.role == "leader"):
                                self._log("p%d 任务脚本已死 → 自动补拉" % it.pid)
                                self._spawn_task(it)
                        except Exception as e:
                            self._log("p%d 任务脚本巡检异常: %s" % (it.pid, e))
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
                            self._spawn_task(i)
                    continue
                # 缺员
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
        ps = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
              "Where-Object { $_.CommandLine -match "
              "'run_unlimited_test|member_sell_loop' } | "
              "ForEach-Object { \"$($_.ProcessId)|$($_.CommandLine)\" }")
        try:
            r = subprocess.run(["powershell", "-NoProfile", "-c", ps],
                               capture_output=True, encoding="gbk",
                               errors="replace", timeout=30)
        except Exception as e:
            self._log("打断任务脚本查询失败: %s" % e)
            return
        token = "pzxy_p%d" % pid
        key = "run_unlimited_test" if leader else "member_sell_loop"
        for line in (r.stdout or "").splitlines():
            line = line.strip()
            if "|" not in line:
                continue
            cp, cl = line.split("|", 1)
            if key in cl and token in cl:
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
        ps = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
              "Where-Object { $_.CommandLine -match "
              "'run_unlimited_test|member_sell_loop' } | "
              "ForEach-Object { \"$($_.ProcessId)|$($_.CommandLine)\" }")
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
            got = sat.approve_loop(leader_pid, expect_members, timeout_s=420.0)
            self._log("[看门狗] 补组批准结束: %s/%s" % (got, expect_members))
            if got and got >= expect_members:
                sat.do_formation(leader_pid)
                self._watch_interrupted = False
                with self.lock:
                    online = [i for i in self.instances
                              if i.status == S_ONLINE]
                for i in online:
                    self._spawn_task(i)
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
                #   每 4 轮查一次（监控 2s/轮 → ~8s 一次），连续 3 次明确 nil
                #   (~24s) 才重启；超时/未知不计数（防游戏忙碌误杀）。
                if inst.status == S_ONLINE and logged and not self.teamflow_running:
                    self._tp_tick += 1
                    if self._tp_tick % 4 == 0:
                        r = self._tp_alive(inst.pid)
                        if r is True:
                            self._tp_fail[inst.pid] = 0
                        elif r is False:
                            n = self._tp_fail.get(inst.pid, 0) + 1
                            self._tp_fail[inst.pid] = n
                            if n == 1:
                                self._log("p%d tp 状态消失（第%d次，疑似服务器抹除）"
                                          % (inst.pid, n))
                            if n >= 3:
                                self._log("p%d tp 连续消失 %d 次 → 杀游戏重启闭环"
                                          % (inst.pid, n))
                                self._begin_restart(inst)

    def _begin_restart(self, inst):
        inst.status = S_RESTART
        inst.note = "掉线重启中"
        self._tp_fail.pop(inst.pid, None)   # 重启即清 tp 失败计数
        threading.Thread(target=self._restart_flow, args=(inst,), daemon=True).start()

    def _tp_alive(self, pid):
        """Lua 主状态存活检查（★2026-09-09 掉线闭环新增盲区补测）。

        进程活着、窗口标题仍在线，但 tp 被服务器整点/维护事件抹掉（06:47
        全队实证）——任务脚本会补旗/回长安无限空转。此检查返回：
          True  = tp 存活
          False = Lua 明确回答 tp 为 nil（状态已亡）
          None  = worker 死/超时/执行失败（未知，不计数，防误杀）
        """
        try:
            w = PzxyWorker(name="p%d" % pid)
            if not w.is_alive():
                return None
            ok, val = w.cmd("__out = tostring(tp ~= nil)", timeout=2.5)
            if not ok:
                return None
            return str(val).strip() == "true"
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
