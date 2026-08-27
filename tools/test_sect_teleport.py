# -*- coding: utf-8 -*-
"""测试：点击门派传子菜单里的「大唐官府」→ 验证是否真实跨图"""
import json, urllib.request, time, sys
import ctypes

sys.path.insert(0, r"e:\DS\mhxy-gui-automation")
from core.window_manager import window_manager

GW = "http://127.0.0.1:18083"
PID = 17000
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
MK_LBUTTON = 0x0001

def _lp(x, y):
    return (int(y) << 16) | (int(x) & 0xFFFF)

def lua(code):
    req = urllib.request.Request(GW + "/api/lua",
        data=json.dumps({"code": code}).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8", "replace"))

def map_now():
    d = lua("tp.窗口.小地图.地图名称")
    m = d.get("result", {}).get("value")
    e = lua("tostring(tp.当前地图 or '')")
    return m, e

def click(hwnd, cx, cy):
    u = ctypes.windll.user32
    u.PostMessageW(hwnd, WM_MOUSEMOVE, 0, _lp(cx, cy)); time.sleep(0.1)
    u.PostMessageW(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, _lp(cx, cy)); time.sleep(0.1)
    u.PostMessageW(hwnd, WM_LBUTTONUP, 0, _lp(cx, cy))

ok = window_manager.bind(pid=PID)
hwnd = getattr(window_manager, "hwnd", None)
print("绑定:", ok, "hwnd=", hwnd)

before = map_now()
print("点击前地图:", before)

# 点击 大唐官府 (选项5 中心 147,465)
click(hwnd, 147, 465)
print("已点击 大唐官府，等待跨图...")
time.sleep(3.0)

after = map_now()
print("点击后地图:", after)