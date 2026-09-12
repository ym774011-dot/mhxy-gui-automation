# -*- coding: utf-8 -*-
"""仓库存物品——独立测试工具（用户要求：先测好再集成进脚本）

用法:
  python tools/_test_store_warehouse.py <pid> <step>
  step: tp | dialog | open | dump | store | quit | all

坐标（用户 2026-09-12 标定，客户区）:
  快捷传送按钮          (271,46)-(317,56)
  传送对话框-仓库（免费） (176,412)-(240,424)
  仓库面板-仓库侧        (117,322)-(169,332)
  仓库面板-退出          (634,401)-(659,414)
Lua 判据: 界面数据[14] = 仓库面板
  本类开关 / 仓库数量 / 当前仓库 / 仓库按钮 / 仓库数据 / 退出 / 行囊 / 取出 / 道具
"""
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tasks.library.ZGUI import (post_click, post_right_click, _lua_call,  # noqa: E402
                                grab_client, set_target_hwnd, _bag_used_count)
from tools.zhuagui_squad import enum_game_windows  # noqa: E402

COORD = {
    "menu_toggle": (149, 10, 173, 41),      # ★快捷菜单开关（点开出 4 个红标签）
    "tp_btn": (269, 45, 322, 58),           # ★快捷传送标签
    "tp_warehouse": (176, 412, 240, 424),   # 传送对话框-仓库（免费）
    "wh_side": (117, 322, 169, 332),        # 仓库面板-仓库侧（备用）
    "wh_quit": (634, 401, 659, 414),        # 仓库面板-退出
}

PANEL = r'''
local j = tp and tp.主界面 and tp.主界面.界面数据
local w = j and j[14]
if type(w) ~= 'table' then __out = '无面板' return end
__out = '开关=' .. tostring(w.本类开关) .. ' 当前仓库=' .. tostring(w.当前仓库)
     .. ' 仓库数量=' .. tostring(w.仓库数量) .. ' 仓库数据=' .. type(w.仓库数据)
     .. ' 行囊=' .. type(w.行囊)
'''

BAG = r'''
local j = tp and tp.主界面 and tp.主界面.界面数据
local pd = type(j) == 'table' and type(j[3]) == 'table' and j[3].物品数据
if type(pd) ~= 'table' then __out = '背包未开' return end
local out, n = {}, 0
for i = 1, 20 do
  local v = pd[i]
  if type(v) == 'table' and tostring(v.名称 or '') ~= '' then
    n = n + 1
    out[#out+1] = i .. ':' .. tostring(v.名称)
  end
end
__out = '占用=' .. n .. ' [' .. table.concat(out, ',') .. ']'
'''


def find_hwnd(pid):
    for p, h, t in enum_game_windows():
        if p == pid:
            return h
    return None


def shot(hwnd, tag):
    try:
        img = grab_client(hwnd)
        pil = img[0] if isinstance(img, tuple) else img
        path = r"E:\DS\mhxy-gui-automation\test_data\store_%s.png" % tag
        pil.save(path)
        print("  截图: %s" % path)
    except Exception as e:
        print("  截图失败:", e)


def click_box(hwnd, gw, box, tag=""):
    x0, y0, x1, y1 = box
    x = random.randint(x0 + 3, max(x0 + 4, x1 - 3))
    y = random.randint(y0 + 1, max(y0 + 2, y1 - 1))
    post_click(hwnd, x, y, gateway=gw)
    print("  点击 %s (%d,%d)" % (tag or box, x, y))


def open_panels(gw):
    return _lua_call(gw, r'''local j=tp and tp.主界面 and tp.主界面.界面数据
local o={}
if type(j)=='table' then for k=1,30 do local v=j[k]
if type(v)=='table' and v.本类开关==true then o[#o+1]=k end end end
__out=table.concat(o,',')''') or ""


def step_tp(pid, hwnd, gw):
    print("[tp] 1) 点快捷菜单开关 (149,10)-(173,41)")
    click_box(hwnd, gw, COORD["menu_toggle"], "菜单开关")
    time.sleep(1.0)
    shot(hwnd, "menu")
    print("[tp] 2) 点快捷传送 (269,45)-(322,58)")
    click_box(hwnd, gw, COORD["tp_btn"], "快捷传送")
    time.sleep(1.5)
    shot(hwnd, "tp_dialog")
    print("  开启界面:", open_panels(gw))


def step_dialog(pid, hwnd, gw):
    print("[dialog] 点 仓库（免费）")
    click_box(hwnd, gw, COORD["tp_warehouse"], "仓库免费")
    time.sleep(3.5)
    shot(hwnd, "tp_arrive")
    print("  地图:", _lua_call(gw, r'''__out=tostring(tp and tp.地图 and tp.地图.地图名称)'''))
    print("  自身:", _lua_call(gw, r'''local me=tp and tp.屏幕 and tp.屏幕.主角 and tp.屏幕.主角.xy
__out=tostring(me and me.x)..','..tostring(me and me.y)'''))
    print("  面板:", _lua_call(gw, PANEL))


def step_open(pid, hwnd, gw):
    print("[open] Lua 找 仓库管理员 NPC → CALL 开面板")
    r = _lua_call(gw, r'''
local t = tp and tp.地图 and tp.地图.npc
local off = tp and tp.屏幕 and tp.屏幕.xy
local ox, oy = (off and off.x) or 0, (off and off.y) or 0
if type(t) ~= 'table' then __out = '' return end
for _, v in pairs(t) do
  if type(v) == 'table' then
    local nm = tostring(v.名称 or '')
    if nm:find('仓库') then
      __out = string.format('%d,%d', (tonumber(v.x) or 0) + ox, (tonumber(v.y) or 0) + oy)
      return
    end
  end
end
__out = ''
''')
    print("  仓库管理员屏幕位:", r or "(未找到)")
    if r and "," in r:
        x, y = [int(float(s)) for s in r.split(",")]
        post_click(hwnd, x, y, gateway=gw)
        time.sleep(1.5)
    else:
        click_box(hwnd, gw, COORD["wh_side"], "仓库侧兜底")
        time.sleep(1.2)
    shot(hwnd, "open")
    print("  面板:", _lua_call(gw, PANEL))


def step_dump(pid, hwnd, gw):
    print("[dump] 仓库面板全量")
    print(_lua_call(gw, r'''
local j = tp and tp.主界面 and tp.主界面.界面数据
local w = j and j[14]
if type(w) ~= 'table' then __out = '无面板' return end
local out = {}
for k, v in pairs(w) do
  local tv = type(v)
  if tv == 'table' then
    local c = 0
    for _ in pairs(v) do c = c + 1 end
    out[#out+1] = tostring(k) .. '=t(' .. c .. ')'
  else
    out[#out+1] = tostring(k) .. '=' .. tostring(v)
  end
end
__out = table.concat(out, ' ;; ')
'''))
    print("  仓库按钮:", _lua_call(gw, r'''
local w = tp and tp.主界面 and tp.主界面.界面数据 and tp.主界面.界面数据[14]
local bs = w and w.仓库按钮
if type(bs) ~= 'table' then __out = '无' return end
local out, n = {}, 0
for k, v in pairs(bs) do
  n = n + 1
  if n <= 8 then
    local b = type(v) == 'table' and v.包围盒
    out[#out+1] = tostring(k) .. '=' .. (b and string.format('(%d,%d %dx%d)', b.x, b.y, b.w or 0, b.h or 0) or tostring(v))
  end
end
__out = n .. '个 ;; ' .. table.concat(out, ' ;; ')
'''))
    print("  背包:", _lua_call(gw, BAG))


def step_store(pid, hwnd, gw):
    print("[store] 右键行囊物品存仓（占位：待 dump 确认物品坐标后实现）")
    print("  背包:", _lua_call(gw, BAG))


def step_quit(pid, hwnd, gw):
    print("[quit] 点退出")
    click_box(hwnd, gw, COORD["wh_quit"], "退出")
    time.sleep(1.0)
    shot(hwnd, "quit")
    print("  面板:", _lua_call(gw, PANEL))


STEPS = {"tp": step_tp, "dialog": step_dialog, "open": step_open,
         "dump": step_dump, "store": step_store, "quit": step_quit}

if __name__ == "__main__":
    pid = int(sys.argv[1])
    step = sys.argv[2] if len(sys.argv) > 2 else "all"
    hwnd = find_hwnd(pid)
    gw = "file://pzxy_p%d" % pid
    set_target_hwnd(hwnd)
    print("角色 pid=%d hwnd=%s" % (pid, hex(hwnd or 0)))
    print("初始面板:", _lua_call(gw, PANEL))
    print("初始背包:", _lua_call(gw, BAG))
    if step == "all":
        for s in ("tp", "dialog", "open", "dump", "quit"):
            STEPS[s](pid, hwnd, gw)
    else:
        STEPS[step](pid, hwnd, gw)
