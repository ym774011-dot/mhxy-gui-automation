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
          第一个登录的拉起 run_unlimited_test.py（完整跑批），其后每个
          拉起 member_sell_loop.py（纯出售）。全部就位后退出。

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
LOGGED_IN_RE = re.compile(r"\[\d{4,}\]")
ROLE_RE = re.compile(r"\(([^()\[\]]+)\[\d+\]\)")


def enum_game_windows():
    """返回 [(pid, hwnd, title)]：Galaxy2DEngine 顶层+子窗口，同进程取标题最长者。"""
    import win32gui
    seen = {}

    def add(h):
        try:
            if not win32gui.IsWindowVisible(h):
                return
            pid = win32gui.GetWindowThreadProcessId(h)[1]
            if not pid:
                return
            if win32gui.GetClassName(h) != "Galaxy2DEngine":
                return
            title = win32gui.GetWindowText(h)
            cur = seen.get(pid)
            if cur is None or len(title) > len(cur[2]):
                seen[pid] = (pid, h, title)
        except Exception:
            pass

    def cb_top(h, _):
        add(h)
        try:
            win32gui.EnumChildWindows(h, lambda c, _x: (add(c), True)[1], None)
        except Exception:
            pass
        return True

    win32gui.EnumWindows(cb_top, None)
    return list(seen.values())


def plant(pid, name, port):
    """登录界面播种：复用 pzxy_plant（--pid 定点 + --name 通道隔离）。"""
    print("[播种] PID=%d name=%s port=%d ..." % (pid, name, port))
    r = subprocess.run(
        [PYEXE, os.path.join(GATEWAY_DIR, "tools", "pzxy_plant.py"),
         "--pid", str(pid), "--name", name, "--port", str(port)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=180)
    tail = (r.stdout or "").strip().splitlines()[-3:]
    for line in tail:
        print("   | " + line)
    return r.returncode == 0


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
            if plant(pid, name, ports[i % len(ports)]):
                squad.append((pid, name))
            else:
                print("[失败] PID=%d 播种失败，跳过" % pid)
        else:
            skip.append((pid, title))
            print("[跳过] PID=%d 已登录但无 worker（无法中途播种）: %r" % (pid, title))
    if not squad:
        print("[X] 没有可用实例。请把窗口重开到登录界面再运行。")
        return 1

    # ---- Phase B：观察登录顺序 ----
    print("=" * 60)
    print("[Phase B] 请依次登录 %d 个号 —— 第一个登录的自动成为队长。" % len(squad))
    print("          （队长=完整抓鬼跑批；其余=纯出售循环。Ctrl+C 中止）")
    assigned = {}
    # 重启续用：上一次的队长映射仍然有效时直接沿用（窗口重启 PID 变化则失效）
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            prev = json.load(f)
        for pid_s, info in (prev.get("assigned") or {}).items():
            pid = int(pid_s)
            if any(pid == p for p, _ in squad) and LOGGED_IN_RE.search(info.get("title", "")):
                assigned[pid] = info
                print("[续用] PID=%d 保持上次角色: 队长=%s" % (pid, info.get("leader")))
    except Exception:
        pass

    t0 = time.time()
    spawned = []
    while len(assigned) < len(squad) and time.time() - t0 < args.wait_login:
        time.sleep(3)
        for pid, hwnd, title in enum_game_windows():
            if pid in assigned or not any(pid == p for p, _ in squad):
                continue
            m = LOGGED_IN_RE.search(title)
            if not m:
                continue
            rm = ROLE_RE.search(title)
            role = rm.group(1).strip() if rm else ("p%d" % pid)
            is_leader = not any(a.get("leader") for a in assigned.values())
            assigned[pid] = {"role": role, "leader": is_leader, "title": title}
            gw = "file://pzxy_p%d" % pid
            try:
                if is_leader:
                    cmd = [PYEXE, os.path.join(ROOT, "run_unlimited_test.py"),
                           "--gateway", gw, "--role", role,
                           "--timeout", "20", "--wait-dialog", "1.2"]
                    tag = "队长·完整跑批"
                else:
                    cmd = [PYEXE, os.path.join(HERE, "member_sell_loop.py"),
                           "--pid", str(pid), "--gateway", gw]
                    tag = "队员·纯出售"
                import subprocess as _sp
                CREATE_NO_WINDOW = 0x08000000
                _sp.Popen(cmd, cwd=ROOT, creationflags=CREATE_NO_WINDOW,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                spawned.append((pid, tag, role))
                print("[就位] PID=%d %s 角色=%s gw=%s" % (pid, tag, role, gw))
                try:
                    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
                    with open(STATE_PATH, "w", encoding="utf-8") as f:
                        json.dump({"assigned": {str(k): v for k, v in assigned.items()},
                                   "ts": time.time()}, f, ensure_ascii=False, indent=1)
                except OSError:
                    pass
            except Exception as e:
                print("[失败] PID=%d 启动失败: %s" % (pid, e))

    print("=" * 60)
    print("[完成] 就位 %d/%d" % (len(spawned), len(squad)))
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
