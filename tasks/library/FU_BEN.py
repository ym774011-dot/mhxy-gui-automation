# -*- coding: utf-8 -*-
"""FU_BEN.py — 副本自动化（2026-09-16 用户定案 + 实测打通乌鸡副本全流程）。

副本分两类：
  A) 一进就打一场（解放美女 / 车迟？—— 待实测）
  B) 刷怪副本（乌鸡副本）：进场景 → 扫 地图.地图单位 → CALL 每只怪 →
     弹确认对话框 → 点红字首选项 → 进战 → 自动战斗 → 脱战 → 循环直到 0。

★战斗判定（全地图刷怪同款）：zhuagui_in_battle 4 信号（参战单位 + 敌方数量 +
  回合进程 + 自动栏可视），进战即 _battle_auto_kick 点自动。不再依赖 _auto_button_visible。

★乌鸡副本实测打通（2026-09-16 二号美人 3131）：
  阶段1 刷怪：10 只"芭蕉木妖"（CALL→"打得你变回木头"→进战→打完）
  阶段2 找仙人：15 只"热心仙人"（CALL→"多谢仙人相助"→仙人消失→循环）
  通用：CALL 通道 客户端:发送数据(0,3,6,<标识>,1)；红字主块 y305-318 中心(155,312)；
  取消小块 y321-330；hover 变色修复=扫描前 _mouse_clear 移鼠标。

用户定案（2026-09-16）：一个副本一天只能打两次 → 三副本合计 6 次/天。

进入副本矩形（用户实机标定，格式 x0,y0,x1,y1）：
  解放美女 113,338,207,346  宽高(94,8)
  车迟副本 259,340,321,347  宽高(62,7)
  乌鸡副本 357,338,418,348  宽高(61,10)
"""
import random
import time

from tasks.library import ZGUI
from tasks.library.ZGUI import (
    _lua_call, _sleep, logger, post_click, post_right_click,
    zhuagui_in_battle, get_hwnd, _battle_auto_kick, _mouse_clear,
    _panel_pin_defaults, user32, _BATTLE_LATCH, _BATTLE_LATCH_S,
)

# ---- 快捷副本按钮（用户在快捷传送上方标定 271,22,323,33 宽高 52x11）----
_FUBEN_BTN = (271, 22, 323, 33)

# ---- 三副本（顺序=尝试顺序）。key=(显示名, 进入矩形) ----
# rect 为用户实机标定的「进入XX副本」链接真实包围盒。
DUNGEONS = (
    ("解放美女", (113, 338, 207, 346)),   # 宽高 94x8
    ("车迟副本", (259, 340, 321, 347)),   # 宽高 62x7
    ("乌鸡副本", (357, 338, 418, 348)),   # 宽高 61x10
)

# ★用户定案：一个副本一天只能打两次 → 三副本合计 6 次/天。
MAX_RUNS_PER_DAY = 6
MAX_RUNS_PER_DUNGEON = 2

# 红字检测带（副本列表区）。进入矩形 y 都在 338-348，
# 开启行（开始XX副本）在其上方，故向上扩 ~90px 足够覆盖。
_RED_X_LO, _RED_X_HI = 100, 440
_RED_Y_LO, _RED_Y_HI = 250, 360
_RED_PIX = dict(r=110, dg=55, db=55)   # R>110 且 R-G>55 且 R-B>55（同 _zhongkui_detect_rows）
_RED_MIN_C = 10                        # 单行红像素数下限
_RED_MIN_N = 30                        # 块内红像素总数下限
_RED_MERGE_GAP = 2                     # 相邻红行块合并间距（<=2 视为同一行）

# ---- 乌鸡副本（刷怪副本）专属常量 ----
WUJI_MONSTER_NAME = "芭蕉木妖"
WUJI_FIGHT_OPTION = "打得你变回木头"
# ---- 第二阶段：寻找仙人帮助 ----
WUJI_XIANREN_NAME = "热心仙人"            # 仙人地图单位名
WUJI_XIANREN_THANKS = "多谢仙人相助"       # 对话主选项（红字主块）
WUJI_XIANREN_TARGETS = 15                  # 仙人总数
# ---- 第三阶段：CALL国王切图 + 打三妖 ----
WUJI_ENTER_OPTION = "送我进去"             # 国王切图对话选项（红字主块）
WUJI_THREE_YAOS = ("缚仙妖怪", "拘灵妖怪", "囚神妖怪")   # 三妖 npc 名
# ---- 第四阶段：消灭鬼祟小妖 ----
WUJI_GS_NAME = "鬼祟小妖"                 # 鬼祟小妖地图单位名
WUJI_GS_UNDER = 10                        # 剩余数量低于该值即完成本阶段
# ---- 第五阶段：分辨真假乌鸡国王 ----
WUJI_KING_NAME = "乌鸡国王"               # 国王 npc 名（npc 表无标识，走近点击）
WUJI_KING_FIGHT_N = 1
# ---- 进本后打开地图点击乌鸡国王NPC（下一地图入口NPC，界面相对坐标）----
WUJI_WALK_GRID = (430, 330)   # 进本后走位目标（大地图格坐标，乌鸡国王NPC/下一地图入口）
WUJI_MAP_OPEN_VK = 0x09          # Tab：与「门派闯关」开大地图同款
WUJI_MAP_OPEN_WAIT = 1.4         # 开图后等待大地图绘制
WUJI_MAP_CLOSE_WAIT = 1.0        # 点完 NPC 关图后等待                     # 用户定案：只打一个国王即通关         # 任务目标名（LUA 名称字段）
WUJI_MAP_NAMES = ("乌鸡国副本",)        # 场景名（LUA 地图.地图名称）
WUJI_MAP_IDS = (3131,)                  # 地图编号（实测）
WUJI_MAX_TARGETS = 10                   # 任务目标总数（固定 10 只）
# ★用户定案（2026-09-16）：战斗选项固定坐标 (170,312)——红字扫描易误判取消块
_DLG_FIGHT_FX, _DLG_FIGHT_FY = 170, 312
# 弹窗红字块 n 区分（实测）：打得你变回木头 n≈367、取消 n≈42、场景大块 n>2000
_DLG_MAIN_MIN_N = 150                  # 主块（选项1）n 下限
_DLG_CANCEL_MAX_N = 150                # 取消块 n 上限
_DLG_BLOCK_MAX_N = 2000                # 排除场景大合并块
WUJI_DIALOG_X_LO, WUJI_DIALOG_X_HI = 95, 620   # 乌鸡对话框红字扫描 x 带（比列表更宽）
WUJI_DIALOG_Y_LO, WUJI_DIALOG_Y_HI = 255, 425  # y 带（覆盖弹窗内所有红字选项）


def _sw8(gateway):
    """界面数据[8] 本类开关（快捷传送/快捷副本对话框是否打开）。

    ★2026-09-18 统一到 `ZGUI.quick_dialog_on`（ZGUI 现已提供该公共件，
      原注"ZGUI 里没有这个函数"已过时）；读不到 → False。
    """
    try:
        return ZGUI.quick_dialog_on(gateway) is True
    except Exception:
        return False


def _red_rows(hwnd):
    """副本列表区红字行检测（像素法，不依赖 OCR）。

    扫描带 (x100-440, y250-360)，阈值与 ZGUI._zhongkui_detect_rows 同源
    （红字=纯红笔画，R 高、G/B 低）。返回自上而下 [{x0,x1,y0,y1}, ...]。
    检不到（列表未弹/黑屏/被遮挡）返回 []。
    """
    try:
        img, _, _ = ZGUI.grab_client(hwnd)
        px = img.load()
        W, H = img.size
        x_lo, x_hi = _RED_X_LO, min(_RED_X_HI, W - 1)
        y_lo, y_hi = _RED_Y_LO, min(_RED_Y_HI, H - 1)
        if x_hi <= x_lo or y_hi <= y_lo:
            return []
        counts = {}
        for y in range(y_lo, y_hi):
            c = 0
            for x in range(x_lo, x_hi):
                R, G, B = px[x, y]
                if R > _RED_PIX["r"] and (R - G) > _RED_PIX["dg"] \
                        and (R - B) > _RED_PIX["db"]:
                    c += 1
            if c >= _RED_MIN_C:
                counts[y] = c
        blks = []
        cur = None
        for y in sorted(counts):
            if cur and (y - cur["y1"]) <= _RED_MERGE_GAP:
                cur["y1"] = y
                cur["c"] += counts[y]
            else:
                if cur:
                    blks.append(cur)
                cur = {"y0": y, "y1": y, "c": counts[y]}
        if cur:
            blks.append(cur)
        res = []
        for b in blks:
            x0, x1, n = 999, -1, 0
            for y in range(b["y0"], b["y1"] + 1):
                for x in range(x_lo, x_hi):
                    R, G, B = px[x, y]
                    if R > _RED_PIX["r"] and (R - G) > _RED_PIX["dg"] \
                            and (R - B) > _RED_PIX["db"]:
                        x0 = min(x0, x)
                        x1 = max(x1, x)
                        n += 1
            if n >= _RED_MIN_N:
                res.append({"x0": x0, "x1": x1, "y0": b["y0"], "y1": b["y1"]})
        return res
    except Exception as e:
        logger.info("副本：红字检测异常（忽略）: %s" % e)
        return []


def _open_fuben_list(gateway, hwnd, tries=3):
    """直接点「快捷副本」按钮弹出副本列表（★用户定案：不点快捷传送）。

    ★2026-09-16 用户定案：副本入口只点 _FUBEN_BTN(271,22,323,33)，不走快捷传送。
      快捷副本按钮在快捷传送正上方，点它直接展开副本列表。
    返回 True=已点「快捷副本」且列表红字可见。
    """
    try:
        ZGUI._bag_ensure_close(gateway, hwnd)
        _sleep(random.uniform(0.2, 0.35))
    except Exception:
        pass
    for attempt in range(max(1, tries)):
        post_click(hwnd, random.randint(_FUBEN_BTN[0], _FUBEN_BTN[2]),
                   random.randint(_FUBEN_BTN[1], _FUBEN_BTN[3]), gateway=gateway)
        # 列表渲染需要时间，先给 1.0-1.4s
        _sleep(random.uniform(1.0, 1.4))
        rows = _red_rows(hwnd)
        if rows:
            logger.info("副本：快捷副本列表已开（检出 %d 行红字）" % len(rows))
            return True
        logger.info("副本：点快捷副本第%d次未检出列表红字，重试" % (attempt + 1))
        _sleep(random.uniform(0.5, 0.8))
    logger.warning("副本：快捷副本列表未开（红字检测无结果）")
    return False


def _start_row_above(rows, enter_rect):
    """在红字行里取「进入矩形正上方」那一行 = 开启行（y 最小且同列）。

    ★用户定案：开启副本坐标用「对应坐标上面的红色字体自动识别」。
      进入行在开启行下方，故 x 与进入矩形同列、y 更小的最近一行即开启行。
      没有更小 y 的行时返回 None（列表未渲染完/识别不全）。
    """
    ex0, ey0, ex1, = enter_rect[0], enter_rect[1], enter_rect[2]
    cx = (ex0 + ex1) / 2.0
    best = None
    for b in rows:
        # 同列判定：红字行与进入矩形 x 区间有重叠
        if b["x1"] < ex0 - 20 or b["x0"] > ex1 + 20:
            continue
        # 在进入矩形上方（允许 4px 容差）
        if b["y1"] >= ey0 - 4:
            continue
        # 取 y 最大（=最靠近进入行的上方那一行），即"对应坐标上面"的行
        if best is None or b["y0"] > best["y0"]:
            best = b
    if best is None:
        return None
    return best


def _click_start(gateway, hwnd, name, enter_rect, tries=4):
    """点「开始XX副本」（红字识别，取进入矩形上方的红字行顶部条带）。

    返回 True=已点击。识别不到返回 False（该副本本日次数可能已满/未渲染）。
    """
    for attempt in range(max(1, tries)):
        rows = _red_rows(hwnd)
        if rows:
            row = _start_row_above(rows, enter_rect)
            if row is not None:
                post_click(hwnd,
                           random.randint(row["x0"] + 3,
                                          max(row["x0"] + 4, row["x1"] - 3)),
                           random.randint(row["y0"] + 2,
                                          min(row["y0"] + 7, row["y1"])),
                           gateway=gateway)
                logger.info("副本：已点「开始%s副本」红字行 (x%d-%d,y%d-%d)"
                            % (name, row["x0"], row["x1"], row["y0"], row["y1"]))
                _sleep(random.uniform(1.2, 1.5))
                return True
            # 红字行列不匹配：进入矩形上方没检出行（可能只有进入行可见）
            logger.info("副本：%s 进入矩形上方未检出开启红字（第%d次），"
                        "该副本可能已开启/本日次数满" % (name, attempt + 1))
        else:
            logger.info("副本：%s 红字检测无结果（第%d次）" % (name, attempt + 1))
        _sleep(random.uniform(0.5, 0.8))
    return False


def _fuben_cells(gateway):
    """读副本列表 超级文本.显示表 非空单元格。

    返回 [{行,列,内容,回调,x,w}, ...]；坐标字段读不到置 None。
    ★2026-09-17：乌鸡列不再用标定 rect（9864 窗口列漂移误点车迟），
      改由回调 cb=271-1(开始乌鸡副本)/271-2(进入乌鸡副本) 实时定位。
    """
    r = _lua_call(gateway, r"""
local d = tp.主界面 and tp.主界面.界面数据 and tp.主界面.界面数据[8]
local st = d and d.超级文本 and d.超级文本.显示表
if type(st) ~= 'table' then __out = '' return end
local out = {}
for i = 1, 12 do
  local rw = st[i]
  if type(rw) == 'table' then
    for j = 1, 6 do
      local c = rw[j]
      if type(c) == 'table' and tostring(c.内容 or '') ~= '' then
        out[#out+1] = tostring(i) .. '.' .. tostring(j) .. '|' ..
          tostring(c.内容) .. '|' .. tostring(c.回调 or '') .. '|' ..
          tostring(c.x or '') .. '|' .. tostring(c.宽 or '')
      end
    end
  end
end
__out = table.concat(out, ' ;; ')
""", timeout=10.0)
    res = []
    for seg in (r or "").split(" ;; "):
        seg = seg.strip()
        if not seg:
            continue
        parts = seg.split("|")
        if len(parts) >= 3:
            try:
                rc = parts[0].split(".")
                cell = {"行": int(rc[0]), "列": int(rc[1]),
                        "内容": parts[1].strip(), "回调": parts[2],
                        "x": None, "w": None}
                if len(parts) >= 4 and parts[3]:
                    try:
                        cell["x"] = float(parts[3])
                    except Exception:
                        pass
                if len(parts) >= 5 and parts[4]:
                    try:
                        cell["w"] = float(parts[4])
                    except Exception:
                        pass
                res.append(cell)
            except Exception:
                pass
    return res


# 副本列表显示表换算基准（ZGUI 实测：文字区原点 client(100,275)、行高 15px）
_DLG8_ORIGIN = (100, 275)
_DLG8_ROW_H = 15
# ★乌鸡列回调（用户实机 dump）：271-1=开始乌鸡副本、271-2=进入乌鸡副本
_WUJI_CB_START = "271-1"
_WUJI_CB_ENTER = "271-2"


def _wuji_cell_rect(gateway, cb):
    """由显示表定位乌鸡列单元格的绝对点击矩形。

    换算：x0=原点x+cell.x，y=(行-1)*行高+原点y，取行中下部（+4..+12）命中文字。
    读不到（列表未开/字段缺失）返回 None → 调用方回退标定 rect。
    """
    for c in _fuben_cells(gateway):
        if c["回调"].startswith(cb):
            x0 = _DLG8_ORIGIN[0] + (c["x"] if c["x"] is not None else 0)
            x1 = x0 + (c["w"] if c["w"] is not None else 80)
            y0 = _DLG8_ORIGIN[1] + (c["行"] - 1) * _DLG8_ROW_H + 4
            y1 = y0 + 9
            logger.info("副本：显示表定位乌鸡列 回调=%s 行%d 内容=%s rect(%d,%d)-(%d,%d)"
                        % (cb, c["行"], c["内容"], x0, y0, x1, y1))
            return (int(x0), int(y0), int(x1), int(y1))
    return None


def _click_enter(gateway, hwnd, name, rect, tries=2):
    """点「进入XX副本」（用户标定固定矩形内随机点）。返回 True=已点击。"""
    for _try in range(max(1, tries)):
        x = rect[0] + 2 if rect[2] - 2 <= rect[0] + 2 else random.randint(rect[0] + 2, rect[2] - 2)
        y = rect[1] + 2 if rect[3] - 2 <= rect[1] + 2 else random.randint(rect[1] + 2, rect[3] - 2)
        post_click(hwnd, x, y, gateway=gateway)
        logger.info("副本：已点「进入%s副本」矩形 (%d,%d)-(%d,%d)"
                    % (name, rect[0], rect[1], rect[2], rect[3]))
        _sleep(random.uniform(1.4, 1.8))
        return True
    return False


def _wait_enter_battle(gateway, hwnd, max_s=40.0):
    """等进战（全地图刷怪同款：只用 zhuagui_in_battle 4 信号）。

    进战即后台拉起 _battle_auto_kick 点自动战斗。
    返回 True=已进战（已启动自动战斗看护）。
    """
    import threading
    t0 = time.time()
    kicked = False
    while time.time() - t0 < max_s:
        try:
            inb = zhuagui_in_battle(gateway)
        except Exception:
            inb = False
        if inb:
            if not kicked:
                threading.Thread(target=_battle_auto_kick,
                                 args=(hwnd, gateway), daemon=True).start()
                kicked = True
            return True
        _sleep(random.uniform(0.8, 1.2))
    return False


def _wait_out_battle(gateway, max_s=300.0):
    """挂机等战斗结束（全地图刷怪同款：只靠 zhuagui_in_battle）。"""
    t0 = time.time()
    while time.time() - t0 < max_s:
        try:
            if not zhuagui_in_battle(gateway):
                return True
        except Exception:
            return True
        _sleep(random.uniform(1.5, 2.2))
    return False



# ============================================================
# ★2026-09-17 任务感知：先读任务栏，判定是否已有乌鸡国任务
# ============================================================
# 任务栏任务名是「乌鸡国」（不是「乌鸡副本」）；说明含「芭蕉木妖」。
# 一条任务 = 一个副本（一天两次 = 两条任务），故可能同时存在多条。
WUJI_TASK_NAME = "乌鸡国"
WUJI_TASK_KEY = "芭蕉木妖"


def _wuji_task_count(gateway):
    """读 tp.窗口.任务栏.任务，返回乌鸡国任务条数；读不到返回 -1。

    ★任务栏真实路径实测（2026-09-17 真机 5 开）：
      tp.窗口.任务栏.任务[i].{名称,说明}
      e.g. [2] 名称=乌鸡国 说明="消灭场景内的芭蕉木妖，当前还有10只..."
    说明里含 #w/#r/#y 等颜色标记，需 strip 后判关键字。
    """
    try:
        r = _lua_call(gateway, r"""
local w = tp and tp.窗口
local tl = w and w.任务栏
local ts = tl and tl.任务
if type(ts) ~= 'table' then __out = '-1' return end
local n = 0
for i = 1, #ts do
  local t = ts[i]
  if type(t) == 'table' then
    local nm = tostring(t.名称 or '')
    local ds = tostring(t.说明 or '')
    if nm == '__TNAME__' and string.find(ds, '__TKEY__', 1, true) then
      n = n + 1
    end
  end
end
__out = tostring(n)""".replace("__TNAME__", WUJI_TASK_NAME)
                      .replace("__TKEY__", WUJI_TASK_KEY), timeout=8.0)
        return int((r or "-1").strip())
    except Exception as e:
        logger.info("副本：任务栏读取异常（按无任务处理）: %s" % e)
        return -1


def _wuji_task_exists(gateway):
    """是否已有乌鸡国任务（读不到任务栏时返回 False=按无任务走旧流程，不阻塞）。"""
    n = _wuji_task_count(gateway)
    if n > 0:
        logger.info("副本：任务栏已存在 %d 条「%s」任务 → 只进入已有副本，不点开启"
                    % (n, WUJI_TASK_NAME))
        return True
    if n == 0:
        logger.info("副本：任务栏无「%s」任务 → 需新开一个乌鸡副本" % WUJI_TASK_NAME)
    else:
        logger.info("副本：任务栏读取失败 → 回退旧流程（开启后进入）")
    return False


# ============================================================
# 乌鸡副本（刷怪副本）专属函数
# ============================================================

def _current_map_name(gateway):
    """当前地图名（沿用 ZGUI._current_map_name 同款）。"""
    try:
        return _lua_call(gateway, r"""
local t = tp and tp.地图
local n = t and (t.地图名称 or t.名称)
if not n then
  local g = _G and _G.引擎 and _G.引擎.场景
  n = g and (g.地图名称 or g.名称)
end
__out = tostring(n or '')""")
    except Exception:
        return ""


def _scan_map_monsters(gateway, name=None):
    """扫描 tp.地图.地图单位，返回 [{名称, 标识, 造型, id}, ...]。

    name 非空时只返回匹配该名称的单位（乌鸡副本=芭蕉木妖）。
    扫描失败/地图无单位返回 []。
    """
    try:
        src_lua = r"""
local t = tp and tp.地图 and tp.地图.地图单位
local out = ''
if type(t) ~= 'table' then __out = '' return end
for _, v in pairs(t) do
  if type(v) == 'table' then
    local nm = tostring(v.名称 or '')
    if nm == '__TARGET__' then
      out = out .. nm .. '|' .. tostring(v.标识 or '') .. '|'
          .. tostring(v.造型 or '') .. '|' .. tostring(v.id or '') .. ' ;; '
    end
  end
end
__out = out""".replace("__TARGET__", name or "")
        raw = _lua_call(gateway, src_lua, timeout=10.0) or ""
        res = []
        for seg in raw.split(" ;; "):
            seg = seg.strip()
            if not seg or seg == "__TARGET__" or seg == "|":
                continue
            parts = seg.split("|")
            if len(parts) >= 4:
                res.append({"名称": parts[0], "标识": parts[1],
                            "造型": parts[2], "id": parts[3]})
        return res
    except Exception as e:
        logger.info("副本：地图单位扫描异常（忽略）: %s" % e)
        return []


def _call_unit(gateway, gid, hwnd=None, wait_latch=False):
    """CALL 地图单位（客户端:发送数据(0,3,6,<标识>,1)）。

    ★战斗中绝不 CALL：双重确认（zhuagui_in_battle + _BATTLE_LATCH 闩锁）。
    ★CALL 前实时核验目标仍在 地图.地图单位（防 rrvl）。
    返回 True=CALL 已发出；False=被战斗闩锁拦截或目标已消失。
    """
    import time as _t
    _now = _t.time()
    try:
        if zhuagui_in_battle(gateway):
            logger.info("副本：战斗中 → 不对 标识%s 发 CALL" % gid)
            return False
    except Exception:
        pass
    latch_wait = _BATTLE_LATCH_S - (_now - _BATTLE_LATCH.get("ts", 0))
    if latch_wait > 0:
        if not wait_latch:
            logger.info("副本：闩锁期内 → 不对 标识%s 发 CALL" % gid)
            return False
        # ★乌鸡循环：战斗结束 8s 保护期内的下一只 CALL 应等待而非永久跳过，
        #   否则目标被误标 skip、后续“未找到怪”提前退出。
        logger.info("副本：闩锁剩 %.1fs，等待后 CALL %s" % (latch_wait, gid))
        _sleep(min(latch_wait + 0.5, 10.0))
        try:
            if zhuagui_in_battle(gateway):
                logger.info("副本：等待后战斗中 → 放弃 CALL %s" % gid)
                return False
        except Exception:
            pass
    # 实时核验目标仍在地图上
    try:
        _st = _lua_call(gateway, r"""
local t = tp and tp.地图 and tp.地图.地图单位
if type(t) ~= 'table' then __out = '1' return end
for _, v in pairs(t) do
  if type(v) == 'table' and tostring(v.标识 or '') == '__GID__' then
    __out = '1' return
  end
end
__out = '0'""".replace("__GID__", gid), timeout=8.0)
        if (_st or "").strip() == "0":
            logger.info("副本：标识%s 已不在地图 → 跳过" % gid)
            return False
    except Exception:
        pass
    try:
        _lua_call(gateway, "客户端:发送数据(0,3,6,%s,1)" % gid, timeout=8.0)
        logger.info("副本：CALL 标识%s" % gid)
        return True
    except Exception as e:
        logger.warning("副本：CALL 标识%s 异常: %s" % (gid, e))
        return False


def _dialog_red_first_row(hwnd):
    """扫描当前对话框内红字选项行（乌鸡副本专用带：y255-425, x95-620）。

    返回自上而下 [{x0,x1,y0,y1}, ...]，检不到返回 []。
    ★实测 2026-09-16："打得你变回木头" y305-318(367px) "取消" y321-330(84px)
    —— 两行可能因间距 ≤2px 合并成一个块；取块顶部 +7px 即命中第一选项。
    """
    try:
        img, _, _ = ZGUI.grab_client(hwnd)
        px = img.load()
        W, H = img.size
        x_lo, x_hi = WUJI_DIALOG_X_LO, min(WUJI_DIALOG_X_HI, W - 1)
        y_lo, y_hi = WUJI_DIALOG_Y_LO, min(WUJI_DIALOG_Y_HI, H - 1)
        if x_hi <= x_lo or y_hi <= y_lo:
            return []
        counts = {}
        for y in range(y_lo, y_hi):
            c = 0
            for x in range(x_lo, x_hi):
                R, G, B = px[x, y][:3]
                if R > 110 and (R - G) > 55 and (R - B) > 55:
                    c += 1
            if c >= 8:
                counts[y] = c
        blks = []
        cur = None
        for y in sorted(counts):
            if cur and (y - cur["y1"]) <= 2:
                cur["y1"] = y
                cur["c"] += counts[y]
            else:
                if cur:
                    blks.append(cur)
                cur = {"y0": y, "y1": y, "c": counts[y]}
        if cur:
            blks.append(cur)
        res = []
        for b in blks:
            x0, x1, n = 9999, -1, 0
            for y in range(b["y0"], b["y1"] + 1):
                for x in range(x_lo, x_hi):
                    R, G, B = px[x, y][:3]
                    if R > 110 and (R - G) > 55 and (R - B) > 55:
                        x0 = min(x0, x)
                        x1 = max(x1, x)
                        n += 1
            if n >= 20:
                res.append({"x0": x0, "x1": x1, "y0": b["y0"], "y1": b["y1"], "n": n})
        return res
    except Exception as e:
        logger.info("副本：对话框红字检测异常（忽略）: %s" % e)
        return []


def _dialog_rows(gateway):
    """读界面[8] 显示表非空单元格。返回 [{行,列,内容,回调}, ...]。"""
    r = _lua_call(gateway, r"""
local d = tp.主界面 and tp.主界面.界面数据 and tp.主界面.界面数据[8]
local st = d and d.超级文本
local rows = st and st.显示表
if type(rows) ~= 'table' then __out = '' return end
local out = {}
for i = 1, 12 do
  local rw = rows[i]
  if type(rw) == 'table' then
    for j = 1, 6 do
      local c = rw[j]
      if type(c) == 'table' and tostring(c.内容 or '') ~= '' then
        out[#out+1] = tostring(i) .. '.' .. tostring(j) .. '|' ..
          tostring(c.内容) .. '|' .. tostring(c.回调 or '')
      end
    end
  end
end
__out = table.concat(out, ' ;; ')
""", timeout=10.0)
    res = []
    for seg in (r or "").split(" ;; "):
        seg = seg.strip()
        if not seg:
            continue
        parts = seg.split("|")
        if len(parts) >= 3:
            try:
                row_col = parts[0].split(".")
                res.append({"行": int(row_col[0]), "列": int(row_col[1]),
                            "内容": parts[1].strip(), "回调": parts[2]})
            except Exception:
                pass
    return res


def _dialog_has_option(gateway, content, cb=None):
    """显示表是否有指定选项行。cb 给定则校验回调一致（确认是本次 CALL 的弹窗）。"""
    for rw in _dialog_rows(gateway):
        if rw["内容"] == content:
            if cb is None or rw["回调"] == str(cb):
                return True
    return False


def _dialog_fight_option_cb(gateway):
    """读「打得你变回木头」行的回调（=本次 CALL 的 gid），读不到返回 None。"""
    for rw in _dialog_rows(gateway):
        if rw["内容"] == WUJI_FIGHT_OPTION:
            return rw["回调"]
    return None


def _dismiss_dialog(gateway, hwnd):
    """关闭残留弹窗（用户定案：ESC 无效；只能点「取消」或右键弹窗面板内）。

    ★实测「取消」红字 y321-330 x114-139；错误关闭会点中别的选项/场景，
      故先用红字精确找取消行，检不到退回面板内右键（弹窗面板约 x90-628 y250-429）。
    返回 True=已关（_sw8 == False）。
    """
    if not _sw8(gateway):
        return True
    # ★hover 修复：先移鼠标，避免选项被悬停变色导致扫不全
    try:
        _mouse_clear(hwnd, gateway)
        _sleep(random.uniform(0.25, 0.4))
    except Exception:
        pass
    rows = _dialog_red_first_row(hwnd)
    # ★取消块 = n<150 的小块（实测 n≈42）；主块(n≈367)不算，避免误点进战斗
    cancel = [r for r in rows if 30 <= r.get("n", 0) <= _DLG_CANCEL_MAX_N]
    if cancel:
        c = cancel[0]
        post_click(hwnd, (c["x0"] + c["x1"]) // 2 + random.randint(-3, 3),
                   c["y0"] + 7 + random.randint(-2, 2), gateway=gateway)
        logger.info("副本：点「取消」红字块 (x%d-%d,y%d-%d,n=%d)" %
                    (c["x0"], c["x1"], c["y0"], c["y1"], c.get("n", 0)))
    else:
        # 无取消块：面板内右键（右上空白区）
        post_right_click(hwnd, random.randint(500, 580),
                         random.randint(270, 295), gateway=gateway)
        logger.info("副本：无取消块，右键弹窗面板右上空白")
    _sleep(random.uniform(0.8, 1.2))
    closed = not _sw8(gateway)
    if not closed:
        logger.warning("副本：弹窗关闭失败（取消/右键未生效）")
    return closed


def _wait_dialog_option(gateway, cb, max_s=4.0):
    """等本次 CALL 的弹窗选项出现（显示表「打得你变回木头」且回调==cb）。

    返回 True=本次 CALL 弹窗已就绪。
    """
    import time as _t
    t0 = _t.time()
    while _t.time() - t0 < max_s:
        try:
            if _dialog_has_option(gateway, WUJI_FIGHT_OPTION, cb=cb):
                return True
        except Exception:
            pass
        _sleep(0.3)
    return False


def _wait_dialog_open(gateway, max_s=3.0):
    """等对话框弹出（_sw8 == True）。返回 True=已弹。"""
    import time as _t
    t0 = _t.time()
    while _t.time() - t0 < max_s:
        try:
            if _sw8(gateway):
                return True
        except Exception:
            pass
        _sleep(0.3)
    return False


def _click_dialog_first_red(gateway, hwnd, tries=3, cb=None):
    """点「打得你变回木头」（红字块1，实测 y305-318 x114-210 → 中心(162,312)）。

    ★用户定案：坐标用红字块1（y0+7），不能用背景 by+7 推算（by 会漂移到 320）。
    ★前置：CALL 后等弹窗选项出现（显示表 cb==目标 gid），避免点场景红字。
    返回 True=已点且弹窗被接受（sw8 变 false 或进战）；False=未检出/未生效。
    """
    # 前置：等弹窗已开（sw8=true）。★不再校验选项文字/回调——
    #   不同目标选项文字不同（芭蕉木妖=打得你变回木头/鬼祟小妖=做你的春秋大梦去），
    #   文字匹配会误判「CALL 未生效」→ 点取消死循环（2026-09-16 用户实锤）。
    if not _wait_dialog_open(gateway, max_s=4.0):
        logger.info("副本：CALL 后弹窗未出现（目标被占用或 CALL 未生效）")
        return False
    for attempt in range(max(1, tries)):
        # ★用户定案：首选固定坐标 (170,312) 点战斗选项，不扫红字（防误点取消块）
        post_click(hwnd, _DLG_FIGHT_FX + random.randint(-3, 3),
                   _DLG_FIGHT_FY + random.randint(-2, 2), gateway=gateway)
        logger.info("副本：点战斗选项固定坐标 (%d,%d)" % (_DLG_FIGHT_FX, _DLG_FIGHT_FY))
        _sleep(random.uniform(0.6, 1.0))
        try:
            if not _sw8(gateway) or zhuagui_in_battle(gateway):
                return True
        except Exception:
            pass
        # ★兜底：红字主块扫描（固定坐标点击未生效时用）
        logger.info("副本：固定坐标点击未接受（sw8=%s），红字扫描兜底" % _sw8(gateway))
        try:
            _mouse_clear(hwnd, gateway)
            _sleep(random.uniform(0.25, 0.4))
        except Exception:
            pass
        rows = _dialog_red_first_row(hwnd)
        main = [r for r in rows if _DLG_MAIN_MIN_N <= r.get("n", 0) <= _DLG_BLOCK_MAX_N]
        if main:
            row = main[0]
            cx = (row["x0"] + row["x1"]) // 2
            cy = row["y0"] + 7
            post_click(hwnd, cx + random.randint(-3, 3),
                       cy + random.randint(-2, 2), gateway=gateway)
            logger.info("副本：兜底点主块 (%d,%d) y%d-%d n=%d"
                        % (cx, cy, row["y0"], row["y1"], row.get("n", 0)))
            _sleep(random.uniform(0.6, 1.0))
            try:
                if not _sw8(gateway) or zhuagui_in_battle(gateway):
                    return True
            except Exception:
                pass
        # 都没生效 → 下一轮重试（弹窗常驻，等重绘）
        _sleep(random.uniform(0.5, 0.8))
    return False


def _wuji_walk_to_map_point(gateway, hwnd, grid=(430, 330), arrive_wait=8.0,
                            verbose=True):
    """★用户定案（2026-09-17）：进副本后 打开地图(Tab) → 在界面上点 (430,330) → 关图，
    人物自己寻路走过去。

    ★坐标说明：(430,330) 就是**游戏界面的坐标**（点下去的位置），
      不做世界坐标换算、不做到达判定。点完等 arrive_wait 秒让人物走。
    返回 True=已发出走位指令（不保证一定到位）。
    """
    gx, gy = grid
    if gx is None or gy is None:
        logger.warning("副本：走位坐标未配置，跳过")
        return False
    logger.info("副本：走位 → 开地图点界面坐标 (%d,%d)" % (gx, gy))
    try:
        # 1) Tab 开大地图
        user32.PostMessageW(hwnd, 0x0100, WUJI_MAP_OPEN_VK, 0)
        _sleep(0.05)
        user32.PostMessageW(hwnd, 0x0101, WUJI_MAP_OPEN_VK, 0xC0000000)
        _sleep(random.uniform(WUJI_MAP_OPEN_WAIT * 0.85, WUJI_MAP_OPEN_WAIT * 1.15))
        # 2) 点界面坐标
        post_click(hwnd, gx + random.randint(-2, 2), gy + random.randint(-2, 2),
                   gateway=gateway)
        _sleep(random.uniform(0.7, 1.0))
        # 3) Tab 关大地图
        user32.PostMessageW(hwnd, 0x0100, WUJI_MAP_OPEN_VK, 0)
        _sleep(0.05)
        user32.PostMessageW(hwnd, 0x0101, WUJI_MAP_OPEN_VK, 0xC0000000)
        _sleep(random.uniform(WUJI_MAP_CLOSE_WAIT * 0.8, WUJI_MAP_CLOSE_WAIT * 1.1))
        # 4) 等人自己走过去
        _sleep(float(arrive_wait))
        if verbose:
            logger.info("副本：走位指令已发出，等待 %.1fs 后继续" % float(arrive_wait))
        return True
    except Exception as e:
        logger.warning("副本：走位异常（不阻断）: %s" % e)
        return False


def _wuji_king_xy(gateway):
    """地图上「乌鸡国王」NPC 坐标 (x,y)；没看到返回 None。"""
    try:
        kx, ky = _scanned_npc_xy(gateway, (WUJI_KING_NAME,))
    except Exception:
        return None
    if kx is None:
        return None
    return (kx, ky)


def _wuji_king_visible(gateway):
    """★到位判定（用户定案 2026-09-17）：地图上能找到「乌鸡国王」NPC 就是已到位。"""
    k = _wuji_king_xy(gateway)
    if k is None:
        return False
    logger.info("副本：已到位 —— 地图上找到「%s」(%s)" % (WUJI_KING_NAME, (int(k[0]), int(k[1]))))
    return True


def _wuji_run(gateway, hwnd):
    """乌鸡副本专属循环（刷 10 只芭蕉木妖，CALL → 点确认 → 自动战斗）。

    流程（每只）：
      扫怪 → _call_unit(CALL, wait_latch=True) → 等弹窗(显示表 cb==gid) → 点红字块1
      → 等进战（全地图刷怪同款 zhuagui_in_battle）→ 自动战斗 → 等脱战。
    ★CALL 不走近目标（用户确认全天可 CALL）。
    ★战斗结束 8s 闩锁期：wait_latch 等待过期再 CALL，避免目标被误 skip。
    ★攻击前弹窗若残留旧目标（cb 不匹配）→ 点取消收掉再重来。
    返回 True=全部打完；False=中途异常/无怪可打。
    """
    # 场景校验
    mname = _current_map_name(gateway)
    if mname not in WUJI_MAP_NAMES:
        logger.warning("副本：当前非乌鸡副本场景（%s），无法执行乌鸡循环" % mname)
        return False
    # ★刚进副本立刻：打开地图(Tab) → 点界面坐标 (430,330) 走位
    # ★到位判定 = 地图上能看到「乌鸡国王」NPC；没到就再走一次（最多 4 次）
    for _try in range(4):
        _wuji_walk_to_map_point(gateway, hwnd, grid=WUJI_WALK_GRID)
        if _wuji_king_visible(gateway):
            logger.info("副本：走位到位（第%d次），继续后续流程" % (_try + 1))
            break
        logger.info("副本：没看到国王，再走一次（已试 %d 次）" % (_try + 1))
    else:
        logger.warning("副本：多次走位仍未见到国王 NPC（不阻断，继续后续）")
    killed = 0
    skip_gids = {}   # 本轮已打过的怪标识（防重 CALL）
    while killed < WUJI_MAX_TARGETS:
        try:
            if zhuagui_in_battle(gateway):
                logger.info("副本：战斗中，等脱战再续")
                _wait_out_battle(gateway, max_s=60.0)
                _sleep(random.uniform(1.0, 1.5))
                continue
        except Exception:
            pass
        # 进下一只前若有残留弹窗，先收掉（防止弹窗挡住后续 CALL）
        if _sw8(gateway) and _dialog_fight_option_cb(gateway) is None:
            _dismiss_dialog(gateway, hwnd)
        monsters = _scan_map_monsters(gateway, WUJI_MONSTER_NAME)
        alive = [m for m in monsters if m["标识"] not in skip_gids]
        if not alive:
            logger.info("副本：未找到 %s（已打 %d/%d），退出循环"
                        % (WUJI_MONSTER_NAME, killed, WUJI_MAX_TARGETS))
            break
        target = alive[0]
        gid = target["标识"]
        logger.info("副本：CALL %s 标识=%s 剩余%d只"
                    % (WUJI_MONSTER_NAME, gid, WUJI_MAX_TARGETS - killed))
        if not _call_unit(gateway, gid, hwnd=hwnd, wait_latch=True):
            # 闩锁等待后仍失败（战斗中/消失）：不永久跳过，稍等重试同一只
            logger.info("副本：%s 标识=%s CALL 未发出，暂缓重试" % (WUJI_MONSTER_NAME, gid))
            _sleep(random.uniform(1.0, 1.6))
            continue
        _sleep(random.uniform(0.5, 0.9))
        # 点「打得你变回木头」（含弹窗 cb 校验 + 后置生效校验）
        if not _click_dialog_first_red(gateway, hwnd, tries=3, cb=gid):
            logger.warning("副本：%s 标识=%s 对话未点成功" % (WUJI_MONSTER_NAME, gid))
            skip_gids[gid] = time.time()
            # 若弹窗残留，收掉
            if _sw8(gateway):
                _dismiss_dialog(gateway, hwnd)
            continue
        # 等进战（全地图刷怪同款）
        if not _wait_enter_battle(gateway, hwnd, max_s=15.0):
            logger.warning("副本：%s 标识=%s 点击后未进战" % (WUJI_MONSTER_NAME, gid))
            skip_gids[gid] = time.time()
            if _sw8(gateway):
                _dismiss_dialog(gateway, hwnd)
            continue
        # 等脱战
        _wait_out_battle(gateway, max_s=120.0)
        killed += 1
        skip_gids[gid] = time.time()
        logger.info("副本：%s 标识=%s 打完 累计 %d/%d"
                    % (WUJI_MONSTER_NAME, gid, killed, WUJI_MAX_TARGETS))
        _sleep(random.uniform(1.0, 1.8))
    logger.info("副本：乌鸡副本循环结束，共打 %d/%d 只 %s"
                % (killed, WUJI_MAX_TARGETS, WUJI_MONSTER_NAME))
    return killed >= WUJI_MAX_TARGETS

def _xianren_run(gateway, hwnd):
    """乌鸡副本第二阶段：寻找 15 个热心仙人帮助。

    流程（每个）：CALL 仙人 → 等弹窗（对话人物=热心仙人）→ 移鼠标+扫红字主块
    → 点「多谢仙人相助」→ 弹窗关 → 地图单位-1。循环直到地图无仙人。
    返回 True=全部送完；False=中途异常。
    """
    # 场景校验
    if _current_map_name(gateway) not in WUJI_MAP_NAMES:
        logger.warning("副本：当前非乌鸡副本场景，无法执行仙人阶段")
        return False
    helped = 0
    skip_gids = {}
    while True:
        try:
            if zhuagui_in_battle(gateway):
                logger.info("副本：战斗中，等脱战再续")
                _wait_out_battle(gateway, max_s=60.0)
                _sleep(random.uniform(1.0, 1.5))
                continue
        except Exception:
            pass
        # 残留弹窗收掉
        if _sw8(gateway):
            _dismiss_dialog(gateway, hwnd)
        xrs = _scan_map_monsters(gateway, WUJI_XIANREN_NAME)
        alive = [m for m in xrs if m["标识"] not in skip_gids]
        if not alive:
            logger.info("副本：地图无 %s（已助 %d/%d），退出" %
                        (WUJI_XIANREN_NAME, helped, WUJI_XIANREN_TARGETS))
            break
        gid = alive[0]["标识"]
        logger.info("副本：CALL %s 标识=%s 剩%d只" %
                    (WUJI_XIANREN_NAME, gid, len(alive)))
        if not _call_unit(gateway, gid, hwnd=hwnd, wait_latch=True):
            _sleep(random.uniform(1.0, 1.6))
            continue
        _sleep(random.uniform(0.5, 0.9))
        # 等弹窗确认是仙人对话（对话框人物=热心仙人）
        if not _wait_xianren_dialog(gateway, gid, max_s=4.0):
            logger.warning("副本：%s 标识=%s 对话未弹出/不匹配" %
                           (WUJI_XIANREN_NAME, gid))
            skip_gids[gid] = time.time()
            if _sw8(gateway):
                _dismiss_dialog(gateway, hwnd)
            continue
        # 点「多谢仙人相助」（红字主块）
        if not _click_xianren_thanks(gateway, hwnd, gid, tries=3):
            logger.warning("副本：%s 标识=%s 多谢未点成功" % (WUJI_XIANREN_NAME, gid))
            skip_gids[gid] = time.time()
            continue
        helped += 1
        skip_gids[gid] = time.time()
        logger.info("副本：%s 标识=%s 已相助 累计 %d/%d" %
                    (WUJI_XIANREN_NAME, gid, helped, WUJI_XIANREN_TARGETS))
        _sleep(random.uniform(1.0, 1.8))
    logger.info("副本：仙人阶段结束，共帮助 %d/%d" % (helped, WUJI_XIANREN_TARGETS))
    return helped >= WUJI_XIANREN_TARGETS


def _gs_count(gateway):
    """读当前鬼祟小妖数量（地图单位表）。失败返回 -1。"""
    try:
        r = _lua_call(gateway, r"""
local t = tp and tp.地图 and tp.地图.地图单位
local n = 0
if type(t) == 'table' then
  for _, v in pairs(t) do
    if type(v) == 'table' and tostring(v.名称) == '__GS__' then n = n + 1 end
  end
end
__out = tostring(n)""".replace("__GS__", WUJI_GS_NAME), timeout=8.0)
        return int((r or "0").strip())
    except Exception:
        return -1


def _scanned_npc_xy(gateway, names):
    """扫 tp.地图.npc 表，返回 [(名称, x, y), ...] 匹配 names（名称元组）。"""
    names = list(names)
    try:
        r = _lua_call(gateway, r"""
local n = tp and tp.地图 and tp.地图.npc
local out = ''
if type(n) == 'table' then
  for k, v in pairs(n) do
    if type(v) == 'table' then
      local nm = tostring(v.名称 or '')
      local hit = false
      for _, want in ipairs({__NAMES__}) do
        if nm == want then hit = true break end
      end
      if hit then
        out = out .. nm .. '|' .. tostring(v.x) .. '|' .. tostring(v.y) .. ' ;; '
      end
    end
  end
end
__out = out""".replace("__NAMES__", ",".join('"%s"' % nm for nm in names)), timeout=10.0)
        res = []
        for seg in (r or "").split(" ;; "):
            seg = seg.strip()
            if not seg:
                continue
            parts = seg.split("|")
            if len(parts) >= 3:
                try:
                    res.append((parts[0], float(parts[1]), float(parts[2])))
                except Exception:
                    pass
        return res
    except Exception as e:
        logger.info("副本：npc 扫描异常（忽略）: %s" % e)
        return []


def _wuji_enter_palace(gateway, hwnd):
    """乌鸡副本第三步：点「乌鸡国王」→ 弹窗「送我进去」→ 切图到 3132。

    ★用户定案：地图上能看到国王 NPC 即表示已到位，直接开始后续。
    ★坐标修正：屏幕偏移 s.xy（约 -1740,-738）；客户区 800x600。
      国王世界坐标 (2319,1560) → 客户区 (578,822) 已超出画面(y>600)，
      必须 **clamp 到画面内** 才点得到，否则弹窗永不出现。
    返回 True=已切图；False=失败。
    """
    import math
    CLW, CLH = 800, 600
    kings = _scanned_npc_xy(gateway, (WUJI_KING_NAME,))
    if not kings:
        logger.warning("副本：未找到 %s" % WUJI_KING_NAME)
        return False
    kx, ky = kings[0][1], kings[0][2]
    logger.info("副本：国王 NPC @世界(%.0f,%.0f)" % (kx, ky))

    def _self_xy():
        try:
            pr = _lua_call(gateway, r"""
local s = tp.屏幕
__out = tostring(s.主角 and s.主角.xy and s.主角.xy.x) .. ',' .. tostring(s.主角 and s.主角.xy and s.主角.xy.y)""",
                           timeout=8.0)
            px, py = [float(v) for v in pr.split(",")]
            return (px, py)
        except Exception:
            return None

    def _screen_off():
        try:
            oru = _lua_call(gateway, r"""
local s = tp.屏幕
__out = tostring(s.xy and s.xy.x) .. ',' .. tostring(s.xy and s.xy.y)""", timeout=8.0)
            oxo, oyo = [float(v) for v in oru.split(",")]
            return (oxo, oyo)
        except Exception:
            return (0.0, 0.0)

    def _click_king():
        oxo, oyo = _screen_off()
        cx = int(round(kx + oxo))
        cy = int(round(ky + oyo))
        cx = max(40, min(CLW - 40, cx))
        cy = max(40, min(CLH - 40, cy))
        logger.info("副本：点国王 世界→客户区 (%d,%d)（clamp 后）" % (cx, cy))
        post_click(hwnd, cx + random.randint(-4, 4), cy + random.randint(-4, 4),
                   gateway=gateway)

    # 1) 走近国王（直到距离<60，最多 45s）
    t0 = time.time()
    last_move = time.time()
    while time.time() - t0 < 45.0:
        pos = _self_xy()
        if pos:
            d = math.hypot(pos[0] - kx, pos[1] - ky)
            if d < 60:
                logger.info("副本：已走到国王旁（距 %.0f）" % d)
                break
            if d < 700:
                _click_king()
                _sleep(random.uniform(0.8, 1.2))
                continue
        if time.time() - last_move > 4.0:
            _click_king()
            last_move = time.time()
            _sleep(random.uniform(1.5, 2.2))
            continue
        _sleep(random.uniform(0.6, 1.0))

    # 2) 连点国王开弹窗（clamp 后的坐标，确保在画面内）
    opened = False
    for ctry in range(10):
        _click_king()
        _sleep(1.1)
        if _sw8(gateway):
            logger.info("副本：国王弹窗已出现（第%d次点击）" % (ctry + 1))
            opened = True
            break
    if not opened:
        logger.warning("副本：国王弹窗未出现")
        return False

    # 3) 点「送我进去」（红字主块）
    _click_dialog_first_red(gateway, hwnd, tries=3)
    _sleep(random.uniform(1.5, 2.5))

    # 4) 等切图 3132（三妖 npc 出现）
    t_end = time.time() + 20.0
    while time.time() < t_end:
        yaos = _scanned_npc_xy(gateway, WUJI_THREE_YAOS)
        if len(yaos) >= 3:
            logger.info("副本：已切图3132（三妖 npc x%d）" % len(yaos))
            return True
        _sleep(1.0)
    logger.warning("副本：切图后三妖未出现（当前地图=%s）" % _current_map_name(gateway))
    return False


def _wuji_three_yao_run(gateway, hwnd):
    """乌鸡副本第四步：反复打拘灵/囚神/缚仙三妖（npc 无标识，走近点击）。

    三妖各打一场（用户定案：只能打一次，打完换下一只）。
    流程（每只）：扫 npc → 选最近的 → 走近(距<60) → 连点开弹窗 → 点战斗选项
    （固定坐标兜底红字扫描）→ 自动战斗 → 等脱战 → 下一只。
    返回 True=三只都打过。
    """
    import math
    for nm in WUJI_THREE_YAOS:
        try:
            if zhuagui_in_battle(gateway):
                _wait_out_battle(gateway, max_s=180.0)
                _sleep(random.uniform(1.0, 1.5))
        except Exception:
            pass
        if _sw8(gateway):
            _dismiss_dialog(gateway, hwnd)
        # 找该妖
        target = None
        for _t in range(6):
            ys = _scanned_npc_xy(gateway, (nm,))
            if ys:
                # 用第一只（一般情况下就一只）
                target = ys[0]
                break
            _sleep(1.0)
        if target is None:
            logger.warning("副本：未找到 %s（可能已打完？）" % nm)
            continue
        _, kx, ky = target
        logger.info("副本：打 %s @(%.0f,%.0f)" % (nm, kx, ky))
        # 走近
        t0 = __import__('time').time()
        # ★2026-09-18 修复 NameError：原来只初始化了 last_move/fix，漏了 last_xy ——
        #   1181 行 `if last_xy:` 在首轮就抛 NameError（"位置修正"整条路一跑就崩）。
        #   与同文件另一处"走近"循环的写法保持一致：last_xy, last_move, fix = None, t0, 0
        last_xy, last_move, fix = None, t0, 0
        while __import__('time').time() - t0 < 60.0:
            try:
                pr = _lua_call(gateway, r"""
local s = tp.屏幕
__out = tostring(s.主角 and s.主角.xy and s.主角.xy.x) .. ',' .. tostring(s.主角 and s.主角.xy and s.主角.xy.y)""", timeout=8.0)
                px, py = [float(v) for v in pr.split(",")]
                d = math.hypot(px-kx, py-ky)
                if d < 60:
                    break
                if d < 600:
                    oru = _lua_call(gateway, r"""
local s = tp.屏幕
__out = tostring(s.xy and s.xy.x) .. ',' .. tostring(s.xy and s.xy.y)""", timeout=8.0)
                    oxo, oyo = [float(v) for v in oru.split(",")]
                    post_click(hwnd, int(kx+oxo), int(ky+oyo), gateway=gateway)
                    _sleep(random.uniform(0.8, 1.2))
                    last_move = __import__('time').time()
                    continue
                if last_xy:
                    mv = abs(px - last_xy[0]) + abs(py - last_xy[1])
                    if mv >= 5:
                        last_move = __import__('time').time()
                last_xy = (px, py)
            except Exception:
                pass
            if __import__('time').time() - last_move > 5.0:
                if fix >= 4:
                    break
                oru = _lua_call(gateway, r"""
local s = tp.屏幕
__out = tostring(s.xy and s.xy.x) .. ',' .. tostring(s.xy and s.xy.y)""", timeout=8.0)
                try:
                    oxo, oyo = [float(v) for v in oru.split(",")]
                    cx, cy = max(60, min(740, int(kx+oxo))), max(60, min(540, int(ky+oyo)))
                except Exception:
                    cx, cy = 400, 300
                post_click(hwnd, cx, cy, gateway=gateway)
                fix += 1
                last_move = __import__('time').time()
                _sleep(random.uniform(2.0, 2.8))
                continue
            _sleep(random.uniform(0.8, 1.2))
        # 连点开弹窗
        for ctry in range(8):
            oru = _lua_call(gateway, r"""
local s = tp.屏幕
__out = tostring(s.xy and s.xy.x) .. ',' .. tostring(s.xy and s.xy.y)""", timeout=8.0)
            try:
                oxo, oyo = [float(v) for v in oru.split(",")]
                px, py = int(kx+oxo), int(ky+oyo)
            except Exception:
                px, py = 400, 300
            post_click(hwnd, px + random.randint(-4, 4), py + random.randint(-4, 4), gateway=gateway)
            _sleep(1.2)
            if _sw8(gateway) or zhuagui_in_battle(gateway):
                logger.info("副本：%s 弹窗/进战（第%d次点击）" % (nm, ctry+1))
                break
        # 弹窗 → 点战斗
        if _sw8(gateway) and not zhuagui_in_battle(gateway):
            _click_dialog_first_red(gateway, hwnd, tries=3)
        # 进战 → 自动战斗打完
        if zhuagui_in_battle(gateway):
            _wait_enter_battle(gateway, hwnd, max_s=10.0)
            _wait_out_battle(gateway, max_s=300.0)
            logger.info("副本：%s 打完" % nm)
            _sleep(random.uniform(1.0, 1.8))
        else:
            logger.warning("副本：%s 未进战" % nm)
    logger.info("副本：三妖阶段完成")
    return True


def _wuji_gs_run(gateway, hwnd, min_under=WUJI_GS_UNDER, max_battles=40):
    """乌鸡副本第四阶段：消灭鬼祟小妖直到剩余 < min_under 只。

    流程（每只）：扫地图单位(名称=鬼祟小妖) → CALL(标识) → 等弹窗(sw8=true)
    → 移鼠标扫红字主块 → 点战斗选项 → 等进战 → 自动战斗 → 等脱战。
    ★2026-09-16 修复：_click_dialog_first_red 不再传 cb（文字匹配会误判）。
    返回 True=已打到剩余<阈值；False=超时/异常。
    """
    for _ in range(max_battles):
        try:
            if zhuagui_in_battle(gateway):
                _wait_out_battle(gateway, max_s=120.0)
                _sleep(random.uniform(1.0, 1.5))
                continue
        except Exception:
            pass
        # 残留弹窗收掉
        if _sw8(gateway):
            _dismiss_dialog(gateway, hwnd)
        monsters = _scan_map_monsters(gateway, WUJI_GS_NAME)
        if not monsters:
            # 地图上没怪 → 可能打完了/刷新延迟
            left = _gs_count(gateway)
            if 0 <= left < min_under:
                logger.info("副本：%s 剩余 %d（<%d），本阶段完成" %
                            (WUJI_GS_NAME, left, min_under))
                return True
            logger.info("副本：未扫到 %s（left=%d），等待刷新" % (WUJI_GS_NAME, left))
            _sleep(random.uniform(1.5, 2.5))
            continue
        gid = monsters[0]["标识"]
        logger.info("副本：CALL %s 标识=%s 剩余%d只" %
                    (WUJI_GS_NAME, gid, len(monsters)))
        if not _call_unit(gateway, gid, hwnd=hwnd, wait_latch=True):
            _sleep(random.uniform(1.0, 1.6))
            continue
        _sleep(random.uniform(0.4, 0.7))
        if not _click_dialog_first_red(gateway, hwnd, tries=3):  # ★不传 cb
            logger.warning("副本：%s 标识=%s 对话未点成功" % (WUJI_GS_NAME, gid))
            if _sw8(gateway):
                _dismiss_dialog(gateway, hwnd)
            continue
        if not _wait_enter_battle(gateway, hwnd, max_s=15.0):
            logger.warning("副本：%s 标识=%s 点击后未进战" % (WUJI_GS_NAME, gid))
            if _sw8(gateway):
                _dismiss_dialog(gateway, hwnd)
            continue
        _wait_out_battle(gateway, max_s=240.0)
        left = _gs_count(gateway)
        logger.info("副本：%s 标识=%s 打完 剩余%d（目标< %d）" %
                    (WUJI_GS_NAME, gid, left, min_under))
        if 0 <= left < min_under:
            logger.info("副本：%s 剩余 %d，本阶段完成" % (WUJI_GS_NAME, left))
            return True
        _sleep(random.uniform(0.8, 1.2))
    logger.warning("副本：%s 达到战斗上限未完成" % WUJI_GS_NAME)
    return False


def _wuji_king_run(gateway, hwnd):
    """乌鸡副本第五阶段：分辨真假国王（走近点击 → 只打一个 → 通关）。

    国王在 npc 表（无标识，CALL 包不可用——CALL 4/5 实测打到残留「请勿扰」）。
    流程：扫 npc 表找国王坐标 → 走至(距<60) → 连点身体开弹窗 →
    红字主块点战斗 → 自动战斗 → 只打一场返回。
    返回 True=打完一场（任务消失=通关）。
    """
    # 扫国王坐标
    kings = []
    try:
        r = _lua_call(gateway, r"""
local n = tp and tp.地图 and tp.地图.npc
local out = ''
if type(n) == 'table' then
  for k, v in pairs(n) do
    if type(v) == 'table' and tostring(v.名称) == '__KING__' then
      out = out .. tostring(v.x) .. ',' .. tostring(v.y) .. ' ;; '
    end
  end
end
__out = out""".replace("__KING__", WUJI_KING_NAME), timeout=10.0)
        for seg in (r or "").split(" ;; "):
            seg = seg.strip()
            if not seg:
                continue
            try:
                x, y = seg.split(",")
                kings.append((float(x), float(y)))
            except Exception:
                pass
    except Exception:
        pass
    if not kings:
        logger.warning("副本：未找到 %s（npc 表）" % WUJI_KING_NAME)
        return False
    # 选最近的国王
    import math
    try:
        pos_r = _lua_call(gateway, r"""
local s = tp.屏幕
__out = tostring(s.主角 and s.主角.xy and s.主角.xy.x) .. ',' .. tostring(s.主角 and s.主角.xy and s.主角.xy.y)
""", timeout=8.0)
        mx, my = [float(v) for v in pos_r.split(",")]
    except Exception:
        mx = my = 0.0
    king = min(kings, key=lambda k: math.hypot(k[0]-mx, k[1]-my))
    kx, ky = king
    logger.info("副本：打 %s @(%.0f,%.0f)" % (WUJI_KING_NAME, kx, ky))
    # 走来（同 _walk 思路，本地简单版）
    t0 = __import__('time').time()
    last_xy, last_move, fix = None, t0, 0
    while __import__('time').time() - t0 < 80.0:
        try:
            pr = _lua_call(gateway, r"""
local s = tp.屏幕
__out = tostring(s.主角 and s.主角.xy and s.主角.xy.x) .. ',' .. tostring(s.主角 and s.主角.xy and s.主角.xy.y)""", timeout=8.0)
            px, py = [float(v) for v in pr.split(",")]
            d = math.hypot(px-kx, py-ky)
            if d < 60:
                _sleep(random.uniform(0.5, 0.8))
                break
            if d < 500:
                oru = _lua_call(gateway, r"""
local s = tp.屏幕
__out = tostring(s.xy and s.xy.x) .. ',' .. tostring(s.xy and s.xy.y)""", timeout=8.0)
                oxo, oyo = [float(v) for v in oru.split(",")]
                post_click(hwnd, int(kx+oxo), int(ky+oyo), gateway=gateway)
                _sleep(random.uniform(0.8, 1.2))
                last_move = __import__('time').time()
                continue
            if last_xy:
                mv = abs(px-last_xy[0]) + abs(py-last_xy[1])
                if mv >= 5:
                    last_move = __import__('time').time()
            last_xy = (px, py)
        except Exception:
            pass
        if __import__('time').time() - last_move > 5.0:
            if fix >= 4:
                break
            oru = _lua_call(gateway, r"""
local s = tp.屏幕
__out = tostring(s.xy and s.xy.x) .. ',' .. tostring(s.xy and s.xy.y)""", timeout=8.0)
            try:
                oxo, oyo = [float(v) for v in oru.split(",")]
                cx, cy = max(60, min(740, int(kx+oxo))), max(60, min(540, int(ky+oyo)))
            except Exception:
                cx, cy = 400, 300
            post_click(hwnd, cx, cy, gateway=gateway)
            fix += 1
            last_move = __import__('time').time()
            _sleep(random.uniform(2.0, 2.8))
            continue
        _sleep(random.uniform(0.8, 1.2))
    # 连点国王身体开弹窗（最多 8 次）
    for ctry in range(8):
        oru = _lua_call(gateway, r"""
local s = tp.屏幕
__out = tostring(s.xy and s.xy.x) .. ',' .. tostring(s.xy and s.xy.y)""", timeout=8.0)
        try:
            oxo, oyo = [float(v) for v in oru.split(",")]
            px, py = int(kx+oxo), int(ky+oyo)
        except Exception:
            px, py = 400, 300
        post_click(hwnd, px + random.randint(-4, 4), py + random.randint(-4, 4), gateway=gateway)
        _sleep(1.2)
        if _sw8(gateway) or zhuagui_in_battle(gateway):
            logger.info("副本：国王弹窗/进战（第%d次点击）" % (ctry+1))
            break
    fought = False
    # 弹窗已开 → 点战斗选项
    if _sw8(gateway) and not zhuagui_in_battle(gateway):
        _click_dialog_first_red(gateway, hwnd, tries=3)
    # 进战则自动战斗打完
    if zhuagui_in_battle(gateway):
        fought = True
        _wait_enter_battle(gateway, hwnd, max_s=10.0)
        _wait_out_battle(gateway, max_s=300.0)
        _sleep(random.uniform(1.0, 1.5))
    if not fought:
        logger.warning("副本：%s 弹窗/进战均未发生，本阶段未完成" % WUJI_KING_NAME)
        return False
    logger.info("副本：%s 阶段完成（任务应消失=通关）" % WUJI_KING_NAME)
    return True


def _wuji_exit(gateway, hwnd):
    """乌鸡副本通关收尾：玉散热人状态用背包传送去随机门派脱离副本。

    传送需散人（任务消失后队伍已解散）。落地后地图应不再含「副本」。
    返回 True=已离开副本；False=传送失败仍滞留。
    """
    import random as _r
    try:
        from tasks.library.ZGUI import zhuagui_teleport
    except Exception:
        return False
    dest = _r.choice(["大唐官府", "天宫", "狮驼岭", "凌波城", "花果山", "化生寺",
                      "龙宫", "魔王寨", "神木林", "天机城", "女儿村", "普陀山",
                      "阴曹地府", "无底洞", "女魃墓", "方寸山", "五庄观", "盘丝洞"])
    logger.info("副本：通关收尾，传送去随机门派 %s" % dest)
    try:
        zhuagui_teleport(gateway=gateway, hwnd=hwnd, dest=dest, verbose=False)
    except Exception as e:
        logger.warning("副本：传送异常: %s" % e)
    _sleep(random.uniform(2.5, 3.5))
    m = _current_map_name(gateway)
    left = "副本" not in (m or "")
    logger.info("副本：落地 %s 已离开副本=%s" % (m, left))
    return left


def _wait_xianren_dialog(gateway, gid, max_s=4.0):
    """等仙人对话弹出（界面[8] 对话人物=热心仙人）。返回 True=已弹。"""
    import time as _t
    t0 = _t.time()
    while _t.time() - t0 < max_s:
        try:
            r = _lua_call(gateway, r"""
local d = tp.主界面 and tp.主界面.界面数据 and tp.主界面.界面数据[8]
__out = tostring(d and d.名称内容)""", timeout=8.0)
            if (r or "").strip() == WUJI_XIANREN_NAME:
                return True
            if not _sw8(gateway):
                return False   # 弹窗没开
        except Exception:
            pass
        _sleep(0.3)
    return False


def _click_xianren_thanks(gateway, hwnd, gid, tries=3):
    """点「多谢仙人相助」（红字主块）。返回 True=已点且弹窗已接受。"""
    for attempt in range(max(1, tries)):
        try:
            _mouse_clear(hwnd, gateway)
            _sleep(random.uniform(0.25, 0.4))
        except Exception:
            pass
        rows = _dialog_red_first_row(hwnd)
        main = [r for r in rows if _DLG_MAIN_MIN_N <= r.get("n", 0) <= _DLG_BLOCK_MAX_N]
        if main:
            row = main[0]
            cx = (row["x0"] + row["x1"]) // 2
            cy = row["y0"] + 7
            post_click(hwnd, cx + random.randint(-3, 3),
                       cy + random.randint(-2, 2), gateway=gateway)
            logger.info("副本：点「多谢仙人相助」(%d,%d) 块=y%d-%d n=%d" %
                        (cx, cy, row["y0"], row["y1"], row.get("n", 0)))
            _sleep(random.uniform(0.6, 1.0))
            try:
                if not _sw8(gateway):
                    return True
            except Exception:
                pass
            logger.info("副本：多谢点击后弹窗未关（sw8=%s），重试" % _sw8(gateway))
        else:
            logger.info("副本：仙人红字主块未检出（n=%s），第%d次重扫" %
                        ([r.get("n") for r in rows], attempt + 1))
        _sleep(random.uniform(0.5, 0.8))
    return False


def _wuji_full_run(gateway, hwnd):
    """乌鸡副本全流程（刷芭蕉木妖→仙人→切图→三妖→鬼祟小妖→真假国王→收尾）。

    供两条进入路径复用：显示表直接定位进入 & 旧逻辑（红字反推+标定 rect）进入。
    返回 True=全链路完成；任一阶段失败返回 False（已执行阶段不重跑）。
    """
    r1 = _wuji_run(gateway, hwnd)
    _sleep(random.uniform(2.0, 3.0))
    if _current_map_name(gateway) not in WUJI_MAP_NAMES:
        return r1   # 刷怪阶段即把副本打完/离开
    r2 = _xianren_run(gateway, hwnd)
    _sleep(random.uniform(2.0, 3.0))
    if _current_map_name(gateway) not in WUJI_MAP_NAMES:
        return r1 and r2
    # ★第三步：CALL 国王 → 「送我进去」→ 切图3132（补全）
    if not _wuji_enter_palace(gateway, hwnd):
        logger.warning("副本：切图3132失败，中止后续")
        return r1 and r2 and False
    _sleep(random.uniform(1.5, 2.5))
    # ★第四步：打三妖（缚仙/拘灵/囚神各一场，补全）
    _wuji_three_yao_run(gateway, hwnd)
    _sleep(random.uniform(2.0, 3.0))
    r3 = _wuji_gs_run(gateway, hwnd)
    if not r3:
        return r1 and r2 and r3
    _sleep(random.uniform(2.0, 3.0))
    r4 = _wuji_king_run(gateway, hwnd)
    _sleep(random.uniform(2.0, 3.0))
    r5 = True
    if _current_map_name(gateway) in WUJI_MAP_NAMES:
        r5 = _wuji_exit(gateway, hwnd)   # 副本完成 → 传送去随机门派收尾
    return r1 and r2 and r3 and r4 and r5


# ============================================================
# 主流程
# ============================================================
def run_one(gateway, hwnd, name, rect, verbose=True):
    """做一次指定副本：开列表 → 点开启（红字）→ 点进入 → 进副本 → 打完。

    乌鸡副本走专属循环（刷 10 只芭蕉木妖）；其他副本走"一进就打一场"。
    返回 True=本轮完整走完。
    """
    # ★2026-09-17 任务感知（用户定案）：启动先读任务栏——
    #   已有「乌鸡国」任务 → 只「进入已有的乌鸡副本」，绝不再点「开启乌鸡副本」；
    #   无任务才 开启 + 进入 新开一个。
    #   真机实证：副本列表显示表有两行独立回调 271-1(开启)/271-2(进入)，
    #   「进入」行能把角色带进已存在的副本地图，故有/无任务的差别仅在于是否点开启行。
    _have_wuji_task = (name == "乌鸡副本" and _wuji_task_exists(gateway))
    if not _open_fuben_list(gateway, hwnd):
        return False
    # ★2026-09-17：乌鸡列一律用显示表 cb 实时定位，杜绝标定 rect 列漂移误开其他副本。
    #   显示表同时给出「开始/进入乌鸡副本」两行矩形 → 直接精确点击两行；
    #   任一行读不到 → 回退旧逻辑（红字反推 + 标定 rect）。
    if name == "乌鸡副本":
        r_start = _wuji_cell_rect(gateway, _WUJI_CB_START)   # "开启乌鸡副本"
        r_enter = _wuji_cell_rect(gateway, _WUJI_CB_ENTER)   # "进入乌鸡副本"
        if r_enter and r_start:
            if _have_wuji_task:
                # 已有任务：只点「进入乌鸡副本」，守住「不新增副本任务」
                logger.info("副本：已有乌鸡国任务 → 只点「进入乌鸡副本」，不点开启")
            else:
                post_click(hwnd,
                           (r_start[0] + r_start[2]) // 2 + random.randint(-3, 3),
                           (r_start[1] + r_start[3]) // 2 + random.randint(-2, 2),
                           gateway=gateway)
                logger.info("副本：显示表直接点「开启乌鸡副本」(%d,%d)"
                            % ((r_start[0] + r_start[2]) // 2,
                               (r_start[1] + r_start[3]) // 2))
                _sleep(random.uniform(1.2, 1.6))
            post_click(hwnd,
                       (r_enter[0] + r_enter[2]) // 2 + random.randint(-3, 3),
                       (r_enter[1] + r_enter[3]) // 2 + random.randint(-2, 2),
                       gateway=gateway)
            logger.info("副本：显示表直接点「进入乌鸡副本」(%d,%d)"
                        % ((r_enter[0] + r_enter[2]) // 2,
                           (r_enter[1] + r_enter[3]) // 2))
            # 进入副本可能有过场/走路，给足缓冲再判场景
            _sleep(random.uniform(1.4, 1.8))
            _mouse_clear(hwnd, gateway)
            cur_map = _current_map_name(gateway)
            # ★进入后轮询场景（过场最长 ~12s），别急着判失败
            _t0 = time.time()
            while cur_map not in WUJI_MAP_NAMES and time.time() - _t0 < 12.0:
                _sleep(random.uniform(0.8, 1.2))
                cur_map = _current_map_name(gateway)
            logger.info("副本：%s 已进入 场景=%s" % (name, cur_map))
            if cur_map not in WUJI_MAP_NAMES:
                logger.warning("副本：点进入后场景仍非乌鸡（%s），中止" % cur_map)
                return False
            return _wuji_full_run(gateway, hwnd)
        logger.warning("副本：显示表未定位到乌鸡列（cb=%s/%s），回退旧逻辑"
                       % (_WUJI_CB_START, _WUJI_CB_ENTER))
    if not _click_start(gateway, hwnd, name, rect):
        _dismiss_dialog(gateway, hwnd)
        return False
    _sleep(random.uniform(0.6, 1.0))
    if not _click_enter(gateway, hwnd, name, rect):
        return False
    _mouse_clear(hwnd, gateway)
    # 进场景缓冲（加载乌鸡副本有过场）
    _sleep(random.uniform(2.0, 3.0))
    cur_map = _current_map_name(gateway)
    logger.info("副本：%s 已进入 场景=%s" % (name, cur_map))
    # ★乌鸡副本专属：多阶段（刷芭蕉木妖→仙人→国王切图→三妖→鬼祟小妖→真假国王→收尾）
    if name == "乌鸡副本":
        return _wuji_full_run(gateway, hwnd)
    # 其他副本（解放美女 / 车迟）：沿用"一进就打一场"模式
    if not _wait_enter_battle(gateway, hwnd, max_s=40.0):
        logger.info("副本：%s 点进入后未检出进战，转下一副本" % name)
        return False
    logger.info("副本：%s 已进战斗，挂机等结束" % name)
    _wait_out_battle(gateway, max_s=300.0)
    logger.info("副本：%s 战斗结束" % name)
    _sleep(random.uniform(1.5, 2.5))
    return True


def run(gateway=ZGUI.DEFAULT_GATEWAY, hwnd=None, verbose=True, dungeons=None, **kw):
    """副本主流程（Leader 侧）。★用户定案：只跑有数据的乌鸡副本。

    2026-09-16 用户定案：只有乌鸡副本做了数据（其他副本无自动化数据/未做），
    开启没有意义 → dungeons 默认=((乌鸡副本),)。可传 dungeons 覆盖。

    返回实际完成次数（int）。
    """
    # ★用户定案：只有乌鸡副本做了数据，其他副本一律不开启。
    #   显式写乌鸡副本，避免 DUNGEONS 元组末尾误加其他副本后被默认开启。
    duns = list(dungeons if dungeons else (("乌鸡副本", DUNGEONS[-1][1]),))
    if hwnd is None:
        hwnd = get_hwnd()
    if not hwnd:
        logger.warning("副本：无游戏窗口")
        return 0
    done = 0
    per = {}          # name -> 本脚本内已完成次数
    fail_streak = 0   # 连续不可用副本数（防死循环）
    try:
        _panel_pin_defaults(gateway)
        _sleep(random.uniform(0.2, 0.35))
        # 开跑前若在战斗，先等脱战
        _wait_out_battle(gateway, max_s=120.0)
        idx = 0
        while done < MAX_RUNS_PER_DAY:
            name, rect = duns[idx % len(duns)]
            idx += 1
            # ★2026-09-17 任务感知（用户定案）：有无「乌鸡国」任务由 run_one 内部统一
            #   处理（有=只点「进入乌鸡副本」271-2；无=点「开启」271-1 后再进入），
            #   这里不再直接调 _wuji_full_run（它假设已在副本内，会误报"非乌鸡场景"）。
            if per.get(name, 0) >= MAX_RUNS_PER_DUNGEON:
                logger.info("副本：%s 本脚本内已完成 %d 次（达单副本上限），跳过"
                            % (name, per[name]))
                fail_streak += 1
                if fail_streak >= len(duns):
                    logger.info("副本：全部副本均达上限/不可用，结束（本次共 %d 次）" % done)
                    break
                continue
            logger.info("副本：第 %d 次尝试 → %s（已完成 %d/%d 次）"
                        % (done + 1, name, done, MAX_RUNS_PER_DAY))
            ok = run_one(gateway, hwnd, name, rect, verbose=verbose)
            if ok:
                done += 1
                per[name] = per.get(name, 0) + 1
                fail_streak = 0
                logger.info("副本：%s 完成（本副本 %d/%d 次，累计 %d/%d 次）"
                            % (name, per[name], MAX_RUNS_PER_DUNGEON,
                               done, MAX_RUNS_PER_DAY))
            else:
                fail_streak += 1
                logger.info("副本：%s 本轮未完成（可能本日次数已满），累计 %d 次"
                            % (name, done))
                if fail_streak >= len(duns):
                    logger.info("副本：连续 %d 个副本不可用，判定本日已打满，结束"
                                % fail_streak)
                    break
            _sleep(random.uniform(1.5, 3.0))
        logger.info("副本：流程结束，本次共完成 %d 次" % done)
        return done
    except Exception as e:
        logger.warning("副本：异常中止: %s" % e)
        return done
