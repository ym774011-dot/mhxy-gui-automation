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
                           plant, process_alive_for, running_squad_cmdlines)
from library.pzxy_ipc import PzxyWorker                                    # noqa: E402
import squad_auto_team as sat                                              # noqa: E402
import ctypes                                                              # noqa: E402
from ctypes import wintypes                                                # noqa: E402

PYEXE = sys.executable
GATEWAY_PLANT = r"E:\DS\mhxy-mcp-gateway\tools\pzxy_plant.py"
RUN_UNLIMITED = os.path.join(ROOT, "run_unlimited_test.py")
MEMBER_LOOP = os.path.join(HERE, "member_sell_loop.py")
CONFIG_PATH = os.path.join(ROOT, "test_data", "pp_gui_config.json")
PORTS = [18091, 18092, 18093, 18094, 18095, 18096, 18097, 18098]

user32 = ctypes.windll.user32

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

    def __init__(self, role, pid=None, name=None, status=S_LAUNCH, title=""):
        Instance._seq += 1
        self.seq = Instance._seq
        self.role = role            # 'leader' | 'member'
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
        self.recording = False
        self._last_click_t = 0.0
        self._prev_btn = False
        self._port_i = 0
        # 组队协调：GUI 登录后只做播种+掉线监控；【启动脚本】才组队+拉任务
        self.cap_world = None       # 队长就绪后的世界坐标 [139,80]
        self.team_done = False      # 组队阶段结束
        self.scripts_started = False  # 已点过【启动脚本】（之后重登=自动归队）
        self.teamflow_running = False

        self._build_ui()
        threading.Thread(target=self._monitor_loop, daemon=True).start()
        self.after(200, self._tick)

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
        self.var_rec = tk.BooleanVar(value=False)
        self.chk_rec = ttk.Checkbutton(
            bar, text="记录登录点击（打开后手动登录一次即录制）",
            variable=self.var_rec, command=self._toggle_rec)
        self.chk_rec.pack(side="left", padx=12)
        self.lbl_rec = ttk.Label(bar, text="已录 %d 次点击"
                                 % len(self.cfg.get("login_clicks", [])))
        self.lbl_rec.pack(side="left")
        ttk.Button(bar, text="清空录制", width=8,
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

    def _toggle_rec(self):
        self.recording = self.var_rec.get()
        self._log("录制登录点击: %s（打开后到游戏窗口手动登录一次）"
                  % ("开" if self.recording else "关"))
        if not self.recording and self.cfg.get("login_clicks"):
            self._save_cfg()

    def _clear_rec(self):
        self.cfg["login_clicks"] = []
        self.lbl_rec.config(text="已录 0 次点击")
        self._save_cfg()
        self._log("已清空登录点击录制")

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
                        self._spawn_task(inst)
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
            if self.cfg.get("login_clicks"):
                threading.Thread(target=self._replay_login,
                                 args=(inst, hwnd), daemon=True).start()
            else:
                self._log("p%d 等待手动登录（未录制登录点击，可打开录制后登录一次）"
                          % inst.pid)
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
        """重放录制的登录点击（掉线重登录闭环）。"""
        clicks = self.cfg.get("login_clicks") or []
        if not clicks:
            return
        self._log("p%d 重放登录点击 %d 步…" % (inst.pid, len(clicks)))
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
        """从在线队长客户端读队长世界坐标（开面板刷新懒加载）。"""
        with self.lock:
            leaders = [i for i in self.instances
                       if i.role == "leader" and i.status == S_ONLINE]
        if not leaders:
            return None
        return sat._read_pos_via_panel(find_hwnd_by_pid(leaders[0].pid),
                                       "file://pzxy_p%d" % leaders[0].pid)

    def _rejoin_flow(self, inst):
        try:
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
        try:
            leader = next((i for i in insts if i.role == "leader"), None)
            members = [i for i in insts if i.role != "leader"]
            cap = None
            if leader:
                leader.status, leader.note = S_TEAM, "传送+走位[139,80]"
                cap = sat.prep_leader(leader.pid)
                if cap is None:
                    self._log("[autoTeam] 队长准备失败，重试一次")
                    time.sleep(20)
                    cap = sat.prep_leader(leader.pid)
                if cap is not None:
                    self.cap_world = cap
                    self._log("[autoTeam] 队长已就位 [139,80]，建队…")
                    if not sat.create_team(leader.pid, cap):
                        self._log("[autoTeam] 建队失败，重试一次")
                        if not sat.create_team(leader.pid, cap):
                            self._log("[autoTeam] 建队失败，只拉任务不组队")
                            cap = None
                else:
                    self._log("[autoTeam] 队长走位失败，只拉任务不组队")
            for m in members:
                m.status, m.note = S_TEAM, "传送+申请入队"
            if cap:
                for m in members:
                    sat.member_tp_and_apply(m.pid, cap, tries=2)
                mem = sat.approve_loop(leader.pid, 1 + len(members),
                                       timeout_s=600.0)
                self._log("[autoTeam] 批准结束: 成员=%s/目标=%s"
                          % (mem, 1 + len(members)))
                if mem and mem >= 1 + len(members):
                    if sat.do_formation(leader.pid):
                        self._log("[autoTeam] 天覆阵完成 ✓")
                else:
                    self._log("[autoTeam] 未满员，跳过阵法")
            elif members and not leader:
                # 没有队长在场：队员只传送待命
                for m in members:
                    ZGUI.zhuagui_teleport("file://pzxy_p%d" % m.pid,
                                          hwnd=find_hwnd_by_pid(m.pid),
                                          dest="大唐官府", verbose=True)
            self.scripts_started = True
            self.team_done = True
            for i in insts:
                i.status, i.note = S_ONLINE, "运行中"
                self._spawn_task(i)
            self._log("[autoTeam] 组队+任务脚本启动完成")
        except Exception as e:
            self._log("[autoTeam] 组队流程异常: %s" % e)
        finally:
            self.teamflow_running = False

    def _spawn_task(self, inst):
        """按角色拉起任务脚本（已在跑则跳过）。"""
        cmdlines = running_squad_cmdlines()
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

    # ---------- 监控（掉线闭环） ----------
    def _monitor_loop(self):
        while True:
            time.sleep(2.0)
            try:
                self._monitor_once()
            except Exception as e:
                self._log("监控异常: %s" % e)

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
                    self._log("p%d 窗口消失（待登录阶段）→ 重启闭环" % inst.pid)
                    self._begin_restart(inst)
            elif inst.status == S_ONLINE:
                if not logged:
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
        if not self.recording:
            self._prev_btn = False
            return
        down = bool(user32.GetAsyncKeyState(0x01) & 0x8000)
        if down and not self._prev_btn:
            pt = wintypes.POINT()
            user32.GetCursorPos(ctypes.byref(pt))
            h = hwnd_at_screen(pt.x, pt.y)
            if h:
                cx, cy = screen_to_client(h, pt.x, pt.y)
                now = time.time()
                dt = round(now - self._last_click_t, 2) if self._last_click_t else 0.6
                self._last_click_t = now
                clicks = self.cfg.setdefault("login_clicks", [])
                clicks.append({"x": int(cx), "y": int(cy), "dt": dt})
                if len(clicks) > 40:
                    del clicks[:-40]
                self.lbl_rec.config(text="已录 %d 次点击" % len(clicks))
                self._log("录制点击 (%d,%d) dt=%.2f" % (cx, cy, dt))
        self._prev_btn = down

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
        self.logq.append("%s %s" % (stamp, msg))
        if len(self.logq) > 400:
            del self.logq[:-200]

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
    app.protocol("WM_DELETE_WINDOW", lambda: (app._persist_instances(),
                                              app.destroy()))
    app.mainloop()
