# -*- coding: utf-8 -*-
r"""guardStats 兜底疗效观测器（只读）——Task A-OBS-001。

用途
----
判定 2026-08-29 那次修复「把未保护的 lua51.dll!lua_call 换成语义等价的
lua_pcall(L,n,r,0)，把致命错误吞掉」到底有没有救活游戏。

该修复被定性为「缓解」而非「根治」：它把「立刻 panic → 弹框 → exit()」
改成「吞掉错误 → 引擎带病继续跑」。修复前实测过一次：某实例带兜底跑 56
分钟后抓到一次真实错误被拦下（attempt to call a boolean value），没弹框，
但进程 4 秒后仍退出。本脚本就是用来把这个「4 秒后偷偷死」的信号抓实。

用法（在 GUI 手动启动 farm 期间另开一个终端跑）
----------------------------------------------
E:/py/python.exe tools/_watch_guardstats.py --duration 20 --interval 5
E:/py/python.exe tools/_watch_guardstats.py --duration 1800 --interval 5
E:/py/python.exe tools/_watch_guardstats.py --duration 0 --interval 5 | tee watch.log

观测内容
--------
1. 网关 /api/status 的 guardStats：calls / errors / userdataErr / lastMsg
2. 游戏实例身份与存活：result.pid 是否存活、是否出现新的 快乐西游.exe、
   角色 ID（窗口标题里的 [701529]）是否还是同一个
3. 致命弹窗只读探测（class #32770 顶层 dialog，标题/子控件文本含「致命的错误」
   /「致命错误」/「this arg is not a userdata!」）—— 探测到只报告，**不关闭、不点击**

判定规则
--------
  PASS          errors 在涨，且每次 errors 变化后 10s 内游戏 PID 都没换号
                → 兜底真的救活了（错误被吞掉后引擎继续跑）
  FAIL          (a) 出现致命弹窗 → 兜底没拦住
                (b) errors 变化后 10s 内 PID 换号 → 只是把「立刻弹框」
                    改成「稍后静默退出」
  INCONCLUSIVE  (c) 网关失联到观测结束，或采样连续失败 → 观测链路断了
                (d) guardStats.calls 长时间冻结（排除 TTL 误判后）→ 计数不可信
                (e) 全程 errors=0 → 兜底根本没被考验，无样本

★ 采样间隔硬约束：网关 /api/status 有 2s TTL 缓存（gateway.py 的
  _SSTAT_TTL = 2.0）。间隔 ≤2s 会反复拿到同一份过期快照，历史上曾因此误判
  「计数冻结」。故默认 --interval=5，且脚本强制下限 3s。

★ 网关可能重连/重启，result.pid 随之变化。脚本用两条独立线索区分：
  - 网关自己的 PID：命令行含 "gateway.py" 且含 "--port <port>" 的进程
  - 网关重启的旁证：result.uptimeMs 骤降（比上次观测值小很多）
  只有「网关自身 PID 未变 + uptimeMs 未骤降」时，result.pid 变化才记为
  游戏实例换号。

只读纪律（本脚本严格遵守）
--------------------------
不启动/停止 farm、不重启或杀死网关、不触发网关自愈、不写 G:\00\ 下任何文件、
不改 WORLD_BOSS.py。所有探测均为读取；致命弹窗只探测不关闭。
"""
import argparse
import json
import re
import sys
import time
import urllib.request
from datetime import datetime

sys.path.insert(0, __import__("os").path.dirname(
    __import__("os").path.dirname(__import__("os").path.abspath(__file__))))

GAME_EXE = "快乐西游.exe"
FATAL_MIN_INTERVAL = 3.0          # /api/status TTL 2s，采样间隔强制下限
EXIT_WINDOW_SEC = 10.0            # errors 变化后，判定「静默退出」的观察窗口
HTTP_TIMEOUT = 5.0
ROLE_RE = re.compile(r"\[(\d{4,})\]")
FATAL_TEXT_KEYS = ("致命的错误", "致命错误", "not a userdata", "userdata")

PASS, FAIL, INCONCLUSIVE = "PASS", "FAIL", "INCONCLUSIVE"


def _now():
    return datetime.now().strftime("%H:%M:%S")


def _fmt_delta(v):
    return f"{v:+d}" if v else "0"


# ---------------------------------------------------------------- 探测原语
def fetch_status(gateway):
    """GET /api/status，返回 result 字典；失败抛异常。"""
    req = urllib.request.Request(gateway.rstrip("/") + "/api/status",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        raw = json.loads(resp.read().decode("utf-8", "replace"))
    if not raw.get("ok"):
        raise RuntimeError(f"网关返回 ok=False: {raw.get('error')}")
    return raw.get("result") or {}


def list_game_pids():
    """返回所有 快乐西游.exe 的 PID 集合。"""
    import psutil
    out = set()
    for p in psutil.process_iter(["pid", "name"]):
        if (p.info.get("name") or "").lower() == GAME_EXE.lower():
            out.add(int(p.info["pid"]))
    return out


def pid_alive(pid):
    """PID 是否存活且确实是游戏进程（PID 复用时名字会对不上）。"""
    import psutil
    if not pid or not psutil.pid_exists(int(pid)):
        return False
    try:
        return psutil.Process(int(pid)).name().lower() == GAME_EXE.lower()
    except Exception:
        return False


def find_gateway_pids(port):
    """返回网关自身进程 PID 集合（命令行含 gateway.py 且含 --port <port>）。"""
    import psutil
    out = set()
    for p in psutil.process_iter(["pid", "cmdline"]):
        try:
            cl = " ".join(p.info.get("cmdline") or [])
        except Exception:
            continue
        if "gateway.py" in cl and (f"--port {port}" in cl or f"--port={port}" in cl):
            out.add(int(p.info["pid"]))
    return out


def map_role_ids():
    """返回 {pid: 角色ID}（标题里 '然学[701529]' 这种）。

    ★ 实锤坑（2026-08-29 实测）：游戏主窗口 class=Galaxy2DEngine 在多开器场景下
    不是顶层窗口，而是嵌套在顶层 WTWindow 下的子窗口，只 EnumWindows 枚举顶层
    会拿不到标题，role 恒为 '-'。故必须递归遍历子窗口树。
    """
    import win32gui
    import win32process
    out = {}

    def _visit(hwnd):
        try:
            title = win32gui.GetWindowText(hwnd) or ""
        except Exception:
            title = ""
        m = ROLE_RE.search(title)
        if m:
            try:
                _tid, pid = win32process.GetWindowThreadProcessId(hwnd)
            except Exception:
                pid = 0
            out.setdefault(int(pid), m.group(1))
        try:
            win32gui.EnumChildWindows(hwnd, lambda h, _l: (_visit(h), True)[1], 0)
        except Exception:
            pass

    def _top(hwnd, _lp):
        _visit(hwnd)
        return True

    win32gui.EnumWindows(_top, 0)
    return out


def probe_fatal_dialog():
    """只读探测引擎致命弹窗。返回 [(hwnd, pid, title, hit_text), ...]。

    只抄 WORLD_BOSS._dismiss_engine_error_dialog() 的探测部分：
    不含任何 PostMessage / BM_CLICK / 关闭动作。
    """
    import win32gui
    import win32process
    hits = []

    def _text_of(hwnd):
        try:
            return win32gui.GetWindowText(hwnd) or ""
        except Exception:
            return ""

    def _cb(hwnd, _lp):
        try:
            cls = win32gui.GetClassName(hwnd) or ""
        except Exception:
            return True
        if cls != "#32770":
            return True
        # MessageBox 的提示文本多数在子控件（Static）上，标题可能很朴素，
        # 所以标题 + 全部子窗口文本一起匹配。只读，不发任何消息。
        head = _text_of(hwnd)
        parts = [head]

        def _child(h, _l):
            parts.append(_text_of(h))
            return True

        try:
            win32gui.EnumChildWindows(hwnd, _child, 0)
        except Exception:
            pass
        full = "\n".join(p for p in parts if p)
        hit = next((k for k in FATAL_TEXT_KEYS if k in full), None)
        if hit:
            try:
                _tid, pid = win32process.GetWindowThreadProcessId(hwnd)
            except Exception:
                pid = 0
            hits.append((int(hwnd), int(pid), head[:40], hit))
        return True

    win32gui.EnumWindows(_cb, 0)
    return hits


# ---------------------------------------------------------------- 观测主体
class Watcher:
    def __init__(self, gateway, interval, duration):
        self.gateway = gateway
        self.interval = interval
        self.duration = duration
        self.port = self._parse_port(gateway)
        self.t0 = time.time()

        self.samples = 0
        self.fetch_fail = 0
        self.consecutive_fail = 0
        self.down_since = None
        self.down_total = 0.0

        self.prev_calls = None
        self.calls_frozen_runs = 0
        self.prev_errors = None
        self.prev_up = None
        self.gw_pids = set()
        self.gw_pid_changes = []
        self.gw_restart_marks = []     # [t, ...] 网关重启/重连时刻
        self.prev_pid = None
        self.pid_changes = []          # [(t, old, new, reason)]
        self.known_game_pids = set()
        self.new_game_pids = []        # [(t, pid)]
        self.error_events = []         # dict(t, errors, msg, verdict, delay)
        self.dialog_events = []        # [(t, pid, title, hit)]
        self.role_seen = {}            # pid -> role_id
        self.last_role = None
        self.last_msg = ""
        self.fatal_seen = False
        self.base = None               # 首次成功采样的 guardStats 基线
        self.base_pid = None

    @staticmethod
    def _parse_port(gateway):
        m = re.search(r":(\d+)", gateway or "")
        return m.group(1) if m else ""

    # ------------------------------------------------------------ 事件判定
    def _resolve_pending(self, now):
        """结算观察窗口已走完的 errors 事件。"""
        for ev in self.error_events:
            if ev["verdict"] != "PENDING":
                continue
            if now - ev["t"] < EXIT_WINDOW_SEC:
                continue
            late = [c for c in self.pid_changes
                    if ev["t"] < c[0] <= ev["t"] + EXIT_WINDOW_SEC]
            if late:
                ev["verdict"] = "SILENT_EXIT"
                ev["delay"] = round(late[0][0] - ev["t"], 1)
                print(f"[{_now()}] !!! FAIL 征兆：errors 跃迁后 {ev['delay']}s "
                      f"内游戏换号 {ev['pid']} -> {late[0][2]}", flush=True)
            else:
                ev["verdict"] = "SURVIVED"
                print(f"[{_now()}] === 好消息：errors 跃迁后 {EXIT_WINDOW_SEC:.0f}s "
                      f"内 PID 未换，引擎带病存活（errors={ev['errors']}）", flush=True)

    def _check_pid_change(self, now, pid, roles):
        """识别出真正的游戏换号（排除网关重启造成的 result.pid 变化）。"""
        new_role = roles.get(pid)
        if new_role:
            self.role_seen[pid] = new_role

        if self.prev_pid is None:
            self.prev_pid = pid
            if new_role:
                self.last_role = new_role
            return

        if pid == self.prev_pid:
            return

        # 换号证据（与网关侧变化无关，只看游戏本身）
        reasons = []
        if not pid_alive(self.prev_pid):
            reasons.append(f"旧PID {self.prev_pid} 已死")
        if new_role and self.last_role and new_role != self.last_role:
            reasons.append(f"角色ID {self.last_role}->{new_role}")

        # 网关侧变化证据：网关自身 PID 刚变过，或 uptimeMs 刚骤降过
        fresh = lambda t: (now - t) <= max(self.interval * 2, 10.0)
        gw_restart = any(fresh(t) for t in self.gw_restart_marks)

        if gw_restart and not reasons:
            # 网关重连/重启后 result.pid 自然跟着变，这不是游戏换号
            print(f"[{_now()}] ~~~ 网关侧变化：result.pid {self.prev_pid} -> {pid}"
                  f"（网关刚重启/重连，不记为游戏换号）", flush=True)
        else:
            self.pid_changes.append(
                (now, self.prev_pid, pid, "；".join(reasons) or "无直接证据"))
            print(f"[{_now()}] *** 跃迁：游戏实例换号 PID {self.prev_pid} -> {pid}"
                  f"（{'；'.join(reasons) or '无直接证据'}）", flush=True)

        self.prev_pid = pid
        if new_role:
            self.last_role = new_role

    # ------------------------------------------------------------ 主循环
    def run(self):
        print("=" * 74, flush=True)
        print(f"guardStats 兜底疗效观测（只读）  网关={self.gateway}", flush=True)
        print(f"interval={self.interval}s（下限 {FATAL_MIN_INTERVAL:.0f}s，"
              f"因 /api/status 有 2s TTL 缓存）"
              f"  duration={'不限' if not self.duration else str(self.duration) + 's'}",
              flush=True)
        print(f"静默退出观察窗口={EXIT_WINDOW_SEC:.0f}s   "
              f"只读纪律：不启停 farm / 不动网关 / 不关弹窗", flush=True)
        print("=" * 74, flush=True)

        try:
            self.known_game_pids = list_game_pids()
            self.gw_pids = find_gateway_pids(self.port)
        except Exception as e:
            print(f"[FATAL] 依赖缺失（psutil）：{e}", flush=True)
            return INCONCLUSIVE
        print(f"[init] 现存 {GAME_EXE}: {sorted(self.known_game_pids)}", flush=True)
        print(f"[init] 网关自身进程 PID: {sorted(self.gw_pids)}", flush=True)

        while True:
            now = time.time() - self.t0
            if self.duration and now >= self.duration:
                break
            try:
                self._sample(now)
            except Exception as e:      # 任一采样点出错不能让观测挂掉
                print(f"[{_now()}] [WARN] 采样点异常（已跳过）: "
                      f"{type(e).__name__}: {e}", flush=True)
            if self.duration and (time.time() - self.t0) >= self.duration:
                break
            time.sleep(self.interval)

        return self._summarize()

    def _sample(self, now):
        # ---- 1) 网关状态 ----
        try:
            res = fetch_status(self.gateway)
        except Exception as e:
            self.fetch_fail += 1
            self.consecutive_fail += 1
            if self.down_since is None:
                self.down_since = time.time()
                print(f"[{_now()}] *** 跃迁：网关失联（{type(e).__name__}: {e}）",
                      flush=True)
            print(f"[{_now()}] t={now:6.1f}s [网关失联 {self.consecutive_fail} 连] "
                  f"{type(e).__name__}: {e}", flush=True)
            self._probe_side(now, None)
            return

        if self.down_since is not None:
            self.down_total += time.time() - self.down_since
            print(f"[{_now()}] *** 跃迁：网关恢复（中断 "
                  f"{time.time() - self.down_since:.1f}s）", flush=True)
            self.down_since = None
        self.consecutive_fail = 0
        self.samples += 1

        pid = int(res.get("pid") or 0)
        ss = res.get("script_status") or res
        gs = ss.get("guardStats") or res.get("guardStats") or {}
        calls = int(gs.get("calls") or 0)
        errors = int(gs.get("errors") or 0)
        uderr = int(gs.get("userdataErr") or 0)
        last_msg = gs.get("lastMsg") or ""
        up_ms = int(ss.get("uptimeMs") or 0)
        up_s = up_ms / 1000.0

        # ---- 2) 网关自身 PID（用于区分网关重启 vs 游戏换号）----
        try:
            cur_gw = find_gateway_pids(self.port)
            if self.gw_pids and cur_gw and cur_gw != self.gw_pids:
                self.gw_pid_changes.append((now, sorted(self.gw_pids), sorted(cur_gw)))
                self.gw_restart_marks.append(now)
                print(f"[{_now()}] *** 跃迁：网关自身进程 PID 变化 "
                      f"{sorted(self.gw_pids)} -> {sorted(cur_gw)}（网关重启/重连）",
                      flush=True)
            if cur_gw:
                self.gw_pids = cur_gw
        except Exception as e:
            print(f"[{_now()}] [WARN] 网关进程枚举失败: {e}", flush=True)

        # uptimeMs 骤降 = 网关重启的第二个旁证（命令行枚举不到时兜底）
        try:
            if self.prev_up is not None and up_s < self.prev_up - max(5.0, self.prev_up * 0.1):
                self.gw_restart_marks.append(now)
                print(f"[{_now()}] *** 跃迁：网关 uptimeMs 骤降 "
                      f"{self.prev_up:.0f}s -> {up_s:.0f}s（网关重启）", flush=True)
        except Exception as e:
            print(f"[{_now()}] [WARN] uptimeMs 比对失败: {e}", flush=True)

        # ---- 3) 实例身份 / 存活 ----
        roles = self._safe(map_role_ids, {})
        self._check_pid_change(now, pid, roles)
        self._probe_side(now, pid)

        alive = pid_alive(pid)
        role = roles.get(pid) or self.role_seen.get(pid) or "-"

        # ---- 4) 计数跃迁 ----
        d_calls = 0 if self.prev_calls is None else calls - self.prev_calls
        if self.prev_calls is not None and d_calls <= 0:
            self.calls_frozen_runs += 1
            if self.calls_frozen_runs == 3:
                print(f"[{_now()}] *** 跃迁：guardStats.calls 连续 3 次无增长"
                      f"（{calls}），排除 TTL 后仍冻结 → 计数可能不可信", flush=True)
        elif d_calls > 0:
            self.calls_frozen_runs = 0

        if self.prev_errors is not None and errors != self.prev_errors:
            self.error_events.append({
                "t": now, "errors": errors, "msg": last_msg,
                "pid": pid, "verdict": "PENDING", "delay": None})
            print(f"[{_now()}] *** 跃迁：guardStats.errors "
                  f"{self.prev_errors} -> {errors}"
                  f"（userdataErr={uderr}）lastMsg={last_msg!r}", flush=True)
        if last_msg and last_msg != self.last_msg:
            self.last_msg = last_msg

        if self.base is None:
            # 基线：观测「开始前」兜底已经吞了多少错误。试跑时就遇到基线
            # errors=1 / lastMsg='attempt to call a table value'，必须在汇总里说清，
            # 否则会误以为全程无错误。
            self.base = {"calls": calls, "errors": errors, "uderr": uderr,
                         "msg": last_msg, "pid": pid}
            print(f"[init] 基线 guardStats: calls={calls} errors={errors} "
                  f"userdataErr={uderr} lastMsg={last_msg!r}", flush=True)
            if errors:
                print(f"[init] 注意：观测开始前兜底已吞掉 {errors} 次致命错误，"
                      f"而 PID {pid} 至今存活（uptime {up_s:.0f}s）", flush=True)

        self._resolve_pending(now)
        self.prev_calls, self.prev_errors, self.prev_up = calls, errors, up_s

        print(f"[{_now()}] t={now:6.1f}s pid={pid} alive={'Y' if alive else 'N'} "
              f"role={role} calls={calls}({_fmt_delta(d_calls)}) "
              f"errors={errors} udErr={uderr} up={up_s:.0f}s", flush=True)

    def _probe_side(self, now, pid):
        """弹窗探测 + 新游戏进程发现（与网关是否在线无关，独立执行）。"""
        try:
            hits = probe_fatal_dialog()
            for hwnd, dpid, title, hit in hits:
                if any(hwnd == h[1] for h in self.dialog_events):
                    continue
                self.dialog_events.append((now, hwnd, dpid, title, hit))
                self.fatal_seen = True
                own = "（属被观测实例）" if (pid and dpid == pid) else ""
                print(f"[{_now()}] !!! 跃迁：检测到引擎致命弹窗 hwnd=0x{hwnd:X} "
                      f"pid={dpid}{own} 命中={hit!r} 标题={title!r}（只读，未关闭）",
                      flush=True)
        except Exception as e:
            print(f"[{_now()}] [WARN] 弹窗探测失败: {type(e).__name__}: {e}",
                  flush=True)

        try:
            cur = list_game_pids()
            new = sorted(cur - self.known_game_pids)
            for np in new:
                self.new_game_pids.append((now, np))
                print(f"[{_now()}] *** 跃迁：出现新的 {GAME_EXE} PID={np}"
                      f"（可能是实例换号/重登）", flush=True)
            self.known_game_pids |= cur
        except Exception as e:
            print(f"[{_now()}] [WARN] 游戏进程枚举失败: {e}", flush=True)

    @staticmethod
    def _safe(fn, default):
        try:
            return fn()
        except Exception:
            return default

    # ------------------------------------------------------------ 汇总
    def _summarize(self):
        dur = time.time() - self.t0
        down = self.down_total + (time.time() - self.down_since
                                  if self.down_since else 0.0)
        surv = [e for e in self.error_events if e["verdict"] == "SURVIVED"]
        silent = [e for e in self.error_events if e["verdict"] == "SILENT_EXIT"]
        pend = [e for e in self.error_events if e["verdict"] == "PENDING"]

        verdict, why = self._verdict(surv, silent, pend, down)

        print("=" * 74, flush=True)
        print("观测汇总", flush=True)
        print("=" * 74, flush=True)
        print(f"观测时长     : {dur:.0f}s   采样点 {self.samples}   "
              f"取状态失败 {self.fetch_fail}   网关累计中断 {down:.0f}s", flush=True)
        print(f"网关自身PID  : {sorted(self.gw_pids)}"
              f"（变化 {len(self.gw_pid_changes)} 次）", flush=True)
        print(f"游戏实例     : 末次 PID={self.prev_pid}  角色ID={self.last_role}   "
              f"换号 {len(self.pid_changes)} 次   "
              f"新 {GAME_EXE} 出现 {len(self.new_game_pids)} 次", flush=True)
        added = 0
        if self.base:
            added = (self.prev_errors or 0) - self.base["errors"]
            print(f"基线         : pid={self.base['pid']} calls={self.base['calls']} "
                  f"errors={self.base['errors']} userdataErr={self.base['uderr']} "
                  f"lastMsg={self.base['msg']!r}", flush=True)
        print(f"末值         : calls={self.prev_calls} errors={self.prev_errors}"
              f"（观测期新增 errors {added}）", flush=True)
        print(f"guardStats   : errors 跃迁 {len(self.error_events)} 次"
              f"（存活 {len(surv)} / 静默退出 {len(silent)} / 窗口未走完 {len(pend)}）",
              flush=True)
        if self.last_msg:
            print(f"lastMsg      : {self.last_msg!r}", flush=True)
        print(f"致命弹窗     : {'出现过 ' + str(len(self.dialog_events)) + ' 次'
                              if self.dialog_events else '未出现'}", flush=True)
        print("-" * 74, flush=True)
        print(f"判定         : [{verdict}]", flush=True)
        print(f"依据         : {why}", flush=True)
        if pend:
            print(f"注意         : {len(pend)} 次 errors 跃迁发生在观测结束前不足 "
                  f"{EXIT_WINDOW_SEC:.0f}s，窗口未走完，未计入判定", flush=True)
        print("=" * 74, flush=True)
        return verdict

    def _verdict(self, surv, silent, pend, down):
        if self.dialog_events:
            return (FAIL, f"观测期间出现引擎致命弹窗 {len(self.dialog_events)} 次"
                          f"（pid={[d[2] for d in self.dialog_events]}），"
                          f"兜底没拦住")
        if silent:
            return (FAIL, f"errors 跃迁后 {EXIT_WINDOW_SEC:.0f}s 内游戏换号 "
                          f"{len(silent)} 次，延迟={[e['delay'] for e in silent]}s "
                          f"→ 只是把「立刻弹框」改成「稍后静默退出」")
        if self.samples == 0 or (down > 0 and self.samples <= 1):
            return (INCONCLUSIVE, f"网关基本不可达（采样成功 {self.samples} 次，"
                                  f"中断 {down:.0f}s），观测链路断了，计数不可信")
        if self.prev_errors is None:
            return (INCONCLUSIVE, "从未取到 guardStats，无法判定")
        if self.prev_errors == 0:
            return (INCONCLUSIVE, "全程 guardStats.errors=0，兜底未被考验"
                                  "（无失败样本，不能证明救活）"
                                  + (f"；calls 末值 {self.prev_calls}" if self.prev_calls else ""))
        if not self.error_events and self.base:
            return (INCONCLUSIVE, f"基线 errors 已为 {self.base['errors']}"
                                  f"（lastMsg={self.base['msg']!r}），但观测期内"
                                  f"无新增 errors 跃迁 → 未捕获到新的被吞错误，"
                                  f"本次无法判定疗效")
        if self.calls_frozen_runs >= 3:
            return (INCONCLUSIVE, f"guardStats.calls 连续 {self.calls_frozen_runs} 次"
                                  f"无增长（末值 {self.prev_calls}），"
                                  f"排除 TTL 缓存后仍冻结 → 计数不可信")
        if surv and not self.pid_changes:
            return (PASS, f"errors 涨到 {self.prev_errors}（{len(surv)} 次跃迁），"
                          f"每次跃迁后 {EXIT_WINDOW_SEC:.0f}s 内 PID 均未换号 "
                          f"→ 兜底真的救活了")
        if surv and self.pid_changes:
            return (INCONCLUSIVE, f"{len(surv)} 次 errors 跃迁后存活，但期间发生 "
                                  f"{len(self.pid_changes)} 次 PID 换号"
                                  f"（窗口外，可能另有原因），需人工核对时间线")
        if pend:
            return (INCONCLUSIVE, f"{len(pend)} 次 errors 跃迁的观察窗口未走完"
                                  f"（延长 --duration 重跑）")
        return (INCONCLUSIVE, "样本不足，无法给出确定结论（详见上方时间线）")


def main():
    ap = argparse.ArgumentParser(
        description="guardStats 兜底疗效观测器（只读）——判定 lua_pcall 兜底是否真救活游戏")
    ap.add_argument("--duration", type=float, default=1800.0,
                    help="观测时长（秒），0 表示不限（默认 1800）")
    ap.add_argument("--interval", type=float, default=5.0,
                    help="采样间隔（秒），下限 3s（默认 5）"
                         "——/api/status 有 2s TTL 缓存，≤2s 会拿到过期快照")
    ap.add_argument("--gateway", default="http://127.0.0.1:18082",
                    help="网关地址（默认 http://127.0.0.1:18082）")
    a = ap.parse_args()

    if a.interval < FATAL_MIN_INTERVAL:
        print(f"[WARN] --interval={a.interval}s 低于 TTL 下限，自动抬到 "
              f"{FATAL_MIN_INTERVAL:.0f}s（否则会反复读到过期快照，误判计数冻结）",
              flush=True)
        a.interval = FATAL_MIN_INTERVAL

    v = Watcher(a.gateway, a.interval, a.duration).run()
    return 0 if v == PASS else (1 if v == FAIL else 2)


if __name__ == "__main__":
    sys.exit(main())
