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

        # ★2026-09-07 可观测性：squad_auto_team 的 _log 原本只 print 到
        #   stdout（GUI 无控制台 → 全程丢失）。组队/走位/建队每一步的内部
        #   日志因此不可见（只能靠肉眼观察客户端），桥接到 GUI 日志落地。
        self._bridge_sat_log()

        self._build_ui()
        threading.Thread(target=self._monitor_loop, daemon=True).start()
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
        port = PORTS[self._port_i % len(PORTS)]
        self._port_i += 1
        ok = plant(inst.pid, inst.name, port)
        if ok:
            inst.status, inst.note = S_WAIT, "播种成功"
            self._log("p%d 播种成功 ✓（%s）" % (inst.pid, inst.name))
            if self._clicks_store().get(inst.slot):
                threading.Thread(target=self._replay_login,
                                 args=(inst, hwnd), daemon=True).start()
            else:
                self._log("p%d 等待手动登录（%s 无登录录制：选中该实例点【录制登录点击】"
                          "后手动登录一次即可）" % (inst.pid, inst.slot))
        else:
            inst.status, inst.note = S_PLANT, "播种失败，重试中"
            time.sleep(3)
            ok2 = plant(inst.pid, inst.name, port)
            if ok2:
                inst.status, inst.note = S_WAIT, "播种成功(重试)"
                self._log("p%d 播种成功(重试) ✓" % inst.pid)
            else:
                inst.status, inst.note = S_PLANT, "播种失败"
                self._log("p%d 播种失败 ✗（窗口将保持登录界面，可手动处理）"
                          % inst.pid)

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
            if inst.pid in self._rejoining:
                return
            self._rejoining.add(inst.pid)
            if inst.role == "leader":
                sat.prep_leader(inst.pid)
            else:
                cap = self.cap_world or self._find_cap_world()
                if cap:
                    sat.member_tp_and_apply(inst.pid, cap, tries=3)
                else:
                    ZGUI.zhuagui_teleport("file://pzxy_p%d" % inst.pid,
                                          hwnd=find_hwnd_by_pid(inst.pid),
                                          dest="大唐官府", verbose=True)
        except Exception as e:
            self._log("p%d 归队异常: %s" % (inst.pid, e))
        finally:
            self._rejoining.discard(inst.pid)
            inst.status, inst.note = S_ONLINE, "重登完成"
            time.sleep(2.0)
            self._spawn_task(inst)

    def _start_all_tasks(self):
        """【启动脚本】= 组队（传送/走位/申请/批准/天覆阵）→ 按角色拉任务。"""
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

            # ---- 阶段1：全员并行传送 ----
            self._log("[autoTeam] 阶段1: %d 人并行传送 %s"
                      % (len(insts), sat.TP_DEST))
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
                  for i in insts]
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
                    # 阶段1 传送失败的就地补传
                    sat.member_tp_and_apply(m.pid, cap, tries=2,
                                            tp_first=not tp_ok.get(m.pid))
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
            if inst.role == "leader":
                cmd = [PYEXE, RUN_UNLIMITED, "--gateway", gw, "--role", role_name,
                       "--timeout", "20", "--wait-dialog", "1.2"]
            else:
                cmd = [PYEXE, MEMBER_LOOP, "--pid", str(inst.pid), "--gateway", gw]
            subprocess.Popen(cmd, cwd=ROOT, creationflags=CREATE_NO_WINDOW,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
        self._kill_stale_tasks()   # 启动先清一遍历史僵尸
        while not self._team_watch_stop.wait(15):
            try:
                stale_scan_n += 1
                hb_n += 1
                if stale_scan_n % 4 == 0:   # ~每分钟清一次残留任务脚本
                    self._kill_stale_tasks()
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
            lw = "file://pzxy_p%d" % leader_pid
            # 队长回等待点（在队中传送可能无效，走位仍有效；失败沿用旧坐标）
            cap = sat.prep_leader(leader_pid)
            if cap is not None:
                self.cap_world = cap
            cap = self.cap_world
            if cap is None:
                self._log("[看门狗] 补组失败：无队长坐标")
                return
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
                        sat.member_tp_and_apply(m.pid, cap, tries=2,
                                                tp_first=False)
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
        with self.lock:
            insts = list(self.instances)
        wins = {pid: (pid, hwnd, title) for pid, hwnd, title in enum_game_windows()}
        for inst in insts:
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

    def _begin_restart(self, inst):
        inst.status = S_RESTART
        inst.note = "掉线重启中"
        threading.Thread(target=self._restart_flow, args=(inst,), daemon=True).start()

    def _restart_flow(self, inst):
        """掉线全闭环：杀旧任务 → 重启游戏 → 补种 → 重放登录 → 拉起任务。"""
        old_pid = inst.pid
        try:
            kill_task_process(old_pid)
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
