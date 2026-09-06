# -*- coding: utf-8 -*-
"""squad_auto_team.py — 登录后一键组队链路（2026-09-06 22:52 实测 5/5 通过）。

顺序铁律：
  1. 全员散人传送 大唐官府（★队伍成员不能传送，必须先传后组）
  2. 队长走到 [139,80]（世界 2780,1600），方便队员点到队长身体
     ★用户规则：走位途中不点组队图标（会开关面板/进旗子模式干扰走路），
     走前可点图标查坐标，到达后再点图标验证。
  3. 建队 → 队员申请 → 循环批准至满员 → 天覆阵

提供两种用法：
  auto_team(leader_pid, member_pids)        一次性全流程（zhuagui_squad 用）
  prep_leader / member_tp_and_apply /
  approve_loop / do_formation               分步调用（PP GUI 用，队员可
                                            异步陆续上线）
"""
import importlib.util
import os
import random
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_HERE, ".."))
_spec = importlib.util.spec_from_file_location(
    "ZGUI", os.path.join(_ROOT, "tasks", "library", "ZGUI.py"))
ZGUI = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ZGUI)
sys.path.insert(0, _HERE)
from member_sell_loop import find_hwnd_by_pid  # noqa: E402

CAP_TARGET = (2780.0, 1600.0)     # 网格 [139,80]
ARRIVE_WORLD = (2640.0, 1660.0)   # 传送统一落点（网格 [132,83]）
TP_DEST = "大唐官府"


def _gw(pid):
    return "file://pzxy_p%d" % pid


def _log(msg):
    print("[autoTeam] %s" % msg, flush=True)


def read_pos_closed(hwnd, gw, tries=3):
    """读自身坐标（每次尝试点图标刷新懒加载），结束保证面板关闭。

    ★开关成对铁律：_read_pos_via_panel 每次调用都点击一次图标（切换），
    尝试 n 次后若 n 为奇数则面板开着，必须补一次关闭——否则走位/任务
    点击全落在面板上（2026-09-07 复盘发现的重试引入 BUG）。
    """
    pos, n = None, 0
    for _ in range(max(1, tries)):
        n += 1
        pos = _read_pos_via_panel(hwnd, gw)
        if pos is not None:
            break
        time.sleep(2.0)
    if n % 2 == 1:
        ZGUI.post_click(hwnd, 570, 583, gateway=gw)   # 补关，成对
        time.sleep(0.8)
    return pos


def _read_pos_via_panel(hwnd, gw, open_already=False):
    """点图标开面板刷新懒加载 → 读 队伍数据[1].地图数据（散人=自己）。

    ★2026-09-07：队伍数据懒加载（重登后尤其慢），开面板后单次读常为空；
      旧逻辑读空即返回 None，外层重试还会把面板点关 → 越试越读不到。
      改为面板开着时轮询读（最多 ~4.3s），空了稍等再读。
    """
    if not open_already:
        ZGUI.post_click(hwnd, 570, 583, gateway=gw)
        time.sleep(1.0)
    code = r"""
if type(tp) ~= 'table' then __out = '' return end
local j = tp.主界面 and tp.主界面.界面数据
local p7 = type(j) == 'table' and j[7]
local td = type(p7) == 'table' and p7.队伍数据
local v = type(td) == 'table' and td[1]
local md = type(v) == 'table' and v.地图数据
if type(md) ~= 'table' then __out = '' return end
__out = tostring(md.x) .. ',' .. tostring(md.y)
"""
    r = ""
    for _ in range(6):
        r = ZGUI._lua_call(gw, code, timeout=10.0) or ""
        if "," in r:
            break
        time.sleep(0.6)
    if "," not in r:
        return None
    x, y = r.split(",", 1)
    try:
        return float(x), float(y)
    except ValueError:
        return None


def _teleport(pid, dest=TP_DEST):
    """散人传送并打印前后状态。"""
    gw = _gw(pid)
    hwnd = find_hwnd_by_pid(pid)
    if not hwnd:
        _log("p%d: 找不到窗口，跳过传送" % pid)
        return False
    ok = ZGUI.zhuagui_teleport(gw, hwnd=hwnd, dest=dest, verbose=True)
    time.sleep(1.0)
    return ok


def prep_leader(leader_pid):
    """队长上线第一步：传送大唐官府 → 走位 [139,80]。

    返回队长世界坐标；失败返回 None。结束时队伍面板为关闭状态。
    """
    _log("队长准备: 传送 %s + 走位 [139,80]" % TP_DEST)
    _teleport(leader_pid)
    lw = _gw(leader_pid)
    lhwnd = find_hwnd_by_pid(leader_pid)
    pos = read_pos_closed(lhwnd, lw)
    _log("队长当前位置: %s" % (pos,))
    if pos is None:
        # 传送落点是统一的 [132,83]（2026-09-06 五开实测），读不到面板时兜底假设
        _log("面板读不到，按传送统一落点 [132,83] 兜底走位")
        pos = ARRIVE_WORLD
    for i in range(4):
        dx, dy = CAP_TARGET[0] - pos[0], CAP_TARGET[1] - pos[1]
        if abs(dx) <= 20 and abs(dy) <= 20:
            break
        off = ZGUI._screen_offset_xy(lw)
        if off is None:
            _log("[fail] tp 不可用")
            return None
        sx, sy = int(CAP_TARGET[0] + off[0]), int(CAP_TARGET[1] + off[1])
        if not (0 <= sx <= 800 and 0 <= sy <= 600):
            _log("[fail] 目标不在队长视野 (%d,%d)，中止" % (sx, sy))
            return None
        _log("走位点击 (%d,%d)（偏差 %.0f,%.0f）——途中不点组队图标" % (sx, sy, dx, dy))
        ZGUI.post_click(lhwnd, sx, sy, gateway=lw)
        time.sleep(4.0)
        pos = (pos[0] + (CAP_TARGET[0] - pos[0]) * 0.5,
               pos[1] + (CAP_TARGET[1] - pos[1]) * 0.5)  # 盲估计，走完再验证
    est = pos
    # ★2026-09-07 到达判定放宽（用户要求：不必精确踩 [139,80]，走离人群即可）：
    #   1) 容差 40 → 60（±3 格），[138,80] 这类差一格不再判失败；
    #   2) 面板读数失败重读 3 次（每次隔 2s），仍读不到按走位盲估计放行——
    #      此前读不到直接 [fail]，人已到位却整场组队卡死。
    for _ in range(3):
        pos = read_pos_closed(lhwnd, lw)
        if pos is not None:
            break
        time.sleep(2.0)
    if pos is None:
        pos = est
        _log("[warn] 到达后面板仍读不到，按走位盲估计放行: %s" % (pos,))
    _log("到达验证: %s（目标 %s，±3 格容差）" % (pos, CAP_TARGET))
    if pos is None or abs(CAP_TARGET[0] - pos[0]) > 60 or abs(CAP_TARGET[1] - pos[1]) > 60:
        _log("[fail] 队长未到达 [139,80] 附近（±3 格）")
        return None
    return pos


def create_team(leader_pid, cap_world):
    """队长建队。成功返回 True（面板已关闭）。"""
    lw = _gw(leader_pid)
    lhwnd = find_hwnd_by_pid(leader_pid)
    coff = ZGUI._screen_offset_xy(lw)
    sx, sy = int(cap_world[0] + coff[0]), int(cap_world[1] + coff[1])
    ZGUI._team_click_icon(lhwnd, lw)
    time.sleep(0.6)
    ZGUI._team_click_body(lhwnd, lw, sx, sy)
    time.sleep(1.0)
    ZGUI._team_click_icon(lhwnd, lw)   # 开面板刷新+验证
    time.sleep(1.2)
    st = ZGUI._team_stats(lw)
    _log("建队后 stats（应为 1）: %s" % (st,))
    # 关面板（后续批准/阵法流程各自决定面板状态）
    ZGUI.post_click(lhwnd, 570, 583, gateway=lw)
    time.sleep(0.8)
    return bool(st) and st[0] >= 1 and bool(st[2])


def member_tp_and_apply(member_pid, cap_world, tries=4, tp_first=True):
    """队员上线：传送大唐官府 → 反复向队长身体申请（队长可能尚未就绪）。

    tp_first=False 跳过传送（GUI 并行流程阶段1 已统一传送）。
    """
    if tp_first:
        _teleport(member_pid)
    else:
        _log("p%d: 阶段1已传送，直接申请" % member_pid)
    gw = _gw(member_pid)
    for k in range(max(1, tries)):
        hwnd = find_hwnd_by_pid(member_pid)
        off = ZGUI._screen_offset_xy(gw)
        if off is None or hwnd is None:
            _log("p%d: tp/窗口不可用" % member_pid)
            time.sleep(6)
            continue
        jx, jy = int(cap_world[0] + off[0]), int(cap_world[1] + off[1])
        if not (0 <= jx <= 800 and 0 <= jy <= 600):
            _log("p%d: 队长不在视野 (%d,%d)" % (member_pid, jx, jy))
            time.sleep(6)
            continue
        ZGUI._team_click_icon(hwnd, gw)
        time.sleep(0.6)
        ZGUI._team_click_body(hwnd, gw, jx, jy)
        _log("p%d: 已点队长身体 (%d,%d)（第%d次申请）" % (member_pid, jx, jy, k + 1))
        time.sleep(random.uniform(6, 9))
    _log("p%d: 申请轮次结束（是否入队由队长批准裁决）" % member_pid)


def approve_open_panel(leader_pid):
    """批准流程第一步：点图标打开队伍面板（面板全程保持开）。"""
    lw = _gw(leader_pid)
    lhwnd = find_hwnd_by_pid(leader_pid)
    ZGUI._team_click_icon(lhwnd, lw)
    time.sleep(1.2)


def approve_round(leader_pid):
    """单轮批准：请求列表 → 点首卡(162,166) → 允许。需先 approve_open_panel。"""
    lw = _gw(leader_pid)
    lhwnd = find_hwnd_by_pid(leader_pid)
    ZGUI.post_click(lhwnd, random.randint(460, 509),
                    random.randint(140, 152), gateway=lw)
    time.sleep(random.uniform(0.9, 1.2))
    st = ZGUI._team_stats(lw)
    mem = st[0] if st else -1
    if mem >= 1:
        ZGUI.post_click(lhwnd, 162 + random.randint(-2, 2),
                        166 + random.randint(-2, 2), gateway=lw)
        time.sleep(random.uniform(0.5, 0.8))
        ZGUI.post_click(lhwnd, random.randint(514, 541),
                        random.randint(370, 378), gateway=lw)
        time.sleep(random.uniform(1.5, 2.2))
    return mem


def approve_loop(leader_pid, expect_members, timeout_s=1800.0, poll_s=6.0):
    """队长循环批准申请直到满员/超时。返回最终成员数。

    流程与 22:20 实测一致：点图标开面板一次 → 循环 请求列表→首卡(162,166)→
    允许（允许后申请列表自动关，重开请求列表即可）。面板全程保持打开。
    """
    approve_open_panel(leader_pid)
    t0 = time.time()
    last_mem = -1
    while time.time() - t0 < timeout_s:
        st = ZGUI._team_stats(_gw(leader_pid))
        mem = st[0] if st else -1
        if mem != last_mem:
            _log("当前成员数: %s（目标 %d）" % (mem, expect_members))
            last_mem = mem
        if mem >= expect_members:
            return mem
        approve_round(leader_pid)
        time.sleep(poll_s)
    st = ZGUI._team_stats(_gw(leader_pid))
    return st[0] if st else -1


def do_formation(leader_pid, name="天覆阵"):
    """选阵并验证。返回 True=阵法生效。"""
    lw = _gw(leader_pid)
    lhwnd = find_hwnd_by_pid(leader_pid)
    ZGUI.zhuagui_team_formation(lw, hwnd=lhwnd, verbose=True)
    time.sleep(1.0)
    r = ZGUI._lua_call(lw, r"""
if type(tp) ~= 'table' then __out = 'noTP' return end
local p7 = tp.主界面 and tp.主界面.界面数据 and tp.主界面.界面数据[7]
__out = tostring(p7 and p7.当前阵法) .. '/' .. tostring(p7 and p7.当前阵型)
""", timeout=10.0) or ""
    _log("阵法验证: %s" % r)
    return name in r


def auto_team(leader_pid, member_pids, expect_members=None, dest=TP_DEST):
    """一次性全流程（所有号都已登录时）。返回 True=满员+阵法完成。"""
    pids = [leader_pid] + list(member_pids)
    expect = expect_members or len(pids)
    _log("阶段1: 全员传送 %s（散人）" % dest)
    for pid in pids:
        _teleport(pid)
    cap_world = prep_leader(leader_pid)
    if cap_world is None:
        return False
    if not create_team(leader_pid, cap_world):
        _log("[fail] 建队失败")
        return False
    _log("阶段4: 队员申请")
    for pid in member_pids:
        member_tp_and_apply(pid, cap_world, tries=1)
        time.sleep(2.0)
    mem = approve_loop(leader_pid, expect, timeout_s=300.0)
    st = ZGUI._team_stats(_gw(leader_pid))
    _log("批准后 stats: %s" % (st,))
    if not st or st[0] < expect:
        _log("[fail] 未满 %d 人" % expect)
        return False
    return do_formation(leader_pid)
