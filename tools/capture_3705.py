# -*- coding: utf-8 -*-
"""抓取会员传送 3705 包的完整字节，解码字段名（协议重放用）"""
import json, urllib.request, time, sys, binascii
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
if type(opt) == "table" then
  for i = 1, 30 do
    local o = opt[i]
    if type(o) ~= "table" then break end
    out = out .. "|" .. tostring(o.跳转链接 or "")
  end
end
_G.__out = out'''
    return lua(code)

ok = window_manager.bind(pid=17000)
hwnd = getattr(window_manager, "hwnd", None)
print("hwnd=", hwnd)
base = pkts(); start = base[-1].get("ts", 0) if base else 0

st = dialog_state()
if "可视=false" in (st or ""):
    click(hwnd, 352, 194, rbutton=True); time.sleep(1.2)
    st = dialog_state()
if "门派传送" in (st or "") and "女儿村" not in (st or ""):
    click(hwnd, 147, 415); time.sleep(1.0)
    st = dialog_state()
print("菜单:", st)
# 点击 女儿村
click(hwnd, 140, 399)
time.sleep(3.0)

for p in pkts():
    if p.get("ts", 0) > start and "3705" in p.get("ascii",""):
        hx = p.get("hex", "").replace(" ", "")
        raw = bytes.fromhex(hx)
        # 跳过 12 字节头，解 payload
        payload = raw[12:]
        print("=== 3705 完整 hex ===")
        print(hx)
        print("=== payload (gbk 解码) ===")
        try:
            print(payload.decode("gbk"))
        except Exception as e:
            print("decode err", e, payload)
        print("=== payload (utf-8 errors=replace) ===")
        print(payload.decode("utf-8", "replace"))
print("当前地图:", lua("tostring(tp.当前地图 or '')"))