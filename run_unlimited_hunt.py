# -*- coding: utf-8 -*-
"""全地图刷怪（2026-09-14 用户定案；PP GUI 方案"全地图刷怪"队长脚本）。

主功能：按周游顺序遍历 12 张图（飞行符 5 + 快捷传送 6 + 女儿村 1），
找顺手打白名单怪（知了王/星宿/远古/地煞星/天罡星）逐只打死。
  ・5 张图用 飞行符（固定坐标范围，用户标定）：长寿村/西凉女国/宝象国/
    朱紫国/建邺城 —— 飞行符在背包，右键打开大地图点目标区。
    （★2026-09-15 长安城/傲来国无怪可刷，已移除）
  ・6 张图用 快捷传送（大唐国境/东海湾/长寿郊外/江南野外/子母河/蓬莱仙岛）：对话框由
    「组队完成」阶段开一次后**一直开着**，每周目只点传送目标行
    （按标定像素落点点击，读落地地图名校验）。
副功能（与抓鬼方案一致）：
  ・背包无飞行符 → 商城自动购买（ZGUI._mall_buy_item）。
  ・背包占用到阈值 → 自动出售垃圾装备（zhuagui_sell_junk）。
  ・背包满→存仓库/重新组队 由 PP GUI 全队存仓流程负责（本脚本不管）。
用法：
  E:/py/python.exe run_unlimited_hunt.py --gateway file://pzxy_p<pid> --role 二号美人
"""
from __future__ import annotations

import argparse
import logging
import os
import random
import signal
import sys
import threading
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from tasks.library import ZGUI                      # noqa: E402

_LOG = logging.getLogger("mhxy")

# ---- 飞行符 5 图（用户 2026-09-14 标定，客户区矩形 x0,y0,x1,y1）----
# ★2026-09-15 用户定案：长安城、傲来国两图无怪可刷，
#   已从飞行符周游序列中移除（不再去这两图找怪）。
FLY_MAPS = [
    ("长寿村",   (315, 137, 331, 153)),
    ("西凉女国", (313, 194, 323, 207)),
    ("宝象国",   (300, 274, 318, 291)),
    ("朱紫国",   (367, 342, 376, 360)),
    ("建邺城",   (542, 303, 560, 322)),
]

# ---- 快捷传送 6 图（★2026-09-15 用户实机标定真实包围盒，x0,y0,x1,y1）----
# 真实包围盒（客户区相对坐标）：
#   大唐国境 127,324,167,332 宽高(40,8)
#   东海湾   328,323,364,332 宽高(36,9)
#   子母河   234,351,264,363 宽高(30,12)
#   蓬莱仙岛 343,355,389,363 宽高(46,8)
#   江南野外 191,325,234,333 宽高(43,8)
#   长寿郊外 322,292,368,303 宽高(46,11)
# ★2026-09-15 修正：原按「像素X=75+段中心」推算的坐标会点偏，
#   已改用用户实机读到的真实链接包围盒。
QUICK_MAPS = ("大唐国境", "东海湾", "长寿郊外", "江南野外",
              "子母河", "蓬莱仙岛")
QUICK_MAP_RECTS = {
    "大唐国境":   (127, 324, 167, 332),   # 宽高 40x8
    "东海湾":     (328, 323, 364, 332),   # 宽高 36x9
    "子母河":     (234, 351, 264, 363),   # 宽高 30x12
    "蓬莱仙岛":   (343, 355, 389, 363),   # 宽高 46x8
    "江南野外":   (191, 325, 234, 333),   # 宽高 43x8
    "长寿郊外":   (322, 292, 368, 303),   # 宽高 46x11
}


# ---- 快捷传送对话框开关/入口（仅作标定记录，脚本不再点）----
# ★2026-09-15 用户定案：快捷传送使用期间**不再点开关/按钮**，
#   对话框由组队阶段开一次后一直开着（除游戏重启）。
#   以下两个常量仅保留作为标定记录，代码不再引用。
_MENU_TOGGLE = (150, 9, 170, 42)        # 快捷菜单开关（仅记录）
_TP_BTN = (269, 45, 322, 58)           # 快捷传送按钮（仅记录）
_QUICK_TARGET_X = (110, 230)           # 快捷传送选项行 X 命中带（对话框文字区）

# ★2026-09-17 用户定案：快捷传送开关是否需要在运行中补点。
#   常规流程（组队阶段已把 [8] 对话框开好）→ False，运行中**不再点开关**；
#   仅当「掉线重新登录后跳过组队」（--skip-team）→ True，才允许点开关重开。
_SKIP_TEAM = False

_SELL_MIN_BAG = 12                     # 背包占用≥该格数才出售
# ★2026-09-17 用户定案：全地图刷怪追加出售白名单（仅本脚本启用，不污染抓鬼）。
#   百炼精铁/制造指南书/钨金 等 打造/功能 材料不在 武器/防具 判据内，
#   需显式白名单才出售；背包里有即由出售流程自动卖。
_SELL_EXTRA = ("百炼精铁", "制造指南书", "钨金")
# ★2026-09-14 用户定案：摄妖香每 299 分钟用一次（组队完成后使用，无则商城购买）
_XIANG_NAME = "摄妖香"          # 道具名
_XIANG_INTERVAL = 299 * 60                  # 使用间隔（秒）
# ★2026-09-14 用户确认女儿村走"背包→传送→十八门派"直达（复用 ZGUI.zhuagui_teleport）。
#   周游顺序 = 飞行符5图 + 快捷传送6图 + 传送1图（女儿村）。
_VISIT_CYCLE = [m[0] for m in FLY_MAPS] + list(QUICK_MAPS) + ["女儿村"]
_STOP = threading.Event()

_LAST_ROUND = {}                       # 与抓鬼脚本同构：本轮耗时分段观测


def _install_signal():
    def _h(signum, frame):
        global _STOP
        if _STOP.is_set():
            signal.signal(signal.SIGINT, signal.SIG_DFL)
            return
        _STOP.set()
        sys.stdout.write("\n[stop] 完成当前图后优雅退出（再按 Ctrl+C 强制）\n")
        sys.stdout.flush()
    signal.signal(signal.SIGINT, _h)


def _lua(gw, code, timeout=8.0):
    return ZGUI._lua_call(gw, code, timeout=timeout)


def _map_name(gw):
    return (_lua(gw, r"""
local me = tp and tp.地图
__out = tostring(me and me.地图名称 or '')""") or "").strip()


# ★2026-09-15 用户定案：本脚本**必须在队伍状态**才能传送/跑图。
#   ★队伍成员不能传送（对话框都不弹），必须散人状态传送后再组队；
#   反之散人状态跑图会脱离大队。所以未在队时一律原地等待归队。
def _team_ok(gw):
    """读队伍状态 → (is_teamed, mem, leader)。

    复用顶部头像栏（实时渲染，无面板懒加载脏快照），
    失败回退 p7 面板。读不到（通道/面板）时 mem=-1，
    is_teamed 为 False（宁停不乱跑）。
    """
    try:
        st = ZGUI.team_stats_topbar(gw)
        if st is None:
            st = ZGUI._team_stats(gw)
    except Exception:
        st = None
    if not st:
        return False, -1, ""
    mem = st[0] if st and st[0] is not None else -1
    leader = st[2] if len(st) > 2 else ""
    return (mem >= 2), mem, leader


_RE_TEAM_WAIT_S = 300.0


def _wait_reteam(gw, tag=""):
    """未在队时原地等待归队（每 5s 复查一次，最多 _RE_TEAM_WAIT_S）。

    返回 True=已归队；False=超时仍未归队（调用方决定是否继续等）。
    ★队伍成员不能传送，散人跑图又会脱队，所以只能等，
    不能自己跑图（那只会越走越散）。
    """
    t0 = time.time()
    _first = True
    while time.time() - t0 < _RE_TEAM_WAIT_S:
        if _STOP.is_set():
            return False
        ok, mem, ld = _team_ok(gw)
        if ok:
            if not _first:
                _LOG.warning("刷怪：已归队（成员=%s 队长=%s），继续刷怪" % (mem, ld or "-"))
            return True
        if _first:
            _LOG.warning("刷怪：%s未在队伍（成员=%s 队长=%s），原地等归队（暂停跑图/不补香）" % (tag, mem, ld or "-"))
            _first = False
        time.sleep(2.5)
    _LOG.warning("刷怪：等归队超时（%.0fs），仍未在队" % _RE_TEAM_WAIT_S)
    return False


def _wait_out_battle(gw, max_s=45.0):
    t0 = time.time()
    while time.time() - t0 < max_s:
        try:
            if not ZGUI.zhuagui_in_battle(gw):
                return True
        except Exception:
            return True
        time.sleep(1.5)
    return False



def _xiang_use(gw, hwnd):
    """使用摄妖香一次（找背包 → 无则商城购买 → 右键使用）。返回是否使用成功。

    ★2026-09-14 用户定案：组队完成后每 299 分钟用一次；
      背包没有就商城购买（复用 _mall_buy_item）。
      使用方式与天眼符同源：右键背包物品图标。
    """
    ZGUI._panel_pin_defaults(gw)
    ZGUI._sleep(random.uniform(0.15, 0.25))
    if not ZGUI._bag_ensure_open(gw, hwnd):
        _LOG.warning("刷怪：摄妖香使用时背包打不开")
        return False
    x, y = 0, 0
    for _ in range(4):
        x, y = ZGUI._bag_find_item_pos(gw, _XIANG_NAME)
        if x > 0:
            break
        ZGUI._sleep(random.uniform(0.25, 0.4))
    if x <= 0:
        _LOG.info("刷怪：背包无摄妖香 → 商城购买")
        if not ZGUI._mall_buy_item(gw, hwnd, _XIANG_NAME, bag_verify=_XIANG_NAME):
            _LOG.warning("刷怪：商城购买摄妖香失败（跳过本轮）")
            return False
        x, y = 0, 0
        for _ in range(4):
            x, y = ZGUI._bag_find_item_pos(gw, _XIANG_NAME)
            if x > 0:
                break
            ZGUI._sleep(random.uniform(0.25, 0.4))
        if x <= 0:
            _LOG.warning("刷怪：购买后背包仍找不到摄妖香")
            return False
    cx, cy = ZGUI._bag_cell_click_pos(x, y)
    ZGUI.post_right_click(hwnd, cx, cy, gateway=gw)
    ZGUI._sleep(random.uniform(0.3, 0.45))
    _LOG.info("刷怪：已使用摄妖香（下次 %d 分钟后）" % (_XIANG_INTERVAL // 60))
    return True

def _ensure_fly(gw, hwnd):
    """背包必须有飞行符：有→坐标；无→商城买一个再找。返回 (x,y) 或 (0,0)。

    ★2026-09-14 用户定案：先钉背包面板回默认位再找/点物品——面板被拖拽后
      物品数据.小动画.x/y 随面板偏移，右键飞行符/格子点击全漂移。
    """
    ZGUI._panel_pin_defaults(gw)
    ZGUI._sleep(random.uniform(0.15, 0.25))
    if not ZGUI._bag_ensure_open(gw, hwnd):
        return (0, 0)
    fx, fy = 0, 0
    for _ in range(4):
        fx, fy = ZGUI._bag_find_item_pos(gw, "飞行符")
        if fx > 0:
            return (fx, fy)
        ZGUI._sleep(random.uniform(0.25, 0.4))
    _LOG.info("刷怪：背包无飞行符 → 商城购买")
    if not ZGUI._mall_buy_item(gw, hwnd, "飞行符", bag_verify="飞行符"):
        return (0, 0)
    for _ in range(4):
        fx, fy = ZGUI._bag_find_item_pos(gw, "飞行符")
        if fx > 0:
            return (fx, fy)
        ZGUI._sleep(random.uniform(0.25, 0.4))
    return (0, 0)


def _fly_dialog_open(gw):
    """飞行符大地图是否打开（界面数据[10] 飞行符类 本类开关）。

    ★2026-09-14 实测定案（首次测试"对话框未打开"根因）：右键飞行符走
    物品数据类:刷新 → `tp.主界面.界面数据[10]:刷新(...)` —— 面板在
    界面数据[10]，不是 tp.窗口[10]（窗口表是另一张图）。
    """
    r = _lua(gw, r"""
local j = tp.主界面 and tp.主界面.界面数据
local v = j and j[10]
__out = tostring(v and v.本类开关)""")
    return r == "true"


def _travel_fly(gw, hwnd, mapname):
    """右键飞行符 → 点该图固定矩形 → 等落地。返回落地地图名。"""
    if not _wait_out_battle(gw):
        return ""
    fx, fy = _ensure_fly(gw, hwnd)
    if fx <= 0:
        _LOG.warning("刷怪：飞行符获取失败，跳过 %s" % mapname)
        return ""
    cx, cy = ZGUI._bag_cell_click_pos(fx, fy)
    ZGUI.post_right_click(hwnd, cx, cy, gateway=gw)
    ZGUI._sleep(random.uniform(0.6, 0.8))
    if not _fly_dialog_open(gw):
        # 再点一次（首次右键偶发落在物品提示上）
        ZGUI.post_right_click(hwnd, cx, cy, gateway=gw)
        ZGUI._sleep(random.uniform(0.6, 0.8))
        if not _fly_dialog_open(gw):
            _LOG.warning("刷怪：飞行符对话框未打开（%s）" % mapname)
            return ""
    rect = dict(FLY_MAPS)[mapname]
    ZGUI.post_click(hwnd, random.randint(rect[0], rect[2]),
                    random.randint(rect[1], rect[3]), gateway=gw)
    ZGUI._sleep(random.uniform(1.5, 2.0))
    # ★2026-09-14 修复：飞行在背包开着时点图，落地后必须关包——
    #   包开着会盖住左上角快捷菜单(149,10)，下一轮快捷传送根本点不着。
    try:
        ZGUI._bag_ensure_close(gw, hwnd)
    except Exception:
        pass
    return _map_name(gw)


def sw8(gw):
    """界面数据[8] 本类开关（快捷传送对话框）。"""
    return _lua(gw, r"""
local v = tp.主界面 and tp.主界面.界面数据 and tp.主界面.界面数据[8]
__out = tostring(v and v.本类开关)""") == "true"


def _open_quick_dialog(gw, hwnd):
    """确认「快捷传送」对话框（[8]）已打开。

    ★2026-09-17 用户定案（最新）：常规流程下**不需要再点快捷传送开关**——
      组队阶段已经把它打开了，之后一直开着。**只有游戏掉线重新登录后
      跳过组队**（--skip-team）时，才需要点开关把它重新打开。

    因此本函数分两条路：
      • 常规（_SKIP_TEAM=False）：只读 [8] 开关确认即可；意外未开 →
        只告警**不点任何开关**，交给上层/下一轮重试。
      • 跳过组队（_SKIP_TEAM=True，掉线重登）：点「快捷传送」按钮 _TP_BTN
        重开；再失败退化为点一次 (158,26) 重新展开菜单。
    """
    try:
        ZGUI._bag_ensure_close(gw, hwnd)
        ZGUI._sleep(random.uniform(0.2, 0.35))
    except Exception:
        pass
    if sw8(gw):
        return True
    # [8] 未开。★常规流程组队已开好，这里不再点开关（用户定案）。
    if not _SKIP_TEAM:
        _LOG.warning("刷怪：快捷传送对话框未开（常规流程本应由组队打开，"
                     "不点开关）")
        return False
    # 跳过组队（掉线重登后）→ 允许点开关重开
    _LOG.info("刷怪：跳过组队模式 → 快捷传送对话框未开，点开关重开")
    # [8] 未开：点「快捷传送」菜单按钮（不碰 158,26）
    for _try in range(2):
        ZGUI.post_click(hwnd, random.randint(_TP_BTN[0], _TP_BTN[2]),
                        random.randint(_TP_BTN[1], _TP_BTN[3]), gateway=gw)
        ZGUI._sleep(random.uniform(0.6, 0.85))
        if sw8(gw):
            _LOG.info("刷怪：快捷传送对话框未开，已点「快捷传送」按钮重开")
            return True
    # 兜底：菜单被收起时才点一次 (158,26) 重新展开
    _LOG.warning("刷怪：快捷传送对话框未开，退化点 (158,26) 重新展开菜单")
    ZGUI.post_click(hwnd, 158, 26, gateway=gw)
    ZGUI._sleep(random.uniform(0.4, 0.6))
    ZGUI.post_click(hwnd, random.randint(_TP_BTN[0], _TP_BTN[2]),
                    random.randint(_TP_BTN[1], _TP_BTN[3]), gateway=gw)
    ZGUI._sleep(random.uniform(0.6, 0.85))
    if sw8(gw):
        return True
    _LOG.warning("刷怪：快捷传送对话框未开（可能游戏重启）")
    return False


def _travel_quick(gw, hwnd, mapname):
    """快捷传送：确认对话框开着 → 点该图固定矩形 → 等落地。返回落地地图名。

    ★2026-09-14 定案：目标为 界面数据[8] 对话框里红字链接，坐标已在线实测
      （QUICK_MAP_RECTS：★2026-09-15 用户实机标定的真实链接包围盒），
      投到矩形内随机点，读落地地图名校验，不再走色簇自校准。

    ★2026-09-15 用户定案：用完**不再收起对话框**（原 _close_dialog8 +
      _collapse_quick_menu 已删）。对话框由「组队完成」阶段开一次后一直开着，
      每轮只点目标行，省掉每次开/关框的两次点击与等待。
    """
    if not _wait_out_battle(gw):
        return ""
    if not _open_quick_dialog(gw, hwnd):
        _LOG.warning("刷怪：快捷传送对话框未开（%s）" % mapname)
        return ""
    rect = QUICK_MAP_RECTS.get(mapname)
    if rect is None:
        _LOG.warning("刷怪：未知快捷目标 %s" % mapname)
        return ""
    landed = ""
    for _try in range(2):
        ZGUI.post_click(hwnd, random.randint(rect[0], rect[2]),
                        random.randint(rect[1], rect[3]), gateway=gw)
        ZGUI._sleep(random.uniform(1.75, 2.25))
        landed = _map_name(gw)
        if landed in QUICK_MAPS or not sw8(gw):
            break
    _LOG.info("刷怪：快捷传送→ %s（目标%s，矩形%s）"
              % (landed or "?", mapname, rect))
    return landed


def _travel_sect(gw, hwnd, dest="女儿村"):
    """背包→传送→十八门派直达：开包点"传送"→点女儿村 → 等落地。返回落地图名。

    ★2026-09-14 用户确认：背包"传送"可直达女儿村，队内全体跟随。
      复用 ZGUI.zhuagui_teleport（内部已开包/点传送/点目标/关包）；其目标矩形
      _TP_DEST_RECTS["女儿村"]=(114,320,166,334)。传送按钮 (258,436)-(287,447)
      依赖背包面板钉位，故跑图先钉位（面板被拖拽后漂移会点不准）。
    """
    if not _wait_out_battle(gw):
        return ""
    ZGUI._panel_pin_defaults(gw)
    ZGUI._sleep(random.uniform(0.15, 0.25))
    try:
        ZGUI._bag_ensure_close(gw, hwnd)
        ZGUI._sleep(random.uniform(0.15, 0.25))
    except Exception:
        pass
    if not ZGUI.zhuagui_teleport(gateway=gw, hwnd=hwnd, dest=dest):
        _LOG.warning("刷怪：背包传送失败（%s）" % dest)
        return ""
    return _map_name(gw)

def _hunt(gw, hwnd):
    """扫当前图白名单怪并打完。返回打掉怪名列表。"""
    _t0 = time.time()
    try:
        killed = ZGUI.zhuagui_bonus_battle(gw, verbose=False, hwnd=hwnd) or []
    except Exception as e:
        killed = []
        _LOG.warning("刷怪：扫打异常（不阻断）: %s" % e)
    _LAST_ROUND["hunt_s"] = round(time.time() - _t0, 1)
    return killed


def _sell_if_needed(gw, hwnd):
    try:
        n = ZGUI._bag_used_count(gw)
        if n is not None and n >= _SELL_MIN_BAG:
            _t0 = time.time()
            s = ZGUI.zhuagui_sell_junk(gw, hwnd=hwnd, extra_sell=_SELL_EXTRA)
            _LAST_ROUND["sell_s"] = round(time.time() - _t0, 1)
            if s:
                _LOG.info("刷怪：出售 %d 件（占用 %d 格）" % (s, n))
    except Exception as e:
        _LOG.warning("刷怪：出售异常（不阻断）: %s" % e)


def _auto_guard(gw, hwnd):
    """自动战斗守护线程（2026-09-14 用户定案"点自动拿过来"）。

    ★白名单打怪（zhuagui_bonus_battle）进战已内置点自动；但跑图途中遭遇的
      普通野怪战斗不在其内。守护线程轮询战斗态：一旦进战就后台拉起
      _battle_auto_kick（幂等：会话闸 _AUTO_ONCE 每 pid 只点一次「自动」），
      覆盖所有战斗场景。
    """
    last_in = False
    while not _STOP.is_set():
        try:
            inb = ZGUI.zhuagui_in_battle(gw)
        except Exception:
            inb = False
        if inb and not last_in:
            threading.Thread(target=ZGUI._battle_auto_kick,
                             args=(hwnd, gw), daemon=True).start()
        last_in = inb
        try:
            time.sleep(1.5)
        except Exception:
            return


def run_round(gw, hwnd, mapname):
    """一轮：去目标图 → 扫打 → 出售。返回 (落地图, 打掉数)。

    ★2026-09-15 用户定案（进队保护）：未在队则**不传送、不扫怪**，
    直接返回等归队。区队伍成员不能传送（对话框都不弹），
    散人状态跑图又会脱离大队——两边都不对，故一律等待。
    """
    _t0 = time.time()
    _ok, _mem, _ld = _team_ok(gw)
    if not _ok:
        _LAST_ROUND.clear()
        _LAST_ROUND["blocked"] = "未在队(成员=%s)" % _mem
        _LOG.warning("刷怪：未在队伍，本轮不传送不扫怪（成员=%s 队长=%s）" % (_mem, _ld or "-"))
        return "", 0
    for k in list(_LAST_ROUND):
        _LAST_ROUND.pop(k)
    fmaps = dict(FLY_MAPS)
    nm = ""
    if mapname in fmaps:
        nm = _travel_fly(gw, hwnd, mapname)
    elif mapname in QUICK_MAPS:
        nm = _travel_quick(gw, hwnd, mapname)
    elif mapname == "女儿村":
        nm = _travel_sect(gw, hwnd)
    _LAST_ROUND["landed"] = nm
    _LAST_ROUND["travel_s"] = round(time.time() - _t0, 1)
    if not nm:
        return "", 0
    killed = _hunt(gw, hwnd)
    _sell_if_needed(gw, hwnd)
    _LAST_ROUND["round_s"] = round(time.time() - _t0, 1)
    return nm, len(killed)


def main(argv=None):
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="全地图刷怪（PP GUI 方案：全地图刷怪）")
    ap.add_argument("--gateway", default="file://pzxy", help="网关/播种通道")
    ap.add_argument("--role", default="二号美人", help="角色名（多开钉窗）")
    ap.add_argument("--rounds", type=int, default=0, help="跑几轮（0=无限）")
    # ★2026-09-15 用户定案：缩短换图等待。原 25~45s 无设计依据（同类脚本
    #   闯关 8~20s / 测试 15~30s，刷怪因 12 图轮转最需要快节奏却设最久），
    #   判定为复制放大。改为 3~8s：留一点节奏缓冲，又不拖慢单圈。
    ap.add_argument("--min-interval", type=float, default=1.5)
    ap.add_argument("--max-interval", type=float, default=4.0)
    ap.add_argument("--start-map", default=None,
                    help="起始图（缺省顺序第一张）")
    # ★2026-09-17 用户定案：掉线重登后跳过组队拉起（如【恢复挂机】/重登闭环）。
    #   此时组队阶段没跑过，快捷传送 [8] 未开 → 才需要点开关补开。
    ap.add_argument("--skip-team", action="store_true",
                    help="跳过组队拉起（掉线重登后）：允许运行中补点快捷传送开关")
    # ★2026-09-14 修复：PP GUI 通传给队长脚本 --timeout/--wait-dialog
    #   （抓鬼方案用），本脚本不识别曾导致 argparse 报错退出。接受忽略。
    ap.add_argument("--timeout", type=float, default=None,
                    help="兼容 PP GUI 通用传参（本脚本不使用）")
    ap.add_argument("--wait-dialog", type=float, default=None,
                    help="兼容 PP GUI 通用传参（本脚本不使用）")
    args = ap.parse_args(argv)
    random.seed()
    global _SKIP_TEAM
    _SKIP_TEAM = bool(args.skip_team)
    if _SKIP_TEAM:
        _LOG.info("刷怪：跳过组队模式（掉线重登）→ 允许补点快捷传送开关")

    gw = args.gateway
    pw = None
    try:
        pw = ZGUI._find_role_window(args.role)
        if pw:
            ZGUI.set_target_hwnd(pw[1])
    except Exception:
        pass
    hwnd = pw[1] if pw else ZGUI.get_hwnd()
    if not hwnd:
        print("未找到游戏窗口。")
        return 2
    _install_signal()
    threading.Thread(target=_auto_guard, args=(gw, hwnd), daemon=True).start()

    # ★2026-09-14 用户定案：组队完成后（脚本被拉起即组队完成）
    #   立即使用一次摄妖香，之后每 299 分钟补一次（中断→下轮自动补）
    _xiang_next = 0.0
    try:
        if _xiang_use(gw, hwnd):
            _xiang_next = time.time() + _XIANG_INTERVAL
    except Exception as e:
        _LOG.warning("刷怪：首次用香异常（不阻断）: %s" % e)

    if args.start_map and args.start_map in _VISIT_CYCLE:
        start_i = _VISIT_CYCLE.index(args.start_map)
    else:
        start_i = 0

    print("=" * 60)
    print("全地图刷怪 | role=%s gw=%s" % (args.role, gw))
    print("  周游: %s" % " → ".join(_VISIT_CYCLE))
    print("  白名单: 知了王/星宿/远古/地煞星/天罡星")
    print("=" * 60)

    i = 0
    total_killed = 0
    err_n = 0
    while True:
        i += 1
        if _STOP.is_set():
            break
        if args.rounds and i > args.rounds:
            break
        mapname = _VISIT_CYCLE[(start_i + i - 1) % len(_VISIT_CYCLE)]
        # ★2026-09-15 用户定案（进队保护主循环部分）：
        #   补香之前先确认仍在队。若中途被踢出/掉队，
        #   不补香、不跑图，原地等归队（香是消耗品，
        #   且队伍成员传送无效）。超时仍未归队则继续等。
        _okc, _memc, _ldc = _team_ok(gw)
        if not _okc:
            if not _wait_reteam(gw, tag="[第%d轮前]" % i):
                time.sleep(5.0)
            continue
        # ★2026-09-14 用户定案：到了 299 分钟间隔就补一次摄妖香
        # （异常不阻断，下轮继续试）
        if _xiang_next and time.time() >= _xiang_next:
            try:
                if _xiang_use(gw, hwnd):
                    _xiang_next = time.time() + _XIANG_INTERVAL
            except Exception as e:
                _LOG.warning("刷怪：补用香异常（不阻断）: %s" % e)
        try:
            pw2 = ZGUI._find_role_window(args.role)
            if pw2:
                ZGUI.set_target_hwnd(pw2[1]); hwnd = pw2[1]
        except Exception:
            pass
        try:
            landed, nk = run_round(gw, hwnd, mapname)
        except Exception:
            import traceback
            err_n += 1
            print("[%03d] 异常: %s\n%s" % (i, sys.exc_info()[1],
                                            traceback.format_exc(limit=4)))
            time.sleep(5.0)
            continue
        total_killed += nk
        print("[%03d] 目标=%-6s 落地=%-8s 打怪=%d 耗时=%.1fs 累计击杀=%d"
              % (i, mapname, landed or "—", nk,
                 _LAST_ROUND.get("round_s", 0), total_killed))
        sys.stdout.flush()
        if _STOP.is_set() or (args.rounds and i >= args.rounds):
            break
        time.sleep(max(0.5, random.uniform(args.min_interval, args.max_interval)))

    print("=" * 60)
    print("结束 | 共 %d 轮 击杀 %d 只 异常 %d 次" % (i, total_killed, err_n))
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())