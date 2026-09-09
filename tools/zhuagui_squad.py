# -*- coding: utf-8 -*-
"""zhuagui_squad.py — 5 开小队编排器（2026-09-06）。

角色定义（用户拍板）：
  第一个登录的窗口 = 队长 → 完整抓鬼跑批（接任务/天眼/打鬼/顺手打稀有/出售）
  之后登录的窗口   = 队员 → 只跑"自动出售"循环（在队伍里跟着队长即可）

流程：
  Phase A 播种：枚举全部 Galaxy2DEngine 实例；登录界面([0])的逐个播种
          worker（--name p<pid>，文件通道互不干扰）；已登录且 worker 活着
          的直接可用（捕获穿登录存活）；已登录但无 worker 的无法补救 → 跳过。
  Phase B 观察登录：轮询标题，出现 [4位以上数字ID] 即视为该窗口已登录；
          用户【按任意键】后自动跑组队链路（squad_auto_team：散人传送大唐
          官府 → 队长走位[139,80] → 建队/申请/批准 → 天覆阵），组完才拉起
          任务（第一个登录的 run_unlimited_test.py 完整跑批，其余
          member_sell_loop.py 纯出售）。

用法（5 个窗口全部停在登录界面后执行）:
    E:/py/python.exe tools/zhuagui_squad.py
    E:/py/python.exe tools/zhuagui_squad.py --stop     # 停掉小队全部进程
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
GATEWAY_DIR = r"E:\DS\mhxy-mcp-gateway"
PYEXE = sys.executable
STATE_PATH = os.path.join(ROOT, "test_data", "squad_state.json")
TMP_DIR = r"E:\DS\tmp"          # pzxy IPC 文件目录（与 pzxy_ipc 默认一致）
LOGGED_IN_RE = re.compile(r"\[\d{4,}\]")
ROLE_RE = re.compile(r"\(([^()\[\]]+)\[\d+\]\)")


def enum_game_windows():
    """返回 [(pid, hwnd, title)]：Galaxy2DEngine 顶层+子窗口，同进程取标题最长者。

    ★ctypes 实现（win32gui 没有 GetWindowThreadProcessId，曾致静默枚举 0 个）。
    兼容两种形态：单独打开的顶层引擎窗口 + 多开器 SetParent 嵌入的子窗口
    （父 WTWindow 属多开器进程，子 Galaxy2DEngine 属游戏进程）。
    """
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    seen = {}

    def add(h):
        try:
            if not user32.IsWindowVisible(h):
                return
            pidv = wintypes.DWORD()
            user32.GetWindowThreadProcessId(h, ctypes.byref(pidv))
            pid = pidv.value
            if not pid:
                return
            cls = ctypes.create_unicode_buffer(64)
            user32.GetClassNameW(h, cls, 64)
            if cls.value != "Galaxy2DEngine":
                return
            n = user32.GetWindowTextLengthW(h)
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(h, buf, n + 1)
            title = buf.value
            cur = seen.get(pid)
            if cur is None or len(title) > len(cur[2]):
                seen[pid] = (pid, h, title)
        except Exception:
            pass

    ENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    def cb_top(h, _lp):
        add(h)
        try:
            user32.EnumChildWindows(h, ENUMPROC(_child), 0)
        except Exception:
            pass
        return True

    def _child(h, _lp):
        add(h)
        return True

    user32.EnumWindows(ENUMPROC(cb_top), 0)
    return list(seen.values())


def clean_pid_ipc(pid):
    """★残留自洁：播种前清掉该 PID 的旧 IPC 三件套。

    Windows PID 复用窗口：新游戏进程可能拿到死进程的旧 PID，残留的
    hb/out 文件会让 PzxyWorker 在首个真实心跳/响应前读到陈旧数据。
    播种即覆盖 + 先清残留 = 双保险。文件不存在/被占用静默忽略。
    """
    import glob
    for f in glob.glob(os.path.join(TMP_DIR, "pzxy_p%d_*" % pid)):
        try:
            os.remove(f)
        except OSError:
            pass


def plant(pid, name, port):
    """登录界面播种：复用 pzxy_plant（--pid 定点 + --name 通道隔离）。

    返回 (ok:bool, reason:str)——reason=pzxy_plant 输出末尾几行（失败原因）。
    ★2026-09-07：此前失败只 print 到控制台（GUI 为 pythonw 时直接丢失），
    播种偶发失败在日志里查不到任何原因，无法排查。
    """
    print("[播种] PID=%d name=%s port=%d ..." % (pid, name, port))
    clean_pid_ipc(pid)          # ★播种前清旧 IPC（防 PID 复用读陈旧通道）
    try:
        r = subprocess.run(
            [PYEXE, os.path.join(GATEWAY_DIR, "tools", "pzxy_plant.py"),
             "--pid", str(pid), "--name", name, "--port", str(port)],
            capture_output=True, text=True, encoding="gbk", errors="replace",
            timeout=180)
    except subprocess.TimeoutExpired:
        return False, "pzxy_plant 180s 超时"
    tail = (r.stdout or "").strip().splitlines()[-3:]
    for line in tail:
        print("   | " + line)
    reason = " | ".join(x.strip() for x in tail) or ("returncode=%d" % r.returncode)
    return r.returncode == 0, reason


def running_squad_cmdlines_ex():
    """(可信, 命令行列表)。★2026-09-07：

    - 可信=True 且列表为空 → PowerShell 查询成功，确实没有任务进程在跑；
    - 可信=False → 查询异常/返回码非 0，结果不可信（此时不能当"没在跑"）。
    区分两者：00:59 停止全部任务后扫描空是正常的，不能据此拒拉
    （01:21 实证：防重守卫误判，五个实例全部跳过拉起）。
    """
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
          "Where-Object { $_.CommandLine -match 'run_unlimited_test|member_sell_loop' } | "
          "ForEach-Object { $_.CommandLine }")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-c", ps],
                           capture_output=True, text=True,
                           encoding="gbk", errors="replace", timeout=30)
        if r.returncode != 0:
            return False, []
        return True, [l.strip() for l in (r.stdout or "").splitlines() if l.strip()]
    except Exception:
        return False, []


def running_squad_cmdlines():
    """当前在跑的小队相关 python 进程命令行列表（PowerShell CIM 查询）。"""
    _ok, lst = running_squad_cmdlines_ex()
    return lst


def process_alive_for(cmdlines, pid, leader):
    """该实例的跑批/出售进程是否真的在跑（续用前必查，防 state 残留守活）。"""
    token = "pzxy_p%d" % pid
    key = "run_unlimited_test" if leader else "member_sell_loop"
    return any(key in cl and token in cl for cl in cmdlines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stop", action="store_true", help="停掉小队全部进程")
    ap.add_argument("--ports", default="18091,18092,18093,18094,18095",
                    help="播种用临时网关端口池（逗号分隔，避开 18082/18083 常驻）")
    ap.add_argument("--wait-login", type=float, default=1800.0,
                    help="观察登录的最长秒数（默认 30 分钟）")
    args = ap.parse_args()

    if args.stop:
        ps = ("Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match "
              "'zhuagui_squad|member_sell_loop|run_unlimited_test' -and "
              "$_.ProcessId -ne %d } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; "
              "Write-Output $_.ProcessId }" % os.getpid())
        r = subprocess.run(["powershell", "-NoProfile", "-c", ps],
                           capture_output=True, text=True)
        killed = [x for x in (r.stdout or "").split() if x.isdigit()]
        print("[stop] 已停止 %d 个进程: %s" % (len(killed), ",".join(killed) or "无"))
        return 0

    ports = [int(p) for p in args.ports.split(",")]

    # ---- Phase A：播种 ----
    wins = enum_game_windows()
    if not wins:
        print("[X] 未找到任何 Galaxy2DEngine 游戏实例（先开多开器）")
        return 1
    print("[Phase A] 发现 %d 个游戏实例" % len(wins))
    squad = []  # [(pid, name)]
    skip = []
    for i, (pid, hwnd, title) in enumerate(wins):
        name = "p%d" % pid
        sys.path.insert(0, ROOT)
        from library.pzxy_ipc import PzxyWorker
        if PzxyWorker(name=name).is_alive():
            print("[可用] PID=%d title=%r（worker 已活着）" % (pid, title))
            squad.append((pid, name))
            continue
        if "([0])" in title:
            ok_p, why = plant(pid, name, ports[i % len(ports)])
            if ok_p:
                squad.append((pid, name))
            else:
                print("[失败] PID=%d 播种失败：%s" % (pid, why))
        else:
            skip.append((pid, title))
            print("[跳过] PID=%d 已登录但无 worker（无法中途播种）: %r" % (pid, title))
    if not squad:
        print("[X] 没有可用实例。请把窗口重开到登录界面再运行。")
        return 1

    # ---- Phase B：观察登录 → 用户组队 → 按任意键才拉起任务 ----
    print("=" * 60)
    print("[Phase B] 请依次登录 %d 个号并在游戏里组好队伍。" % len(squad))
    print("          第一个登录的=队长（完整跑批）；其余=队员（纯出售）。")
    print("          组好队后【按任意键】启动任务。Ctrl+C 中止。")
    assigned = {}
    # ★2026-09-06 修复：续用前必须验证对应进程真的活着。此前只看 state 残留
    #   —— bat"停"过一次后再跑，续用把全部窗口标记已分配却一个进程都不拉起。
    live_cmdlines = running_squad_cmdlines()
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            prev = json.load(f)
        for pid_s, info in (prev.get("assigned") or {}).items():
            pid = int(pid_s)
            if not any(pid == p for p, _ in squad):
                continue
            if not process_alive_for(live_cmdlines, pid, bool(info.get("leader"))):
                print("[失效] PID=%d state 有分配但进程不在跑 → 将重新拉起" % pid)
                continue
            assigned[pid] = info
            print("[续用] PID=%d 保持上次角色: 队长=%s（进程在跑）"
                  % (pid, info.get("leader")))
    except Exception:
        pass

    # 登录观察 + 等按键（msvcrt 轮询，任意键触发；期间每 5s 刷新状态行）
    import msvcrt
    import time as _t
    login_order = []  # [pid,...] 按首次登录先后
    t0 = _t.time()
    last_status = ""
    print("-" * 60)
    while _t.time() - t0 < float(args.wait_login):
        if msvcrt.kbhit():
            msvcrt.getwch()  # 任意键 → 启动
            print()
            break
        logged_now = []
        for pid, hwnd, title in enum_game_windows():
            if not any(pid == p for p, _ in squad):
                continue
            if LOGGED_IN_RE.search(title) and pid not in login_order:
                login_order.append(pid)
            if LOGGED_IN_RE.search(title):
                logged_now.append(pid)
        status = ("已登录 %d/%d: %s" % (
            len(logged_now), len(squad),
            ",".join(str(p) for p in logged_now)))
        if status != last_status:
            print("  [观察] " + status)
            last_status = status
        _t.sleep(2)
    else:
        print("\n[超时] 等待登录超时，按当前状态继续。")

    # 分配：续用优先；其余按登录顺序补齐（第一个未分配的登录窗口=队长）
    leader_taken = any(a.get("leader") for a in assigned.values())
    for pid in login_order:
        if pid in assigned:
            continue
        title = next((t for p, _h, t in enum_game_windows() if p == pid), "")
        rm = ROLE_RE.search(title or "")
        role = rm.group(1).strip() if rm else ("p%d" % pid)
        is_leader = not leader_taken
        leader_taken = True
        assigned[pid] = {"role": role, "leader": is_leader, "title": title}
        print("[分配] PID=%d %s 角色=%s" % (pid, "队长" if is_leader else "队员", role))
    if not assigned:
        print("[X] 没有任何已登录窗口，无法启动。")
        return 1

    # 分配预览 + 拉起（已在跑的跳过）
    live_cmdlines = running_squad_cmdlines()
    to_spawn = []
    print("=" * 60)
    for pid, info in sorted(assigned.items()):
        alive = process_alive_for(live_cmdlines, pid, bool(info.get("leader")))
        mark = "已在跑，跳过" if alive else ("队长·完整跑批" if info.get("leader") else "队员·纯出售")
        print("  PID=%-6d 角色=%-10s %s" % (pid, info.get("role", "?"), mark))
        if not alive:
            to_spawn.append((pid, info))
    if not to_spawn:
        print("[完成] 全部进程都在跑，无需启动。")
        return 0

    # ---- 自动组队（2026-09-06 新增：按键后第一时间跑，组完才拉起任务）----
    # 顺序铁律：散人先传送大唐官府 → 队长走到[139,80] → 建队/申请/批准 → 天覆阵。
    # ★队员在队伍里不能传送，必须先传后组。
    leader_pid = next((pid for pid, info in to_spawn if info.get("leader")), None)
    member_pids = [pid for pid, info in to_spawn if not info.get("leader")]
    team_ok = False
    if leader_pid and member_pids:
        print("=" * 60)
        print("[autoTeam] 开始自动组队：队长=%d 队员=%s" % (leader_pid, member_pids))
        try:
            from squad_auto_team import auto_team
            team_ok = auto_team(leader_pid, member_pids)
        except Exception as e:
            print("[autoTeam] 异常: %s" % e)
            team_ok = False
        if team_ok:
            print("[autoTeam] 组队+天覆阵完成 ✓")
        else:
            print("[autoTeam] 组队未完成。回车=继续拉起任务（无队模式），Ctrl+C=中止")
            try:
                input()
            except (KeyboardInterrupt, EOFError):
                return 1
    elif leader_pid is None:
        print("[autoTeam] 无队长可分配，跳过自动组队")

    spawned = []
    for pid, info in to_spawn:
        gw = "file://pzxy_p%d" % pid
        role = info.get("role") or ("p%d" % pid)
        try:
            if info.get("leader"):
                cmd = [PYEXE, os.path.join(ROOT, "run_unlimited_test.py"),
                       "--gateway", gw, "--role", role,
                       "--timeout", "20", "--wait-dialog", "1.2"]
                tag = "队长·完整跑批"
            else:
                cmd = [PYEXE, os.path.join(HERE, "member_sell_loop.py"),
                       "--pid", str(pid), "--gateway", gw]
                tag = "队员·纯出售"
            CREATE_NO_WINDOW = 0x08000000
            subprocess.Popen(cmd, cwd=ROOT, creationflags=CREATE_NO_WINDOW,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            spawned.append((pid, tag, role))
            print("[启动] PID=%d %s 角色=%s gw=%s" % (pid, tag, role, gw))
        except Exception as e:
            print("[失败] PID=%d 启动失败: %s" % (pid, e))
    try:
        os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump({"assigned": {str(k): v for k, v in assigned.items()},
                       "ts": time.time()}, f, ensure_ascii=False, indent=1)
    except OSError:
        pass

    print("=" * 60)
    print("[完成] 本次拉起 %d 个进程" % len(spawned))
    for pid, tag, role in spawned:
        print("  PID=%-6d %s  角色=%s" % (pid, tag, role))
    if skip:
        print("  跳过: %s" % (["%d:%s" % (p, t) for p, t in skip],))
    print("jsonl/test_data 落盘；再次运行 bat 或 --stop 可全部停止。")
    return 0


if __name__ == "__main__":
    _rc = 0
    try:
        _rc = main()
    except KeyboardInterrupt:
        print("\n[stop] 已手动中止。")
        _rc = 130
    except Exception:
        import traceback
        traceback.print_exc()
        _rc = 1
    finally:
        # 编排器由桌面 bat 以独立控制台拉起：任何退出（含报错）都停住，
        # 否则窗口一闪即关，用户看不到"未找到游戏实例"之类的失败原因。
        try:
            input("\n---- 按回车关闭窗口 ----")
        except Exception:
            pass
    sys.exit(_rc)
