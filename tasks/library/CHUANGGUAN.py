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
import re
import time

from tasks.library import ZGUI
from tasks.library.ZGUI import (
    _lua_call, _sleep, _coord_int, logger, post_click, post_right_click,
    zhuagui_go_back_changan, zhuagui_teleport, zhuagui_in_battle,
    self_world_xy, get_hwnd, _zhongkui_detect_rows, _battle_auto_kick,
    _mouse_clear, user32, _bag_ensure_open, _bag_cell_click_pos,
    _bag_ensure_close, _auto_button_visible,
)
import ctypes
import ctypes.wintypes as wt
import threading

# 门派（任务追踪解析用，顺序无关）。★2026-09-09 补 天机城/女魃墓：私服实测
#   天机城闯关——15 表缺新门派 → read_tracker_sect 匹配不到 → 假"无任务"
#   中止 0 场（10:10 18920 实锤）。仍有漏网由 "立即前往#X#" 段解析兜底，
#   无校准门派走「不走路直接 CALL」通道（用户定案）。
SECTS = ("大唐官府", "神木林", "盘丝洞", "天宫", "狮驼岭", "魔王寨", "化生寺",
         "无底洞", "五庄观", "凌波城", "龙宫", "阴曹地府", "普陀山", "女儿村",
         "方寸山", "天机城", "女魃墓")

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

# ★放马过来按钮固定矩形（用户 2026-09-08 深夜标定：123,307,160,317）
#   红字行检测常与上行合并成 x30-168 大行，条带随机点会落在按钮文字外
#   =点击落空（天宫 4 连点无效根因之一）。识别行 y 与标定相符时优先点此矩形。
_FANGMA_RECT = (123, 307, 160, 317)

_MAX_TRIALS = 16         # ★游戏规则：一次报名=15 次考验，全部完成前不能抓鬼
                         # （用户 2026-09-08 定案；16=15+1 防边界）
_ARRIVE_TOL_GAME = 16.0  # 到位判定：距护法 <16 游戏单位即 CALL（用户：略偏无妨）
_STALL_GAP_S = 5.0       # 走路停滞判定：位置变化 <5px 视为停滞

# ★2026-09-08 摄妖香（每次接闯关后买一次并用一次，防跨图走路遇敌）。
#   2026-09-08 晚定案：商城 Lua 直读通用函数已上移 ZGUI（_mall_state/
#   _mall_find_item/_mall_buy_rect/_mall_buy_item，PID 22616 实测），
#   本模块只保留摄妖香背包读取与使用，购买统一走 ZGUI._mall_buy_item。


def _sheaoxiang_pos(gateway):
    """背包中摄妖香的物品坐标 (x,y)；无/包未开返回 (0,0)。同天眼读小动画。"""
    code = r"""
local j = tp.主界面 and tp.主界面.界面数据
local pd = type(j) == 'table' and type(j[3]) == 'table' and j[3].物品数据
if type(pd) ~= 'table' then __out = '0,0' return end
for i = 1, 40 do
  local it = pd[i]
  if type(it) == 'table' and tostring(it.名称 or ''):find('摄妖香') then
    local sa = it.小动画
    if type(sa) == 'table' then
      local x = tonumber(sa.x)
      local y = tonumber(sa.y)
      if x and y and x > 0 and y > 0 then
        __out = string.format('%d,%d', x, y)
        return
      end
    end
  end
end
__out = '0,0'
"""
    r = _lua_call(gateway, code) or "0,0"
    if "," not in r:
        return (0, 0)
    try:
        x, y = [int(round(float(v))) for v in r.split(",")]
        return (x, y)
    except Exception:
        return (0, 0)


def _buy_and_use_sheaoxiang(gateway, hwnd, verbose=True):
    """买并使用摄妖香：ZGUI._mall_buy_item 按名购买（全 Lua 定位+闭环验证，
    购后开包复核）→ 背包右键使用（同天眼符通道）。任何一步失败只告警不阻断
    （香是防遇敌辅助，不影响闯关主链路）。"""
    try:
        logger.info("闯关：购买摄妖香...")
        if not ZGUI._mall_buy_item(gateway, hwnd, "摄妖香", bag_verify="摄妖香"):
            logger.warning("闯关：摄妖香购买失败，跳过使用")
            return False
        # 开包找摄妖香并使用（右键，同天眼符通道）
        if not _bag_ensure_open(gateway, hwnd):
            logger.warning("闯关：背包打不开，摄妖香使用跳过")
            return False
        x, y = 0, 0
        for _ in range(6):
            x, y = _sheaoxiang_pos(gateway)
            if x > 0 and y > 0:
                break
            _sleep(random.uniform(0.5, 0.8))
        if x <= 0 or y <= 0:
            logger.warning("闯关：背包里没找到摄妖香（购买可能未生效），跳过使用")
            return False
        cx, cy = _bag_cell_click_pos(x, y)
        post_right_click(hwnd, cx, cy, gateway=gateway)
        _sleep(random.uniform(0.6, 1.0))
        _mouse_clear(hwnd, gateway)
        logger.info("闯关：摄妖香已使用（背包 %d,%d）" % (cx, cy))
        return True
    except Exception as e:
        logger.warning("闯关：摄妖香流程异常（不阻断）: %s" % e)
        return False


_INCENSE_GUARD_S = 1500  # 摄妖香防重复护栏：25 分钟内已用则跳过（无法读 buff 态，
                         # 以时间闸代替；反复中止重入 run() 也不会连环消费）
_INCENSE_TS = 0.0        # 上次成功使用摄妖香的 time.time()


def _ensure_sheaoxiang(gateway, hwnd, verbose=True):
    """确保摄妖香已使用（★2026-09-08 晚改：报名与续跑通用——续跑考验
    原来完全跳过摄妖香，跨图走路遇敌，用户指正）。
    包里有 → 直接用；没有 → 商城买一个再用（_buy_and_use_sheaoxiang）。
    25 分钟内已用过则跳过（防 run() 反复重入连环消费）。"""
    global _INCENSE_TS
    if time.time() - _INCENSE_TS < _INCENSE_GUARD_S:
        logger.info("闯关：摄妖香 %d 分钟内已使用，跳过"
                    % int((time.time() - _INCENSE_TS) / 60))
        return True
    try:
        # 包里有就直接用（省一笔）
        if _bag_ensure_open(gateway, hwnd):
            x, y = 0, 0
            for _ in range(4):
                x, y = _sheaoxiang_pos(gateway)
                if x > 0 and y > 0:
                    break
                _sleep(random.uniform(0.5, 0.8))
            if x > 0 and y > 0:
                cx, cy = _bag_cell_click_pos(x, y)
                post_right_click(hwnd, cx, cy, gateway=gateway)
                _sleep(random.uniform(0.6, 1.0))
                _mouse_clear(hwnd, gateway)
                _INCENSE_TS = time.time()
                logger.info("闯关：摄妖香已使用（背包现有 %d,%d）" % (cx, cy))
                return True
        # 没有 → 买一个再用
        if _buy_and_use_sheaoxiang(gateway, hwnd, verbose=verbose):
            _INCENSE_TS = time.time()
            return True
        logger.warning("闯关：摄妖香未确保成功（不阻断主链路）")
        return False
    except Exception as e:
        logger.warning("闯关：摄妖香流程异常（不阻断）: %s" % e)
        return False


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
    # ★2026-09-09 新门派兜底：目标门派是独立彩色段、紧跟"立即前往"（实机
    #   dump：R2=[◆|请你们立即前往|天机城|接]）。未登记门派也照返，下游
    #   run() 对无校准门派走「不走路直接 CALL」通道（用户定案）。
    m = re.search(r"立即前往#([^#]+)#", r)
    if m:
        return m.group(1)
    return None


def _walk_world(gateway, hwnd, wx, wy, tol_game=_ARRIVE_TOL_GAME,
                timeout=60.0, verbose=False):
    """走到世界像素 (wx,wy)：★2026-09-08 晚用户定案——移动指令（大地图
    点击）发出后只等不点，等 CALL 界面出来即可。移动中反复点击会误触
    界面按钮（乱点事故根因，越界夹逼点更会压到按钮）。
    到位判定靠实时读 主角.xy；仅当确认角色已停滞（停稳 5s 未到位）才
    补点，最多 2 次（停稳状态点击符合"移动中不点"铁律）。
    """
    t0 = time.time()
    last_x = last_y = None
    last_move_ts = time.time()
    fix_clicks = 0
    wr = wt.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(wr))

    def _project_click():
        r = _lua_call(gateway, r"""local o=tp.屏幕.xy
__out=tostring(o and o.x or 0)..','..tostring(o and o.y or 0)""") or "0,0"
        try:
            ox, oy = _coord_int(r.split(",")[0]), _coord_int(r.split(",")[1])
        except Exception:
            return False
        px = _coord_int(str(wx + ox))
        py = _coord_int(str(wy + oy))
        if px is None or py is None:
            return False
        if 0 <= px < wr.right and 0 <= py < wr.bottom:
            post_click(hwnd, px + random.randint(-3, 3),
                       py + random.randint(-3, 3), gateway=gateway)
        else:
            cx = max(30, min(wr.right - 30, px))
            cy = max(30, min(wr.bottom - 30, py))
            if verbose:
                logger.info("闯关走路：目标越界(%d,%d) 朝其点视野(%d,%d)" % (px, py, cx, cy))
            post_click(hwnd, cx, cy, gateway=gateway)
        return True

    while time.time() - t0 < timeout:
        pos = self_world_xy(gateway)
        if pos:
            dx, dy = pos[0] - wx, pos[1] - wy
            dist = (dx * dx + dy * dy) ** 0.5
            if dist < tol_game * 20:
                if verbose:
                    logger.info("闯关走路：到位 (%d,%d) 距目标 %.0fpx" % (pos[0], pos[1], dist))
                return True
            if last_x is not None:
                mv = abs(pos[0] - last_x) + abs(pos[1] - last_y)
                if mv >= 5:
                    last_move_ts = time.time()
            last_x, last_y = pos[0], pos[1]
        # ★纯等待：移动中绝不补点；仅停滞（停稳 5s 未到位）才补，最多 2 次
        if time.time() - last_move_ts > _STALL_GAP_S:
            if fix_clicks >= 2:
                if verbose:
                    logger.info("闯关走路：停滞且补点用尽，放弃（坐标略偏无妨）")
                break
            if _project_click():
                fix_clicks += 1
                if verbose:
                    logger.info("闯关走路：角色停滞，补点第%d次" % fix_clicks)
            last_move_ts = time.time()
            _sleep(random.uniform(2.0, 2.8))
            continue
        _sleep(random.uniform(0.8, 1.2))
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


def _click_dialog_first_row(gateway, hwnd, tries=5, tag="", fixed_rect=None):
    """点对话红字第一行顶部条带（第一行=参加活动/放马过来，顶部条带绝不
    误触下面取消行）。返回是否点击成功。

    ★2026-09-08 用户规则：移动中不点击——先等角色停稳再点（移动中画面
    在动，识别框与实际弹窗错位，鼠标滑过去也点不中）。
    ★2026-09-08 深夜：放马过来实测红字行会与上行合并（识别出 x30-168
    的大行），条带内随机点常落在按钮文字外=点击落空。用户标定固定矩形
    (123,307)-(160,317)——识别行与标定 y 相符时优先点固定矩形。
    """
    _wait_move_stop(gateway, max_wait=6.0)
    for _ in range(max(1, tries)):
        rows = _zhongkui_detect_rows(gateway)
        if rows:
            b = rows[0]
            if fixed_rect and abs(b["y0"] - fixed_rect[1]) < 15:
                fx0, fy0, fx1, fy1 = fixed_rect
                post_click(hwnd, random.randint(fx0 + 2, fx1 - 2),
                           random.randint(fy0 + 2, fy1 - 2), gateway=gateway)
                logger.info("闯关%s：已点标定矩形 (%d,%d)-(%d,%d)（识别行 y%d-%d 相符）"
                            % (tag, fx0, fy0, fx1, fy1, b["y0"], b["y1"]))
            else:
                post_click(hwnd, random.randint(b["x0"] + 3, max(b["x0"] + 4, b["x1"] - 3)),
                           random.randint(b["y0"] + 2, min(b["y0"] + 7, b["y1"])),
                           gateway=gateway)
                logger.info("闯关%s：已点对话首行顶部条带 (x%d-%d,y%d-%d)"
                            % (tag, b["x0"], b["x1"], b["y0"], b["y1"]))
            # ★2026-09-08 用户实况定位：点击后鼠标不能马上移走——引擎下一帧
            # 才处理点击，光标被 _mouse_clear 移走=命中落空（第一次无效根因）。
            # 0.5-0.8s 仍不够（22:53 用户复现第一次又没生效），加到 1.2-1.5s。
            _sleep(random.uniform(1.2, 1.5))
            return True
        _sleep(random.uniform(0.4, 0.6))
    return False


def _dismiss_dialog(gateway, hwnd):
    """右键弹窗上关闭（用户确认：右键必须在弹窗上）。

    ★2026-09-08 收紧：检测不到红字行时什么都不做（不盲右键）——
      实况事故：CALL 弹出的对话被本函数盲右键误关（用户目击）。
    """
    rows = _zhongkui_detect_rows(gateway)
    if not rows:
        return False
    b = rows[0]
    dx = min(max(b["x1"] + 40, 300), 560)
    dy = (b["y0"] + b["y1"]) // 2
    post_right_click(hwnd, dx, dy, gateway=gateway)
    _sleep(random.uniform(0.8, 1.0))
    return True


def _wait_move_stop(gateway, max_wait=8.0):
    """等角色停止移动（连续两读位移<6px 判停）。用户规则：移动中画面在动，
    兜底点击必偏——必须停稳后才允许点护法身体。返回是否停稳。"""
    t0 = time.time()
    lx = ly = None
    stable = 0
    while time.time() - t0 < max_wait:
        pos = self_world_xy(gateway)
        if pos:
            if lx is not None:
                mv = abs(pos[0] - lx) + abs(pos[1] - ly)
                stable = stable + 1 if mv < 6 else 0
                if stable >= 2:
                    return True
            lx, ly = pos[0], pos[1]
        _sleep(random.uniform(0.4, 0.6))
    return False


def _call_guard_npc(gateway, hwnd, sect, guard_grid, verbose=False):
    """CALL 门派护法：优先地图单位按门派名/护法称谓找标识发 CALL 包；
    找不到（标识读不到）退回投影点击护法身体（点 NPC=同款对话请求）。

    ★2026-09-08 两连修：
      1) KEYPAT 裸词语法错误（local key = 女儿村 → Lua 报错 → 永远读空
         → 永远走点击兜底）。实机对比：裸词=None，加引号='2|女儿村护法'。
      2) 用户规则：兜底点击必须等角色停稳（移动中画面在动点击必偏）；
         且距护法 >200px 时不点（太远点不中，宁可下轮重来）。
    """
    _wait_move_stop(gateway, max_wait=8.0)
    _sleep(random.uniform(0.15, 0.4))   # ★柔和化，与抓鬼 CALL 同款
    code = r"""
local t = tp.地图.地图单位
if type(t) ~= 'table' then __out = '' return end
local key = 'KEYPAT'
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
    r = ""
    for _ in range(7):                  # ★轮询：单位表刷出有延迟，最多 ~4s
        r = _lua_call(gateway, code) or ""
        if "|" in r:
            break
        _sleep(random.uniform(0.5, 0.7))
    if "|" in r:
        gid, nm = r.split("|", 1)
        if gid.strip().isdigit():
            _lua_call(gateway, "客户端:发送数据(0,3,6," + gid.strip() + ",1)")
            logger.info("闯关：已 CALL 护法 %s（标识%s）" % (nm, gid.strip()))
            return True
    # 兜底：停稳 + 距离检查后才投影点击护法身体（★用户规则：移动中不点）。
    # ★2026-09-09 无校准门派（天机城等）guard_grid=None → 只 CALL 不兜底
    #   点击（用户定案：不走路直接 CALL），失败留给下一轮重试。
    if guard_grid is None:
        logger.warning("闯关：%s CALL 未中且无校准坐标，不做兜底点击（下轮重试）" % sect)
        return False
    pos = self_world_xy(gateway)
    wx, wy = guard_grid[0] * 20, guard_grid[1] * 20
    if pos:
        dist = ((pos[0] - wx) ** 2 + (pos[1] - wy) ** 2) ** 0.5
        if dist > 200:
            logger.warning("闯关：距护法 %.0fpx 太远且 CALL 未中，兜底点击放弃（下轮重走）" % dist)
            return False
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
        # ---- 2) 关背包 → 点(469,66)走到使者跟前 → 识别使者并点击接任务
        #          （仅新报名时）----
        #   ★2026-09-08 晚用户标定（截图实拍）：旗到长安后左键点 (469,66)
        #   即走到使者跟前；背包先关（旗子通道用完是开着的，开着会挡点击/
        #   误触背包按钮——传送门点成传送按钮同族事故）。到位后识别 npc 表
        #   使者投影点击开对话（使者无标识 CALL 不了，只能点击通道）。
            _bag_ensure_close(gateway, hwnd)
            _wait_move_stop(gateway, max_wait=8.0)   # 旗子落地停稳
            post_click(hwnd, 469 + random.randint(-3, 3),
                       66 + random.randint(-3, 3), gateway=gateway)
            _wait_move_stop(gateway, max_wait=20.0)  # 走到使者跟前
            _sleep(random.uniform(0.5, 0.9))
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
        # ---- 2.5) 摄妖香：报名与续跑通用（★2026-09-08 深夜用户指正：续跑
        #          原来完全跳过摄妖香，跨图走路遇敌）。包有→直接用；没有→买。
        #          25 分钟内已用则跳过，防 run() 反复重入连环消费。----
        _ensure_sheaoxiang(gateway, hwnd, verbose=verbose)
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
            if calib is not None:
                guard_grid, cpx, cgrid, scale = calib
            else:
                # ★2026-09-09 用户定案（天机城实锤）：无校准门派不走路——
                #   落地直接 CALL 护法（CALL 按门派名/护法扫全地图单位，与
                #   位置无关）；弹窗/放马过来与其他门派同款。
                guard_grid = cpx = None
                logger.info("闯关：%s 无校准数据 → 不走路直接 CALL 护法" % sect)
            logger.info("闯关：第%d次考验 → 目标 %s" % (trial, sect))
            # 3a 前置：清残留对话（上一场"未进战中止"可能留下放马过来弹窗，
            #     弹窗开着会挡背包传送——22:07:36 传送失败实证）
            _dismiss_dialog(gateway, hwnd)
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
            if guard_grid is None:
                # ★2026-09-09 用户定案：无校准门派跳过走路段，CALL 前只等停稳
                logger.info("闯关：%s 无校准 → 跳过走路，直接进 CALL" % sect)
            else:
                wx, wy = guard_grid[0] * 20, guard_grid[1] * 20
                _walk_world(gateway, hwnd, wx, wy, timeout=60.0, verbose=verbose)
            # 3c) CALL 护法 → 放马过来
            if not _call_guard_npc(gateway, hwnd, sect, guard_grid, verbose=verbose):
                logger.warning("闯关：CALL 护法失败（%s），中止" % sect)
                break
            _sleep(random.uniform(1.0, 1.5))
            if not _click_dialog_first_row(gateway, hwnd, tag="放马过来",
                                           fixed_rect=_FANGMA_RECT):
                # ★2026-09-08 晚改：对话没弹出也不中止——同"未进战"，转下轮
                # 以任务追踪裁决（追踪=唯一真相，自愈重走）
                logger.warning("闯关：护法对话未弹出（%s），转下轮以任务追踪裁决" % sect)
                _sleep(random.uniform(1.5, 2.5))
                continue
            _mouse_clear(hwnd, gateway)
            # ★自动战斗看护提前到点击后立即拉起（原先等 entered 才启动，
            #   in_battle 漏检时整场战斗无人点「自动」——2026-09-08 深夜实况）
            threading.Thread(target=_battle_auto_kick,
                             args=(hwnd, gateway, 8.0, 8), daemon=True).start()
            # 3d) 等进战（★点击未吃则按标定矩形重点，最多3次）。
            #     ★进战证据二选一：in_battle 三信号（会漏检，天宫实证）
            #     OR「自动」按钮模板命中（按钮已渲染=必在战斗）。
            entered = False
            for attempt in range(3):
                t0 = time.time()
                while time.time() - t0 < 15.0 and not (
                        zhuagui_in_battle(gateway) or _auto_button_visible(hwnd)):
                    _sleep(random.uniform(0.8, 1.2))
                if zhuagui_in_battle(gateway) or _auto_button_visible(hwnd):
                    entered = True
                    break
                rows = _zhongkui_detect_rows(gateway)
                if not rows:
                    break   # 对话没了也没进战：无从再点
                logger.info("闯关：放马过来第%d次点击未生效，按标定矩形重点" % (attempt + 1))
                post_click(hwnd, random.randint(_FANGMA_RECT[0] + 2, _FANGMA_RECT[2] - 2),
                           random.randint(_FANGMA_RECT[1] + 2, _FANGMA_RECT[3] - 2),
                           gateway=gateway)
                _sleep(random.uniform(1.2, 1.5))
            if not entered:
                # ★2026-09-08 晚改：不中止，转下轮以任务追踪裁决（实况：天宫
                # 放马过来实际已进战并打完，in_battle 三信号全程漏检误判未进战
                # →旧逻辑直接 break，卡死在原地不去下个门派）。追踪为唯一真相：
                #   打成了 → 追踪刷新为下个门派，下轮继续；
                #   没打成 → 追踪仍是本门派，下轮重新传送+CALL（自愈）。
                logger.warning("闯关：点放马过来后未进战（%s），转下轮以任务追踪裁决" % sect)
                _sleep(random.uniform(1.5, 2.5))
                continue
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
