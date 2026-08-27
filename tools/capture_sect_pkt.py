# -*- coding: utf-8 -*-
"""抓取「会员传送」点到某门派的网络包（协议重放用）"""
import json, urllib.request, time, sys
import ctypes

sys.path.insert(0, r"e:\DS\mhxy-gui-automation")
from core.window_manager import window_manager

GW = "http://127.0.0.1:18083"
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
MK_L = 0x0001
MK_R = 0x0002

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

def pkts():
    d = http("/api/net/keypkts")
    return d.get("result", {}).get("packets", []) or d.get("packets", []) or []

def click(hwnd, cx, cy, rbutton=False):
    u = ctypes.windll.user32
    down, up, mk = (WM_RBUTTONDOWN, WM_RBUTTONUP, MK_R) if rbutton else (WM_LBUTTONDOWN, WM_LBUTTONUP, MK_L)
    u.PostMessageW(hwnd, WM_MOUSEMOVE, 0, _lp(cx, cy)); time.sleep(0.1)
    u.PostMessageW(hwnd, down, mk, _lp(cx, cy)); time.sleep(0.1)
    u.PostMessageW(hwnd, up, 0, _lp(cx, cy))

def dialog_state():
    code = r'''
local d = tp.窗口.对话栏
local out = "可视=" .. tostring(d and d.可视 or false) .. " 名称=" .. tostring(d and d.名称 or "")
local opt = d and d.选项
local n = 0
if type(opt) == "table" then
  for i = 1, 30 do
    local o = opt[i]
    if type(o) ~= "table" then break end
    if i > 1 then out = out .. "|" end
    out = out .. tostring(o.跳转链接 or "")
  end
end
_G.__out = out'''
    return lua(code)

ok = window_manager.bind(pid=17000)
hwnd = getattr(window_manager, "hwnd", None)
print("绑定:", ok, "hwnd=", hwnd)

base = pkts()  # baseline
print("基线包数:", len(base), "最后ts:", base[-1].get("ts") if base else None)
start = base[-1].get("ts", 0) if base else 0
st = dialog_state()
print("点击前对话栏:", st)

TARGET = "女儿村"
SECT_OPT_IDX = 2  # 女儿村 in 17-option submenu
# open menu if not visible
if "可视=false" in (st or ""):
    print("对话栏不可见 → 右键卡重开 (352,194)")
    click(hwnd, 352, 194, rbutton=True)
    time.sleep(1.2)
    st = dialog_state()
    print("重开后:", st)

# 若是卡根菜单(含 门派传送) → 点门派传送
if "门派传送" in (st or "") and "女儿村" not in (st or ""):
    print("在卡根菜单 → 点门派传送 (147,415)")
    click(hwnd, 147, 415); time.sleep(1.0)
    st = dialog_state()
    print("点门派传送后:", st)

print("点击目标门派:", TARGET, "选项#", SECT_OPT_IDX)
# 女儿村 option[2] center: x=119..161, y=392..406 → (140,399)
click(hwnd, 140, 399)
time.sleep(3.0)

new = pkts()
print("点击后包数:", len(new))
newpkts = [p for p in new if p.get("ts", 0) > start]
print("baseline 后新包:", len(newpkts))
for p in newpkts:
    print("SEND:", p.get("ascii"))
print("当前地图:", lua("tostring(tp.当前地图 or '')"))