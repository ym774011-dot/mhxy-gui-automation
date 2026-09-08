# -*- coding: utf-8 -*-
"""CHUANGGUAN.py — 门派闯关自动化（2026-09-08，与抓鬼跑批随机合并调度）。

流程（用户 2026-09-08 定案 + 实测截图标定）：
  1) 合成旗飞长安（沿用抓鬼 zhuagui_go_back_changan 的旗子红点通道）
     → 角色走到 长安城(231,104) → 投影点击 门派闯关活动使者（npc 表，
     功能 NPC 无标识，CALL 包不可用——2026-09-08 实测定案）。
  2) 点「参加活动」→ 从 任务追踪 读目标门派（15 门派随机）。
  3) 背包「传送」按钮直传该门派（zhuagui_teleport，十八门派传送）。
  4) Tab 开大地图 → 按校准数据换算护法像素并点击 → 路径走到护法
     （化生寺/龙宫/阴曹地府 落地即护法，免走）→ 到位后 CALL 护法
     （护法是活动刷的地图单位，带标识，CALL 与抓鬼同款 0,3,6,标识,1）。
  5) 点「放马过来」进战 → 自动战斗等结束 → 任务追踪刷新进下一考验。
  循环直至任务追踪不再显示门派闯关（上限 6 轮防死循环）。

坐标校准（用户提供，格式：像素 = 校准像素 + (护法坐标-校准坐标)×缩放）：
  大唐官府(132,46)｜(481,237)↔(132,46)｜(2.750,2.652)
  神木林(23,142)｜(167,468)↔(23,142)｜(2.130,2.479)
  盘丝洞(152,117)｜(409,343)↔(152,117)｜(1.914,1.949)
  天宫(183,124)｜(430,331)↔(183,125)｜(1.705,1.728)
  狮驼岭(114,16)｜(358,288)↔(84,60)｜(2.857,2.883)
  魔王寨(47,55)｜(267,181)↔(49,23)｜(3.041,2.913)
  化生寺(37,72)｜无需移动，直接CALL
  无底洞(14,52)｜(196,193)↔(34,35)｜(2.294,2.229)
  五庄观(15,25)｜(222,227)↔(30,30)｜(3.500,3.767)
  凌波城(30,30)｜(286,232)↔(61,45)｜(2.770,2.622)
  龙宫(69,81)｜无需移动，直接CALL
  阴曹地府(62,79)｜无需移动，直接CALL
  普陀山(67,50)｜(402,208)↔(71,25)｜(4.000,3.720)
  女儿村(65,74)｜(293,224)↔(87,57)｜(2.023,1.930)
  方寸山(58,132)｜(305,216)↔(111,63)｜(1.676,1.603)
"""
import random
import time

from tasks.library import ZGUI
from tasks.library.ZGUI import (
    _lua_call, _sleep, _coord_int, logger, post_click, post_right_click,
    zhuagui_go_back_changan, zhuagui_teleport, zhuagui_in_battle,
    self_world_xy, get_hwnd, _zhongkui_detect_rows, _battle_auto_kick,
    _mouse_clear, user32,
)
import ctypes
import ctypes.wintypes as wt
import threading

# 15 门派（任务追踪解析用，顺序无关）
SECTS = ("大唐官府", "神木林", "盘丝洞", "天宫", "狮驼岭", "魔王寨", "化生寺",
         "无底洞", "五庄观", "凌波城", "龙宫", "阴曹地府", "普陀山", "女儿村",
         "方寸山")

# name -> (护法游戏坐标(x,y), 校准像素(x,y), 校准游戏坐标(x,y), 缩放(x,y))；None=落地直接CALL
SECT_CALIB = {
    "大唐官府": ((132, 46), (481, 237), (132, 46), (2.750, 2.652)),
    "神木林":   ((23, 142), (167, 468), (23, 142), (2.130, 2.479)),
    "盘丝洞":   ((152, 117), (409, 343), (152, 117), (1.914, 1.949)),
    "天宫":     ((183, 124), (430, 331), (183, 125), (1.705, 1.728)),
    "狮驼岭":   ((114, 16), (358, 288), (84, 60), (2.857, 2.883)),
    "魔王寨":   ((47, 55), (267, 181), (49, 23), (3.041, 2.913)),
    "化生寺":   ((37, 72), None, None, None),
    "无底洞":   ((14, 52), (196, 193), (34, 35), (2.294, 2.229)),
    "五庄观":   ((15, 25), (222, 227), (30, 30), (3.500, 3.767)),
    "凌波城":   ((30, 30), (286, 232), (61, 45), (2.770, 2.622)),
    "龙宫":     ((69, 81), None, None, None),
    "阴曹地府": ((62, 79), None, None, None),
    "普陀山":   ((67, 50), (402, 208), (71, 25), (4.000, 3.720)),
    "女儿村":   ((65, 74), (293, 224), (87, 57), (2.023, 1.930)),
    "方寸山":   ((58, 132), (305, 216), (111, 63), (1.676, 1.603)),
}

# 长安城活动集合点（用户标定 ~231,104）与 使者在 npc 表的称谓
_ACT_LIST_GAME = (231, 104)
_ACT_ENVOY_TITLE = "门派闯关活动使者"

_MAX_TRIALS = 16         # ★游戏规则：一次报名=15 次考验，全部完成前不能抓鬼
                         # （用户 2026-09-08 定案；16=15+1 防边界）
_ARRIVE_TOL_GAME = 16.0  # 到位判定：距护法 <16 游戏单位即 CALL（用户：略偏无妨）
_STALL_GAP_S = 5.0       # 走路停滞判定：位置变化 <5px 视为停滞


def _key_press(hwnd, vk=0x09):
    """后台按键（默认 Tab）。"""
    user32.PostMessageW(hwnd, 0x0100, vk, 0)
    time.sleep(0.05)
    user32.PostMessageW(hwnd, 0x0101, vk, 0xC0000000)


def read_tracker_sect(gateway):
    """从任务追踪读当前目标门派名；无门派闯关任务返回 None。

    2026-09-08 实测字段：tp.窗口.任务追踪.介绍文本.显示表.N.M.内容，
    行2='请你们立即前往' + 门派名（独立彩色段）+ 行3='考验，当前…'。
    """
    code = r"""
local tz = tp.窗口 and tp.窗口.任务追踪
local rt = tz and tz.介绍文本
local st = rt and rt.显示表
if type(st) ~= 'table' then __out = '' return end
local out = {}
for _, row in pairs(st) do
  if type(row) == 'table' then
    for _, seg in pairs(row) do
      if type(seg) == 'table' and type(seg.内容) == 'string' then
        out[#out+1] = seg.内容
      end
    end
  end
end
__out = table.concat(out, '#')
"""
    r = _lua_call(gateway, code) or ""
    if "门派闯关" not in r and "考验" not in r:
        return None
    for s in SECTS:
        if s in r:
            return s
    return None


def _walk_world(gateway, hwnd, wx, wy, tol_game=_ARRIVE_TOL_GAME,
                timeout=60.0, verbose=False):
    """走到世界像素 (wx,wy)：视野内直点，视野外朝目标点视野边缘渐进。

    ★到位判定靠实时读 主角.xy（不傻等）；停滞（连续两窗位移<5px）提前
    放弃返回 False（用户：坐标略偏无妨，能 CALL 到就行）。
    """
    t0 = time.time()
    last_x = last_y = None
    last_move_ts = time.time()
    stall = False
    while time.time() - t0 < timeout:
        pos = self_world_xy(gateway)
        if pos:
            dx, dy = pos[0] - wx, pos[1] - wy
            dist = (dx * dx + dy * dy) ** 0.5
            if dist < tol_game * 20:
                if verbose:
                    logger.info("闯关走路：到位 (%d,%d) 距目标 %.0fpx" % (pos[0], pos[1], dist))
                return True
            # 停滞检测
            if last_x is not None:
                mv = abs(pos[0] - last_x) + abs(pos[1] - last_y)
                if mv >= 5:
                    last_move_ts = time.time()
                    stall = False
                elif time.time() - last_move_ts > _STALL_GAP_S:
                    stall = True
            last_x, last_y = pos[0], pos[1]
        # 投影目标点
        r = _lua_call(gateway, r"""local o=tp.屏幕.xy
__out=tostring(o and o.x or 0)..','..tostring(o and o.y or 0)""") or "0,0"
        try:
            ox, oy = _coord_int(r.split(",")[0]), _coord_int(r.split(",")[1])
        except Exception:
            ox = oy = 0
        px = _coord_int(str(wx + ox))
        py = _coord_int(str(wy + oy))
        if px is None or py is None:
            _sleep(random.uniform(0.8, 1.2))
            continue
        wr = wt.RECT()
        user32.GetClientRect(hwnd, ctypes.byref(wr))
        if 0 <= px < wr.right and 0 <= py < wr.bottom:
            post_click(hwnd, px + random.randint(-3, 3),
                       py + random.randint(-3, 3), gateway=gateway)
        else:
            cx = max(30, min(wr.right - 30, px))
            cy = max(30, min(wr.bottom - 30, py))
            if verbose:
                logger.info("闯关走路：目标越界(%d,%d) 朝其点视野(%d,%d)" % (px, py, cx, cy))
            post_click(hwnd, cx, cy, gateway=gateway)
        _sleep(random.uniform(2.0, 2.8))
        if stall:
            break
    if verbose:
        logger.info("闯关走路：超时/停滞退出（坐标略偏无妨）")
    return False


def _guard_map_pixel(sect):
    """按校准公式换算护法的大地图像素：像素 = 校准像素 + (护法-校准坐标)×缩放。"""
    calib = SECT_CALIB.get(sect)
    if not calib or calib[1] is None:
        return None
    guard, cpx, cgrid, scale = calib
    px = cpx[0] + (guard[0] - cgrid[0]) * scale[0]
    py = cpx[1] + (guard[1] - cgrid[1]) * scale[1]
    return (int(round(px)), int(round(py)))


def _click_dialog_first_row(gateway, hwnd, tries=5, tag=""):
    """点对话红字第一行顶部条带（第一行=参加活动/放马过来，顶部条带绝不
    误触下面取消行）。返回是否点击成功。"""
    for _ in range(max(1, tries)):
        rows = _zhongkui_detect_rows(gateway)
        if rows:
            b = rows[0]
            post_click(hwnd, random.randint(b["x0"] + 3, max(b["x0"] + 4, b["x1"] - 3)),
                       random.randint(b["y0"] + 2, min(b["y0"] + 7, b["y1"])),
                       gateway=gateway)
            logger.info("闯关%s：已点对话首行顶部条带 (x%d-%d,y%d-%d)"
                        % (tag, b["x0"], b["x1"], b["y0"], b["y1"]))
            return True
        _sleep(random.uniform(0.4, 0.6))
    return False


def _dismiss_dialog(gateway, hwnd):
    """右键弹窗上关闭（用户确认：右键必须在弹窗上；落点=红字行右侧面板空白）。"""
    rows = _zhongkui_detect_rows(gateway)
    if rows:
        b = rows[0]
        dx = min(max(b["x1"] + 40, 300), 560)
        dy = (b["y0"] + b["y1"]) // 2
    else:
        dx, dy = 370, 330
    post_right_click(hwnd, dx, dy, gateway=gateway)
    _sleep(random.uniform(0.8, 1.0))


def _call_guard_npc(gateway, hwnd, sect, guard_grid, verbose=False):
    """CALL 门派护法：优先地图单位按门派名/护法称谓找标识发 CALL 包；
    找不到（标识读不到）退回投影点击护法身体（点 NPC=同款对话请求）。"""
    _sleep(random.uniform(0.15, 0.4))   # ★柔和化，与抓鬼 CALL 同款
    code = r"""
local t = tp.地图.地图单位
if type(t) ~= 'table' then __out = '' return end
local key = KEYPAT
for _, v in pairs(t) do
  if type(v) == 'table' then
    local nm = tostring(v.名称 or '')
    local tt = tostring(v.称谓 or '')
    if v.标识 and (nm:find(key, 1, true) or tt:find(key, 1, true)
                   or nm:find('护法', 1, true) or tt:find('护法', 1, true)) then
      __out = tostring(v.标识) .. '|' .. nm
      return
    end
  end
end
__out = ''
""".replace("KEYPAT", sect)
    r = _lua_call(gateway, code) or ""
    if "|" in r:
        gid, nm = r.split("|", 1)
        if gid.strip().isdigit():
            _lua_call(gateway, "客户端:发送数据(0,3,6," + gid.strip() + ",1)")
            logger.info("闯关：已 CALL 护法 %s（标识%s）" % (nm, gid.strip()))
            return True
    # 兜底：投影点击护法身体（游戏坐标×20 → 世界像素 → 屏幕）
    wx, wy = guard_grid[0] * 20, guard_grid[1] * 20
    r = _lua_call(gateway, r"""local o=tp.屏幕.xy
__out=tostring(o and o.x or 0)..','..tostring(o and o.y or 0)""") or "0,0"
    try:
        ox, oy = _coord_int(r.split(",")[0]), _coord_int(r.split(",")[1])
    except Exception:
        ox = oy = 0
    px, py = _coord_int(str(wx + ox)), _coord_int(str(wy + oy))
    wr = wt.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(wr))
    if px is None or py is None or not (0 <= px < wr.right and 0 <= py < wr.bottom):
        logger.warning("闯关：护法不在视野（投影%d,%d），CALL 失败" % (px, py))
        return False
    post_click(hwnd, px + random.randint(-4, 4),
               py + random.randint(-24, -14), gateway=gateway)
    logger.info("闯关：护法无标识，已投影点击身体 (%d,%d)" % (px, py))
    return True


def run(gateway=ZGUI.DEFAULT_GATEWAY, hwnd=None, verbose=True, **kw):
    """门派闯关主流程（Leader 侧）。返回 True=至少完成一场考验战斗。

    ★游戏规则（用户 2026-09-08 定案）：接了门派闯关就不能抓鬼，15 次考验
    全部完成后才恢复。故入口先查任务追踪：已有进行中的闯关任务 → 跳过
    报名段（旗子/使者/参加活动）直接续跑考验；没有才走完整报名流程。
    """
    if hwnd is None:
        hwnd = get_hwnd()
    if not hwnd:
        logger.warning("闯关：无游戏窗口")
        return False
    won = 0
    try:
        # ---- 0) 已有进行中的闯关任务 → 直接续跑（跳过报名段）----
        existing = read_tracker_sect(gateway)
        if existing:
            logger.info("闯关：检测到进行中的门派闯关（当前目标 %s）→ 续跑考验" % existing)
        else:
            # ---- 1) 旗子飞长安（沿用抓鬼通道）----
            if not zhuagui_go_back_changan(gateway=gateway):
                logger.warning("闯关：旗子回长安失败，中止")
                return False
        # ---- 2) 走到活动集合点 → 点使者 → 参加活动（仅新报名时）----
            gx, gy = _ACT_LIST_GAME
            if not _walk_world(gateway, hwnd, gx * 20, gy * 20, tol_game=20.0,
                               timeout=45.0, verbose=verbose):
                logger.info("闯关：未精确到集合点（坐标略偏无妨），继续点使者")
            code = r"""
local nl = tp.地图 and tp.地图.npc
if type(nl) ~= 'table' then __out = '' return end
for _, v in pairs(nl) do
  if type(v) == 'table' and tostring(v.称谓 or '') == 'TITLE' then
    __out = tostring(v.x) .. ',' .. tostring(v.y)
    return
  end
end
__out = ''
""".replace("TITLE", _ACT_ENVOY_TITLE)
            r = _lua_call(gateway, code) or ""
            if "," not in r:
                logger.warning("闯关：长安城找不到门派闯关活动使者，中止")
                return False
            ex, ey = [int(float(v)) for v in r.split(",")]
            r = _lua_call(gateway, r"""local o=tp.屏幕.xy
__out=tostring(o and o.x or 0)..','..tostring(o and o.y or 0)""") or "0,0"
            ox, oy = [int(float(v)) for v in r.split(",")]
            px, py = ex + ox, ey + oy
            wr = wt.RECT()
            user32.GetClientRect(hwnd, ctypes.byref(wr))
            if not (0 <= px < wr.right and 0 <= py < wr.bottom):
                logger.warning("闯关：使者不在视野(%d,%d)，中止" % (px, py))
                return False
            post_click(hwnd, px + random.randint(-3, 3), py + random.randint(-6, 0),
                       gateway=gateway)
            _sleep(random.uniform(1.2, 1.6))
            if not _click_dialog_first_row(gateway, hwnd, tag="参加活动"):
                logger.warning("闯关：使者对话未弹出（红字行无结果），中止")
                return False
            _mouse_clear(hwnd, gateway)
        # ---- 3) 考验循环（以任务追踪为准，上限 _MAX_TRIALS）----
        for trial in range(1, _MAX_TRIALS + 1):
            # 等任务追踪刷新（参加活动/上一场战斗结算有延迟）
            sect = None
            t0 = time.time()
            while time.time() - t0 < 20.0:
                sect = read_tracker_sect(gateway)
                if sect:
                    break
                _sleep(random.uniform(1.5, 2.2))
            if not sect:
                logger.info("闯关：任务追踪已无门派闯关（完成/未接上），共赢 %d 场" % won)
                break
            calib = SECT_CALIB.get(sect)
            if calib is None:
                logger.warning("闯关：未知门派 %s（校准缺失），中止" % sect)
                break
            guard_grid, cpx, cgrid, scale = calib
            logger.info("闯关：第%d次考验 → 目标 %s" % (trial, sect))
            # 3a) 背包传送按钮直传该门派
            if not zhuagui_teleport(gateway=gateway, hwnd=hwnd, dest=sect, verbose=verbose):
                logger.warning("闯关：传送 %s 失败，中止" % sect)
                break
            # 3b) 大地图点护法像素 → 路径走过去（免走门派直接 CALL）
            if cpx is not None:
                mpx, mpy = _guard_map_pixel(sect)
                _key_press(hwnd, 0x09)            # Tab 开大地图
                _sleep(random.uniform(1.2, 1.6))
                post_click(hwnd, mpx + random.randint(-2, 2),
                           mpy + random.randint(-2, 2), gateway=gateway)
                _sleep(random.uniform(0.8, 1.2))
                _key_press(hwnd, 0x09)            # Tab 关大地图
                _sleep(random.uniform(0.8, 1.2))
            wx, wy = guard_grid[0] * 20, guard_grid[1] * 20
            _walk_world(gateway, hwnd, wx, wy, timeout=60.0, verbose=verbose)
            # 3c) CALL 护法 → 放马过来
            if not _call_guard_npc(gateway, hwnd, sect, guard_grid, verbose=verbose):
                logger.warning("闯关：CALL 护法失败（%s），中止" % sect)
                break
            _sleep(random.uniform(1.0, 1.5))
            if not _click_dialog_first_row(gateway, hwnd, tag="放马过来"):
                logger.warning("闯关：护法对话未弹出（%s），中止" % sect)
                _dismiss_dialog(gateway, hwnd)
                break
            _mouse_clear(hwnd, gateway)
            # 3d) 等进战 + 自动战斗 + 等结束
            t0 = time.time()
            while time.time() - t0 < 15.0 and not zhuagui_in_battle(gateway):
                _sleep(random.uniform(0.8, 1.2))
            if not zhuagui_in_battle(gateway):
                logger.warning("闯关：点放马过来后未进战（%s），中止" % sect)
                break
            threading.Thread(target=_battle_auto_kick, args=(hwnd, gateway),
                             daemon=True).start()
            t1 = time.time()
            while zhuagui_in_battle(gateway) and time.time() - t1 < 300.0:
                _sleep(random.uniform(1.5, 2.2))
            if zhuagui_in_battle(gateway):
                logger.warning("闯关：战斗超时 300s（%s），中止" % sect)
                break
            won += 1
            logger.info("闯关：%s 战斗结束（累计赢 %d 场）" % (sect, won))
            _sleep(random.uniform(2.0, 3.0))   # 任务追踪刷新
        logger.info("闯关：流程结束，共赢 %d 场" % won)
        return won > 0
    except Exception as e:
        logger.warning("闯关：异常中止: %s" % e)
        return won > 0
