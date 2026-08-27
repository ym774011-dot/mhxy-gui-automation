# -*- coding: utf-8 -*-
"""遍历 15门派：会员卡瞬移 + 读地图ID → 建立 SECT_MAP_ID 表"""
import json, urllib.request, time, sys
import ctypes

sys.path.insert(0, r"e:\DS\mhxy-gui-automation")
from core.window_manager import window_manager

GW = "http://127.0.0.1:18083"
PID = 17000
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
VK_TAB = 0x09
MK_L = 0x0001
MK_R = 0x0002

SECT_LIST_15 = ["大唐官府","方寸山","化生寺","凌波城","龙宫","魔王寨","女儿村","普陀山","盘丝洞","神木林","狮驼岭","天宫","无底洞","五庄观","阴曹地府"]

def _lp(x, y):
    return (int(y) << 16) | (int(x) & 0xFFFF)

def http(path, data=None):
    req = urllib.request.Request(GW + path,
        data=json.dumps(data).encode("utf-8") if data is not None else None,
        headers={"Content-Type": "application/json"} if data is not None else {})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8", "replace"))

def lua(code):
    d = http("/api/lua", {"code": code})
    return d.get("result", {}).get("value")

def expr(e):
    d = http("/api/lua/expr", {"expr": e})
    return d.get("result", {}).get("value")

def dialog_state():
    code = r'''
local d = tp.窗口.对话栏
local out = "可视=" .. tostring(d and d.可视 or false) .. " 名称=" .. tostring(d and d.名称 or "")
local opt = d and d.选项
if type(opt) == "table" then
  for i = 1, 30 do
    local o = opt[i]
    if type(o) ~= "table" then break end
    out = out .. "|" .. tostring(o.跳转链接 or "")
  end
end
_G.__out = out'''
    return lua(code)

def card_pos():
    code = r'''
local bag = tp.窗口.道具行囊
local out = "-1,-1"
if type(bag) == "table" and type(bag.物品) == "table" then
  for k, it in pairs(bag.物品) do
    if type(it) == "table" and tostring(it.名称 or "") == "鲜衣怒马会员卡" then
      out = tostring(it.x) .. "," .. tostring(it.y)
      break
    end
  end
end
_G.__out = out'''
    v = lua(code)
    try:
        x, y = v.split(",")
        return int(x), int(y)
    except Exception:
        return 352, 194

def sect_center(name):
    code = r'''
local opt = tp.窗口.对话栏.选项
local out = ""
if type(opt) == "table" then
  for i = 1, 30 do
    local o = opt[i]
    if type(o) == "table" and tostring(o.跳转链接 or "") == "NAME" then
      local j = o.选中判断
      if type(j) == "table" then
        local cx = (tonumber(j.x or 0) + tonumber(j.x2 or 0)) / 2
        local cy = (tonumber(j.y or 0) + tonumber(j.y2 or 0)) / 2
        out = tostring(cx) .. "," .. tostring(cy)
      end
      break
    end
  end
end
_G.__out = out'''.replace("NAME", name)
    v = lua(code)
    try:
        x, y = v.split(",")
        return int(x), int(y)
    except Exception:
        return None, None

def click(hwnd, cx, cy, rbutton=False):
    if cx is None or cy is None:
        return
    u = ctypes.windll.user32
    down, up, mk = (WM_RBUTTONDOWN, WM_RBUTTONUP, MK_R) if rbutton else (WM_LBUTTONDOWN, WM_LBUTTONUP, MK_L)
    u.PostMessageW(hwnd, WM_MOUSEMOVE, 0, _lp(cx, cy)); time.sleep(0.12)
    u.PostMessageW(hwnd, down, mk, _lp(cx, cy)); time.sleep(0.12)
    u.PostMessageW(hwnd, up, 0, _lp(cx, cy))

def ensure_bag(hwnd):
    v = expr("tostring(tp.窗口.道具行囊.可视 or false)")
    if v != "true":
        u = ctypes.windll.user32
        u.PostMessageW(hwnd, WM_KEYDOWN, VK_TAB, 0)
        u.PostMessageW(hwnd, WM_KEYUP, VK_TAB, 0)
        time.sleep(0.8)

def ensure_sect_menu(hwnd):
    """确保对话栏在当前门派传送子菜单状态，返回 True/False"""
    for _ in range(4):
        st = dialog_state() or ""
        vis = "可视=true" in st
        is_root = ("领取每日福利" in st) or ("我要存钱" in st)
        has_sect = any(s in st for s in SECT_LIST_15)
        if vis and has_sect and not is_root:
            return True
        if not vis:
            cx, cy = card_pos()
            click(hwnd, cx, cy, rbutton=True)
            time.sleep(1.2)
            continue
        if is_root:
            click(hwnd, 147, 415)
            time.sleep(1.0)
            continue
        return False
    return False

ok = window_manager.bind(pid=PID)
hwnd = getattr(window_manager, "hwnd", None)
print("hwnd=", hwnd)

result = {}
for name in SECT_LIST_15:
    ensure_bag(hwnd)
    if not ensure_sect_menu(hwnd):
        print(f"[{name}] 无法打开门派菜单，跳过"); continue
    cx, cy = sect_center(name)
    if cx is None:
        print(f"[{name}] 未定位选项，跳过"); continue
    before = expr("tostring(tp.当前地图 or '')")
    click(hwnd, cx, cy)
    time.sleep(3.0)
    mid = expr("tostring(tp.当前地图 or '')")
    result[name] = mid
    print(f"[{name}] -> 地图={mid} (点击前={before})")
    # 关掉会员对话框避免残留上下文（点"让我再想想"或按Tab；先试关闭按钮）
    # 直接留待下次重开即可

print("==== SECT_MAP_ID ====")
print(json.dumps(result, ensure_ascii=False, indent=1))