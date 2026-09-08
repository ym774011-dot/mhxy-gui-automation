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
    """读自身实时世界坐标 —— ★零点击（2026-09-07 重写）。

    旧实现要点一次组队图标开面板读 `界面数据[7].队伍数据[1].地图数据`：
      1) 无队伍时该表为空（懒加载）→ 常年 None（"队长当前位置: None"）；
      2) 有队伍时读到的是 **目标xy（上一次走路目标）**，不是当前位置 ——
         实测队长实际 (4440,5480)，该字段返回 (2772,1563)=锚点，走位判据
         与建队投影全部失真（建队总失败的真根因）；
      3) 点图标本身会切旗子/开面板，干扰后续建队。
    改读引擎每帧维护的 `tp.屏幕.主角.xy`，散人/队长/队员均可读，零副作用。
    """
    for _ in range(max(1, tries)):
        pos = ZGUI.self_world_xy(gw)
        if pos is not None:
            return pos
        time.sleep(0.6)
    return None


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

    ★2026-09-08 用户规则定案（时序铁律）：队长必须真正到达 [139,80]
      （±3 格），队员才能开始组队操作——队长没到时队员朝锚点/旧坐标
      投影点身体 = 点空地，反而打乱双方坐标（12:41 实锤：队长卡在传送
      落点 (2640,1660) 三连点纹丝不动，队员按旧锚点坐标点击全部落空）。

    走位每次点击后读真实位置（tp.屏幕.主角.xy 零点击），从真实位置继续
    导航（旧代码盲估计中点，走没走全然不知）；连续 2 次点击位置无变化
    → 重传送重置再走；整轮最多 2 次传送。

    返回：到达后的队长世界坐标（实测确认）；未到达返回 None——调用方
    必须跳过队员归队操作（等下一轮看门狗），绝不让队员朝错误位置点击。
    """
    _log("队长准备: 传送 %s + 走位 [139,80]" % TP_DEST)
    lw = _gw(leader_pid)
    lhwnd = find_hwnd_by_pid(leader_pid)
    pos = None
    for attempt in (1, 2):
        _teleport(leader_pid)
        time.sleep(1.0)
        pos = read_pos_closed(lhwnd, lw)
        _log("队长当前位置: %s（第%d次传送后）" % (pos, attempt))
        if pos is None:
            # 传送落点是统一的 [132,83]（2026-09-06 五开实测），读不到面板时兜底假设
            _log("面板读不到，按传送统一落点 [132,83] 兜底走位")
            pos = ARRIVE_WORLD
        stuck = 0
        for i in range(4):
            dx, dy = CAP_TARGET[0] - pos[0], CAP_TARGET[1] - pos[1]
            if abs(dx) <= 20 and abs(dy) <= 20:
                break
            off = ZGUI._screen_offset_xy(lw)
            if off is None:
                _log("[fail] tp 不可用")
                pos = None
                break
            sx, sy = int(CAP_TARGET[0] + off[0]), int(CAP_TARGET[1] + off[1])
            if not (0 <= sx <= 800 and 0 <= sy <= 600):
                # 目标不在视野：改点视野边缘同方向逼近（走两步相机跟过来目标
                # 自然入视野）。旧代码直接中止 → 队员永远等不到队长就位。
                sx = max(30, min(770, sx))
                sy = max(30, min(570, sy))
                _log("[warn] 目标不在视野，改点视野边缘 (%d,%d) 逼近" % (sx, sy))
            _log("走位点击 (%d,%d)（偏差 %.0f,%.0f）——途中不点组队图标" % (sx, sy, dx, dy))
            ZGUI.post_click(lhwnd, sx, sy, gateway=lw)
            time.sleep(4.0)
            # ★每次点击后读真实位置（不再盲估计中点）
            real = None
            for _ in range(3):
                real = read_pos_closed(lhwnd, lw)
                if real is not None:
                    break
                time.sleep(2.0)
            if real is None:
                pos = (pos[0] + (CAP_TARGET[0] - pos[0]) * 0.5,
                       pos[1] + (CAP_TARGET[1] - pos[1]) * 0.5)  # 读不到退盲估计
                continue
            moved = abs(real[0] - pos[0]) + abs(real[1] - pos[1])
            pos = real
            if moved < 10:
                stuck += 1
                _log("[warn] 第%d次点击后位置未变 (%.0f,%.0f)"
                     % (i + 1, real[0], real[1]))
                if stuck >= 2:
                    _log("[warn] 连续 2 次点击无移动 → 重传送重置走位")
                    break
            else:
                stuck = 0
        if (pos is not None
                and abs(CAP_TARGET[0] - pos[0]) <= 60
                and abs(CAP_TARGET[1] - pos[1]) <= 60):
            _log("队长已就位: %s（目标 %s，±3 格容差）" % (pos, CAP_TARGET))
            return pos
        _log("[warn] 第%d轮走位未到锚点（pos=%s）→ 重传送再来" % (attempt, pos))
    _log("[fail] 队长两轮走位均未到达 [139,80]——本轮禁止队员归队（防打乱坐标）")
    return None


def _team_panel_ensure(lhwnd, lw, want_open, settle=0.9):
    """把组队面板切到 want_open 状态；★一次调用最多点一次图标。

    ★2026-09-07 修正（关键）：主队图标点击语义是"切换"（无队=举旗/收旗），
      若点击后确认不到状态就补点 = 收旗 → 点身体建不了队（用户实测
      "点击2次就取消了旗子"）。因此这里只读一次状态，不符则点一次并等待，
      绝不二次点击；通道不可信（None）时宁可不点。
    """
    v = ZGUI._team_panel_visible(lw)
    if v is None:                      # 通道失败：等一拍重读，读不到就不点
        time.sleep(random.uniform(0.5, 0.8))
        v = ZGUI._team_panel_visible(lw)
        if v is None:
            _log("组队面板状态读不到，跳过本次图标点击（防误触收旗）")
            return False
    if v == want_open:
        return True
    ZGUI._team_click_icon(lhwnd, lw)
    time.sleep(settle)
    nv = ZGUI._team_panel_visible(lw)
    return (nv is None) or (nv == want_open)


def create_team(leader_pid, cap_world, tries=3):
    """队长建队（★2026-09-07 二次重写：换掉失真坐标源 + 每轮清旗）。

    旧版两个致命 bug（实测队长实际 (4440,5480)，旧字段却读成锚点 (2772,1563)）：
      1) 自身坐标读 `p7.队伍数据[1].地图数据` —— 那是 **目标xy**，不是当前位置，
         投影出 (-1268,-3617) 越界后退回固定点 (400,370)，而脚底在 y≈300，
         370 已在脚底**之下** → 点到地面 = 走路指令 → 永远建不了队；
      2) 第 2 轮起再点组队图标 = 把上一轮残留的旗子收掉 → 点身体无意义。
    现流程（每轮）：走回锚点（用实时坐标判定）→ 右键清旗 → 点图标一次
      → 读实时脚底屏幕位 → 点身体 → 读顶栏头像确认（零点击）。
    """
    lw = _gw(leader_pid)
    lhwnd = find_hwnd_by_pid(leader_pid)
    for k in range(max(1, int(tries))):
        if lhwnd is None:
            _log("建队: 窗口不可用，等 3s 重试")
            time.sleep(3.0)
            lhwnd = find_hwnd_by_pid(leader_pid)
            continue
        # 1) 走回锚点 [139,80]（旧版用目标xy判定 → 实际站在别处却以为到位）
        for _ in range(2):
            self_xy = ZGUI.self_world_xy(lw)
            if self_xy is None:
                _log("建队第%d次：读不到自身坐标，等 2s 重试" % (k + 1))
                time.sleep(2.0)
                continue
            if abs(cap_world[0] - self_xy[0]) <= 60 and abs(cap_world[1] - self_xy[1]) <= 60:
                break
            off = ZGUI._screen_offset_xy(lw)
            if off is None:
                break
            ax, ay = int(cap_world[0] + off[0]), int(cap_world[1] + off[1])
            if not (0 <= ax <= 800 and 0 <= ay <= 600):
                _log("建队第%d次 锚点不在视野 (%d,%d)，跳过走回" % (k + 1, ax, ay))
                break
            _log("建队第%d次 偏离锚点(现%s)，点击走回 (%d,%d)" % (k + 1, self_xy, ax, ay))
            ZGUI.post_click(lhwnd, ax + random.randint(-2, 2),
                            ay + random.randint(-2, 2), gateway=lw)
            time.sleep(3.5)
        # 2) 右键清一次鼠标：清掉上轮可能残留的旗子（否则本轮点图标=收旗）
        if k > 0:
            ZGUI.post_right_click(lhwnd, random.randint(390, 430),
                                  random.randint(240, 280), gateway=lw)
            time.sleep(0.8)
        # 3) 点图标一次进入选目标模式（★绝不点第二次）
        ZGUI._team_click_icon(lhwnd, lw)
        # 4) 实时脚底屏幕位 → 身体点（不再用固定 (400,370)）
        sc = ZGUI.self_screen_xy(lw)
        if sc is None or not (0 <= sc[0] <= 800 and 0 <= sc[1] <= 600):
            sc = (400.0, 300.0)          # 相机锁中心兜底（脚底≈屏幕中心）
            _log("建队第%d次 屏幕位读不到，用中心兜底 (400,300)" % (k + 1))
        _log("建队第%d次 脚底屏幕位 (%d,%d) → 身体点上移 %d" % (k + 1, sc[0], sc[1], ZGUI._TEAM_BODY_LIFT))
        ZGUI._team_click_body(lhwnd, lw, int(sc[0]), int(sc[1]))
        # 5) 零点击验证：顶部头像栏（无队=0，建队成功=1）
        time.sleep(1.5)
        st = ZGUI.team_stats_topbar(lw)
        _log("建队第%d次 顶栏stats（应为 1）: %s" % (k + 1, (st,)))
        ok = bool(st) and st[0] >= 1 and bool(st[2])
        if ok:
            # 队伍面板若被打开则关掉（读状态配对，不盲点图标）
            if ZGUI._team_panel_visible(lw):
                ZGUI._team_click_icon(lhwnd, lw)
            return True
        _log("建队第%d次未生效，下一轮右键清旗后重试" % (k + 1))
    return False


def _read_map(gw):
    """读当前地图名（联动归队用）；读不到返回 None。"""
    try:
        return ZGUI._lua_call(gw, r'''local m=tp.地图
__out=tostring(m and m.地图名称 or "")''')
    except Exception:
        return None


def member_tp_and_apply(member_pid, cap_world, tries=4, tp_first=True,
                        leader_pid=None):
    """队员上线/归队：与队长同图 → 靠近队长 → 反复点队长身体申请。

    tp_first=False 跳过传送（GUI 并行流程阶段1 已统一传送）。

    ★2026-09-07 联动修复（队长重登后 4 队员卡"队长不在视野"实锤）：
      归队路径 tp_first=False 假设"阶段1已传送"，但掉线重登场景没人传过
      队员 → 队员留在异图（江南野外），队长坐标（大唐官府）投影越界
      → 空等 3 轮放弃，永远不申请。现在每轮先对账：
        异图（读双方地图名实测）→ 就地传送（散人才能传）；
        同图但队长视野外 → 向队长方向点击走近（夹到窗口内）；
        视野内 → 点队长身体申请。
      leader_pid 提供后地图对账才生效；未提供维持旧行为。
    """
    gw = _gw(member_pid)
    for k in range(max(1, tries)):
        hwnd = find_hwnd_by_pid(member_pid)
        if hwnd is None:
            _log("p%d: 找不到窗口" % member_pid)
            time.sleep(6)
            continue
        # ---- 地图对账（联动核心）----
        if leader_pid:
            my_map = _read_map(gw)
            cap_map = _read_map(_gw(leader_pid))
            if my_map and cap_map and my_map != cap_map:
                _log("p%d: 异图(%s≠队长%s) 就地传送" % (member_pid, my_map, cap_map))
                _teleport(member_pid)
            elif tp_first and k == 0:
                _teleport(member_pid)
            elif not tp_first and k == 0:
                _log("p%d: 已与队长同图(%s)，直接申请" % (member_pid, my_map or "?"))
        elif tp_first and k == 0:
            _teleport(member_pid)
        elif not tp_first and k == 0:
            _log("p%d: 阶段1已传送，直接申请" % member_pid)
        off = ZGUI._screen_offset_xy(gw)
        if off is None or hwnd is None:
            _log("p%d: tp/窗口不可用" % member_pid)
            time.sleep(6)
            continue
        jx, jy = int(cap_world[0] + off[0]), int(cap_world[1] + off[1])
        if not (0 <= jx <= 800 and 0 <= jy <= 600):
            # ★同图但队长在视野外：向其方向点击走近（不再原地空等）
            wx = min(max(jx, 60), 740)
            wy = min(max(jy, 60), 540)
            _log("p%d: 队长不在视野 (%d,%d) → 向其方向走 (%d,%d)"
                 % (member_pid, jx, jy, wx, wy))
            ZGUI.post_click(hwnd, wx, wy, gateway=gw)
            time.sleep(random.uniform(3.0, 4.0))
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
    st = ZGUI.team_stats_topbar(lw)      # ★顶栏实时成员数（面板数据仅作兜底）
    if st is None:
        st = ZGUI._team_stats(_gw(leader_pid))
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
        st = ZGUI.team_stats_topbar(_gw(leader_pid))
        if st is None:
            st = ZGUI._team_stats(_gw(leader_pid))
        mem = st[0] if st else -1
        if mem != last_mem:
            _log("当前成员数: %s（目标 %d）" % (mem, expect_members))
            last_mem = mem
        if mem >= expect_members:
            return mem
        approve_round(leader_pid)
        time.sleep(poll_s)
    st = ZGUI.team_stats_topbar(_gw(leader_pid))
    if st is None:
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
    st = ZGUI.team_stats_topbar(_gw(leader_pid))
    if st is None:
        st = ZGUI._team_stats(_gw(leader_pid))
    _log("批准后 顶栏stats: %s" % (st,))
    if not st or st[0] < expect:
        _log("[fail] 未满 %d 人" % expect)
        return False
    return do_formation(leader_pid)
