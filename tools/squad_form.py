# -*- coding: utf-8 -*-
"""squad_form.py — 五开自动组队编排器（2026-09-06 用户标定全流程）。

用法：
    E:/py/python.exe tools/squad_form.py --leader 18908 --members 7732,3916,11568,18736

流程：
    1. 角色识别：窗口标题 `胖子西游-(角色名(ID))...`
    2. 队长：点主队图标(570,583) → 点自己身体 → 创建队伍
    3. 读队长世界坐标（队伍数据[1].地图数据）
    4. 各队员：点图标 → 点队长身体 → 发入队申请（队长端申请列表核对）
    5. 队长：循环 图标→请求列表→点首卡→允许，直到 5 人齐
    6. 汇报最终成员表

前置：5 实例 worker 活着（file://pzxy_p<pid> 通道）、tp 可用（被服务器
事件抹除时整链路同死，需重登+重播 worker）。
"""
import argparse
import ctypes
import ctypes.wintypes
import importlib.util
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
spec = importlib.util.spec_from_file_location(
    "ZGUI", os.path.join(ROOT, "tasks", "library", "ZGUI.py"))
ZGUI = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ZGUI)
sys.path.insert(0, HERE)
from member_sell_loop import find_hwnd_by_pid  # noqa: E402

_TITLE_RE = re.compile(r"胖子西游-\s*\((.+?)[\[\(](\d+)[\]\)]\)")


def role_of(pid):
    """从窗口标题读角色名：`胖子西游-(二号美人(412646))...` → (名, id)。"""
    hwnd = find_hwnd_by_pid(pid)
    if not hwnd:
        return None, None
    n = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    ctypes.windll.user32.GetWindowTextW(hwnd, buf, n + 1)
    m = _TITLE_RE.search(buf.value)
    if not m:
        return None, None
    return m.group(1), m.group(2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--leader", type=int, required=True)
    ap.add_argument("--members", required=True, help="逗号分隔的队员 PID")
    ap.add_argument("--apply-wait", type=float, default=4.0,
                    help="每名队员申请后等待(s)")
    args = ap.parse_args()

    pids = [int(x) for x in args.members.split(",") if x.strip()]
    lname, lid = role_of(args.leader)
    print("== 自动组队开始：队长 p%d=%s(%s)，队员 PID=%s =="
          % (args.leader, lname, lid, pids), flush=True)

    lgw = "file://pzxy_p%d" % args.leader
    lhwnd = find_hwnd_by_pid(args.leader)

    # 0) 前置检查
    st = ZGUI._team_stats(lgw)
    if st is None:
        print("[fail] 队长端队伍面板不可读（tp 缺失/worker 死），中止", flush=True)
        return 1
    if st[0] >= 2:
        print("[skip] 已存在队伍（成员=%d 队长=%s），如需重组请先解散" % (st[0], st[2]),
              flush=True)
        return 0

    # 1) 队长建队
    if not ZGUI.zhuagui_team_create(lgw, hwnd=lhwnd, verbose=True):
        print("[fail] 队长建队失败（点自己身体 3 次未生效）", flush=True)
        return 1

    # 2) 队长世界坐标
    lxy = ZGUI._team_self_world_xy(lgw)
    print("队长世界坐标: %s" % (lxy,), flush=True)
    if lxy is None:
        print("[fail] 读不到队长世界坐标", flush=True)
        return 1

    # 3) 队员依次申请
    # ★2026-09-06 22:18 实测：p7.申请列表 计数恒读 0，无法在队长端核对
    # "申请已入列"——改为固定等待，由阶段 4 的批准循环做最终裁决。
    for pid in pids:
        name, rid = role_of(pid)
        gw = "file://pzxy_p%d" % pid
        hwnd = find_hwnd_by_pid(pid)
        ok = ZGUI.zhuagui_team_join(gw, hwnd=hwnd, verbose=True,
                                    leader_world_xy=lxy)
        print("队员 p%d=%s(%s): 已点队长身体（申请是否生效由批准阶段裁决）"
              % (pid, name, rid), flush=True)
        time.sleep(args.apply_wait)

    # 4) 队长批准全部
    final = ZGUI.zhuagui_team_approve_all(lgw, hwnd=lhwnd, verbose=True,
                                          expect_members=1 + len(pids))
    st = ZGUI._team_stats(lgw)
    print("== 组队结束：成员=%s；面板=%s ==" % (final, st), flush=True)
    return 0 if final == 1 + len(pids) else 1


if __name__ == "__main__":
    sys.exit(main())
