# -*- coding: utf-8 -*-
"""关闭完成确认弹窗：先 ESC，后右键场景空白（用 window_manager 的 hwnd）"""
import json, urllib.request, time, os, sys, ctypes
GW = "http://127.0.0.1:18083"
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(ROOT))
def lua(code):
    d = json.loads(urllib.request.urlopen(urllib.request.Request(
        GW + "/api/lua", data=json.dumps({"code": code}).encode("utf-8"),
        headers={"Content-Type": "application/json"}), timeout=20).read().decode("utf-8", "replace"))
    if d.get("ok") is False:
        return f"<ERR:{d.get('error')}>"
    return d.get("result", {}).get("value")
def visible():
    return (lua("_G.__out=tostring(tp.窗口.对话栏.可视 or false)") or "").strip()

from core.window_manager import window_manager
pid = (json.loads(urllib.request.urlopen(GW + "/api/status", timeout=10)
                  .read().decode("utf-8", "replace")).get("result") or {}).get("pid")
print("pid=", pid)
window_manager.bind(pid=pid)
hwnd = getattr(window_manager, "hwnd", None)
print("hwnd=", hwnd)
u = ctypes.windll.user32

def rclick(cx, cy):
    lp = (int(cy) << 16) | (int(cx) & 0xFFFF)
    u.PostMessageW(hwnd, 0x0200, 0, lp); time.sleep(0.1)
    u.PostMessageW(hwnd, 0x0204, 0x0002, lp); time.sleep(0.1)
    u.PostMessageW(hwnd, 0x0205, 0, lp)

print("关闭前可视=", visible())
# 1) ESC
print("按 ESC")
u.PostMessageW(hwnd, 0x0100, 0x1B, 0)
u.PostMessageW(hwnd, 0x0101, 0x1B, 0)
time.sleep(1.0)
print("ESC 后可视=", visible())
if visible() == "true":
    # 2) 右键场景空白处（对话框在 x=100,y=310，尝试右键其标题/空白区）
    print("右键尝试点 (150,320)")
    rclick(150, 320)
    time.sleep(1.0)
    print("右键后可视=", visible())