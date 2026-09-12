# -*- coding: utf-8 -*-
"""仓库存物品（用户 2026-09-12 定案；坐标全部实机标定）

流程（单角色；★组队下无法用仓库，调用方需先解散队伍）：
  1) 快捷菜单开关 (149,10)-(173,41) → 快捷传送 (269,45)-(322,58)
  2) 传送对话框 → 仓库（免费）(194,410) → 精确落地 长安 [355,33]
  3) tp.地图.npc 找 仓库管理员 → 点它 → 红字行首行（打开仓库）→ 面板开
  4) 逐件存：可叠物品（有 数量）需 >= _STORE_STACK_MIN(99) 才存；
     保留：第一排（格子id<=5）+ 天眼/合成旗（名称子串）；
     同物品同分页：先在仓库里找同名物品所在分页，找不到用第一个未满分页
  5) 仓库满判定=功能判定：右键后行囊件数下降=成功；没降=满 → 换下一分页重试
  6) 退出 (646,408) 收面板

Lua 依据（全部实测）：
  界面[14] 仓库面板：本类开关/当前仓库/仓库数量(容量恒26)/仓库按钮(26个带包围盒)
    物品数据=行囊侧物品（含 小动画{x,y}=点击坐标 / 数量 / 名称 / 格子id）
  仓库物品[1][i]=当前分页物品（含 名称/数量）→ 用于"同物品同分页"检索
"""

import random
import time

from . import ZGUI as _Z

# ---- 用户标定坐标（客户区）----
_MENU_TOGGLE = (149, 10, 173, 41)      # 快捷菜单开关
_TP_BTN = (269, 45, 322, 58)           # 快捷传送
_TP_WAREHOUSE = (194, 410)             # 传送对话框-仓库（免费）
_WH_QUIT = (646, 408)                  # 仓库面板-退出
_WH_BTN_X0, _WH_BTN_Y1, _WH_BTN_Y2 = 215, 395, 423   # 分页按钮起始/两排 y
_WH_BTN_DX, _WH_BTN_W, _WH_BTN_H = 25, 22, 23
_NPC_FALLBACK = (298, 305)             # 落点[355,33]时仓库管理员固定屏幕位（实测）

_STORE_STACK_MIN = 99                  # 可叠物品攒满 99 才存（用户定案）
_STORE_NO_STACK_MIN = ("魔兽要诀",)    # ★2026-09-12 用户更正：魔兽要诀不可叠加
                                       # （每本占一格）→ 不限 99，有多少存多少
_STORE_KEEP_NAMES = ("天眼", "合成旗", "飞行旗")   # 名称子串保护
_STORE_KEEP_SLOTS = 5                  # 第一排（格子id<=5）保留

_PANEL_LUA = r'''
local w = tp and tp.主界面 and tp.主界面.界面数据 and tp.主界面.界面数据[14]
if type(w) ~= 'table' then __out = '无' return end
local bag = 0
if type(w.物品数据) == 'table' then for _ in pairs(w.物品数据) do bag = bag + 1 end end
local wh = 0
local c = w.仓库物品 and w.仓库物品[1]
if type(c) == 'table' then for _ in pairs(c) do wh = wh + 1 end end
__out = '开=' .. tostring(w.本类开关) .. ' 分页=' .. tostring(w.当前仓库)
     .. ' 行囊=' .. bag .. ' 本页物品=' .. wh
'''


def _log(msg):
    _Z.logger.info("[存仓] " + msg)


def _click_box(hwnd, gw, box, tag=""):
    x0, y0, x1, y1 = box
    x = random.randint(x0 + 3, max(x0 + 4, x1 - 3))
    y = random.randint(y0 + 1, max(y0 + 2, y1 - 1))
    _Z.post_click(hwnd, x, y, gateway=gw)
    return x, y


def _panel(hwnd, gw):
    """返回 dict：{'open':bool,'page':int,'bag':int,'wh':int}"""
    r = _Z._lua_call(gw, _PANEL_LUA) or ""
    d = {"open": False, "page": None, "bag": 0, "wh": 0}
    for seg in r.split(" "):
        if "=" not in seg:
            continue
        k, _, v = seg.partition("=")
        if k == "开":
            d["open"] = (v == "true")
        elif k == "分页":
            try:
                d["page"] = int(v)
            except ValueError:
                pass
        elif k == "行囊":
            try:
                d["bag"] = int(v)
            except ValueError:
                pass
        elif k == "本页物品":
            try:
                d["wh"] = int(v)
            except ValueError:
                pass
    return d


def _switch_page(hwnd, gw, page, tries=3):
    """点分页按钮并回读校验（点击→回读→重试）。"""
    for _ in range(tries):
        if page <= 8:
            x, y = _WH_BTN_X0 + (page - 1) * _WH_BTN_DX, _WH_BTN_Y1
        else:
            x, y = _WH_BTN_X0 + (page - 9) * _WH_BTN_DX, _WH_BTN_Y2
        _Z.post_click(hwnd, x + _WH_BTN_W // 2, y + _WH_BTN_H // 2, gateway=gw)
        time.sleep(random.uniform(1.0, 1.4))
        st = _panel(hwnd, gw)
        if st.get("page") == page:
            return True
    return False


def _page_items(hwnd, gw):
    """当前分页物品：[(名称, 数量)]（仓库物品[1] 容器）。"""
    r = _Z._lua_call(gw, r'''
local w = tp and tp.主界面 and tp.主界面.界面数据 and tp.主界面.界面数据[14]
local c = w and w.仓库物品 and w.仓库物品[1]
if type(c) ~= 'table' then __out = '' return end
local out = {}
for _, v in pairs(c) do
  if type(v) == 'table' then
    out[#out+1] = tostring(v.名称 or '') .. '#' .. tostring(v.数量 or '')
  end
end
__out = table.concat(out, ',')
''') or ""
    res = []
    for seg in r.split(","):
        if "#" in seg:
            nm, _, qty = seg.partition("#")
            res.append((nm, qty))
    return res


def _bag_items(hwnd, gw):
    """行囊侧物品：[{'id','name','qty','x','y'}]（小动画=点击坐标）。"""
    r = _Z._lua_call(gw, r'''
local w = tp and tp.主界面 and tp.主界面.界面数据 and tp.主界面.界面数据[14]
local d = w and w.物品数据
if type(d) ~= 'table' then __out = '' return end
local out = {}
for _, v in pairs(d) do
  if type(v) == 'table' then
    local sa = v.小动画
    local x = type(sa) == 'table' and tonumber(sa.x) or 0
    local y = type(sa) == 'table' and tonumber(sa.y) or 0
    out[#out+1] = string.format('%s|%s|%s|%d|%d|%s',
      tostring(v.格子id or 0), tostring(v.名称 or ''), tostring(v.数量 or ''),
      x, y, tostring(v.类型 or ''))
  end
end
__out = table.concat(out, ' ;; ')
''') or ""
    res = []
    for seg in r.split(" ;; "):
        p = seg.split("|")
        if len(p) >= 5:
            res.append({"id": _Z._coord_int(p[0]), "name": p[1], "qty": p[2],
                        "x": _Z._coord_int(p[3]), "y": _Z._coord_int(p[4]),
                        "type": p[5]})
    return res


def _dialog_open(gw):
    """NPC 对话框是否打开（界面[8].本类开关）——功能性校验，不用像素。"""
    return _Z._lua_call(gw, r'''
local d = tp and tp.主界面 and tp.主界面.界面数据 and tp.主界面.界面数据[8]
__out = tostring(d and d.本类开关)''') == "true"


def _go_warehouse(hwnd, gw):
    """快捷菜单 → 快捷传送 → 仓库（免费）。返回 True=已到长安仓库点。

    ★2026-09-12 改功能性校验：菜单开关是切换式且像素会被队友名条干扰，
      改为"点开关→点快捷传送→读界面8开关"配对重试（最多 4 轮），不再看图。
    """
    opened = False
    for _ in range(4):
        _click_box(hwnd, gw, _MENU_TOGGLE, "菜单开关")
        time.sleep(0.9)
        _click_box(hwnd, gw, _TP_BTN, "快捷传送")
        time.sleep(1.5)
        if _dialog_open(gw):
            opened = True
            break
    if not opened:
        _log("快捷传送对话框打不开（4 轮）")
        return False
    _Z.post_click(hwnd, _TP_WAREHOUSE[0] + random.randint(-6, 6),
                  _TP_WAREHOUSE[1] + random.randint(-1, 3), gateway=gw)
    time.sleep(3.5)
    pos = _Z._lua_call(gw, r'''
local me = tp and tp.屏幕 and tp.屏幕.主角 and tp.屏幕.主角.xy
__out = tostring(tp and tp.地图 and tp.地图.地图名称) .. ','
     .. tostring(me and math.floor((me.x or 0) / 20)) .. ','
     .. tostring(me and math.floor((me.y or 0) / 20))''') or ""
    _log("落点: %s" % pos)
    # ★落地后关掉快捷传送对话框（对话框开着角色不能移动，会挡住后续点 NPC）
    _close_dialogs(hwnd, gw)
    return pos.startswith("长安城,35")


def _close_dialogs(hwnd, gw, tries=3):
    """关闭挡住世界点击的对话框（界面8：快捷传送/NPC 对话）。

    ★2026-09-12 用户实测：对话框开着时角色不能移动（世界点击被忽略）——
      传送落地后必须先把快捷传送对话框关掉，否则点 NPC 全部无效。
    优先点对话框自带的 关闭按钮（Lua 包围盒），再兜底 ESC。
    """
    for _ in range(max(1, tries)):
        pos = _Z._lua_call(gw, r'''
local d = tp and tp.主界面 and tp.主界面.界面数据 and tp.主界面.界面数据[8]
local b = d and d.关闭 and d.关闭.包围盒
if not (d and d.本类开关 == true) or not b then __out = '' return end
__out = string.format('%d,%d', b.x + 8, b.y + 8)''') or ""
        if "," in pos:
            try:
                x, y = [int(float(s)) for s in pos.split(",")]
            except ValueError:
                break
            _Z.post_click(hwnd, x, y, gateway=gw)
            time.sleep(0.8)
            continue
        break
    if _Z._lua_call(gw, r'''
local d = tp and tp.主界面 and tp.主界面.界面数据 and tp.主界面.界面数据[8]
__out = tostring(d and d.本类开关)''') == "true":
        import ctypes as _c
        u = _c.windll.user32
        u.PostMessageW(hwnd, 0x0100, 0x1B, 0)
        u.PostMessageW(hwnd, 0x0101, 0x1B, 0xC0000001)
        time.sleep(0.6)
    return _Z._lua_call(gw, r'''
local d = tp and tp.主界面 and tp.主界面.界面数据 and tp.主界面.界面数据[8]
__out = tostring(d and d.本类开关)''') != "true"


def _call_warehouse_npc(hwnd, gw):
    """CALL 仓库管理员 → 点"打开仓库"（对话最顶选项）→ 校验面板打开。

    ★NPC 定位：先轮询 npc 表（传送落地后表可能还没加载），表里没有再用
      实测固定屏幕位（落点[355,33] 时 NPC 恒在角色左前方 (298,305)）。
    ★选项定位：用对话框 关闭按钮 的 Lua 包围盒做锚点推算第一行
      （实测 关闭=(608,254) ↔ 打开仓库行 (110-175, 288-300)，dx≈-480 dy≈+40）；
      失败再退回红字行检测（取最顶行）。
    """
    def _npc_pos():
        return _Z._lua_call(gw, r'''
local t = tp and tp.地图 and tp.地图.npc
local off = tp and tp.屏幕 and tp.屏幕.xy
local ox, oy = (off and off.x) or 0, (off and off.y) or 0
if type(t) ~= 'table' then __out = '' return end
for _, v in pairs(t) do
  if type(v) == 'table' and tostring(v.名称 or ''):find('仓') then
    __out = string.format('%d,%d', (tonumber(v.x) or 0) + ox, (tonumber(v.y) or 0) + oy)
    return
  end
end
__out = ''
''') or ""

    def _click_npc():
        pos = ""
        t0 = time.time()
        while time.time() - t0 < 12.0:
            pos = _npc_pos()
            if "," in pos:
                break
            time.sleep(1.0)
        if "," in pos:
            x, y = [int(float(s)) for s in pos.split(",")]
        else:
            x, y = _NPC_FALLBACK          # 落点固定位（实测）
        _Z.post_click(hwnd, x + random.randint(-4, 4),
                      y + random.randint(-4, 4), gateway=gw)
        time.sleep(1.8)
        return "," in pos

    # ★2026-09-12 实测坑：背包面板开着会盖住 NPC（点击落在背包格上出物品提示），
    #   点 NPC 前先无条件关背包。
    try:
        _Z._bag_ensure_close(gw, hwnd)
    except Exception:
        pass
    _close_dialogs(hwnd, gw)
    # 实测：落点与 NPC 相距约 5 格（99 世界像素）——单击只是"开始走过去"，
    #   没到交互距离不弹对话。改为"走近→点→校验"循环（每轮按表重算屏幕位）。
    for _ in range(5):
        if _panel(hwnd, gw)["open"]:
            return True
        pos = ""
        t0 = time.time()
        while time.time() - t0 < 6.0:
            pos = _npc_pos()
            if "," in pos:
                break
            time.sleep(1.0)
        if "," in pos:
            x, y = [int(float(s)) for s in pos.split(",")]
        else:
            x, y = _NPC_FALLBACK
        _Z.post_click(hwnd, x + random.randint(-4, 4),
                      y + random.randint(-4, 4), gateway=gw)
        time.sleep(1.6)
        if _panel(hwnd, gw)["open"]:
            return True
        # 对话已弹 → 点"打开仓库"：
        # ★2026-09-12 用户标定坐标 (117,322)-(169,332) 优先（实测最稳），
        #   失败再用 关闭按钮锚点推算 / 红字行检测兜底。
        _Z.post_click(hwnd, random.randint(120, 166), random.randint(323, 331),
                      gateway=gw)
        time.sleep(1.6)
        if _panel(hwnd, gw)["open"]:
            return True
        anchor = _Z._lua_call(gw, r'''
local d = tp and tp.主界面 and tp.主界面.界面数据 and tp.主界面.界面数据[8]
local b = d and d.关闭 and d.关闭.包围盒
if not (d and d.本类开关 == true) or not b then __out = '' return end
__out = string.format('%d,%d', b.x - 480, b.y + 40)''') or ""
        if "," in anchor:
            ax, ay = [int(float(s)) for s in anchor.split(",")]
            _Z.post_click(hwnd, ax + random.randint(0, 50),
                          ay + random.randint(-2, 8), gateway=gw)
            time.sleep(1.6)
            continue
        rows = _Z._bonus_dialog_rows(hwnd)
        if rows:
            b = rows[0]
            _Z.post_click(hwnd, random.randint(b["x0"] + 3,
                                               max(b["x0"] + 4, b["x1"] - 3)),
                          random.randint(b["y0"], b["y1"]), gateway=gw)
            time.sleep(1.6)
    st = _panel(hwnd, gw)
    if not st["open"]:
        _log("打开仓库面板失败（5 轮）")
    return st["open"]


def zhuagui_store_all(pid, keep_names=_STORE_KEEP_NAMES, stack_min=_STORE_STACK_MIN,
                      hwnd=None, verbose=True):
    """单角色：背包物品存仓库（★2026-09-12 用户定案：边存边填页）。

    不预扫描全部分页（省 ~60s）——直接在当前分页开存；存不进去（该页满）
    就切下一页继续；26 页都满才放弃该件。
    规则：可叠物品（有 数量 字段）攒满 stack_min(99) 才存；保留第一排
    （格子id<=5）+ 名称含 天眼/合成旗/飞行旗。
    ★组队下无法使用仓库——调用方必须先解散队伍。
    返回 (成功标志, 存放件数, 说明)。
    """
    gw = "file://pzxy_p%d" % pid
    if hwnd is None:
        from tools.squad_auto_team import find_hwnd_by_pid
        hwnd = find_hwnd_by_pid(pid)
    if not hwnd:
        return False, 0, "找不到窗口"
    if not _go_warehouse(hwnd, gw):
        return False, 0, "到仓库失败"
    if not _call_warehouse_npc(hwnd, gw):
        return False, 0, "开仓库面板失败"

    bag = _bag_items(hwnd, gw)
    todo = []
    for it in bag:
        nm, qty, gid = it["name"], it["qty"], it["id"]
        if not nm or not it["x"] or not it["y"]:
            continue
        if any(k in nm for k in keep_names):
            continue
        if gid is not None and gid <= _STORE_KEEP_SLOTS:      # 第一排保留
            continue
        if (qty.isdigit() and int(qty) < stack_min
                and not any(k in nm for k in _STORE_NO_STACK_MIN)):
            continue                                            # 可叠未攒满 → 留
        todo.append(it)
    if not todo:
        _log("p%d 无可存物品（保留规则过滤后）" % pid)
        _exit_panel(hwnd, gw)
        return True, 0, "无可存"

    # ★用户定案：不预扫描——直接在当前分页开存；存不进去（该页满）就切下一页
    #   继续；26 页都满才放弃该件。cur 从面板当前分页开始（延续上次进度）。
    st = _panel(hwnd, gw)
    cur = st.get("page") or 1
    stored = 0
    for it in todo:
        for _ in range(26):
            if not _switch_page(hwnd, gw, cur):
                cur = cur % 26 + 1
                continue
            before = _panel(hwnd, gw)["bag"]
            _Z.post_right_click(hwnd, it["x"], it["y"], gateway=gw)
            time.sleep(random.uniform(1.2, 1.6))
            after = _panel(hwnd, gw)["bag"]
            if after < before:                    # 存成功 → 该页继续放下一件
                stored += 1
                _log("p%d %s → 分页%d（余 %d 件）" % (pid, it["name"], cur, after))
                break
            _log("p%d 分页%d 存 %s 未生效（满页）→ 下一页"
                 % (pid, cur, it["name"]))
            cur = cur % 26 + 1
        else:
            _log("p%d %s 26 个分页都满，放弃该件" % (pid, it["name"]))
    _exit_panel(hwnd, gw)
    return True, stored, "存入 %d 件" % stored


def _exit_panel(hwnd, gw):
    _Z.post_click(hwnd, _WH_QUIT[0] + random.randint(-4, 4),
                  _WH_QUIT[1] + random.randint(-2, 2), gateway=gw)
    time.sleep(0.8)
    st = _panel(hwnd, gw)
    if st["open"]:
        _log("退出未生效，补 ESC")
        import ctypes
        u = ctypes.windll.user32
        u.PostMessageW(hwnd, 0x0100, 0x1B, 0)
        u.PostMessageW(hwnd, 0x0101, 0x1B, 0xC0000001)
        time.sleep(0.6)
