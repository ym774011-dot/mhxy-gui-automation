# -*- coding: utf-8 -*-
"""点击 会员卡菜单「门派传送」→ 打开 15门派子菜单 → dump 选项"""
import json, urllib.request, time
import sys
import ctypes
from ctypes import wintypes

sys.path.insert(0, r"e:\DS\mhxy-gui-automation")
try:
    from core.window_manager import window_manager
except Exception as e:
    print("导入窗口管理器失败:", e); sys.exit(1)

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

def dump_opts(tag):
    code = r'''
local d = tp.窗口.对话栏
local out = {}
out[#out+1] = "名称=" .. tostring(d and d.名称 or "")
local opt = d and d.选项
local n = 0
if type(opt) == "table" then for _ in pairs(opt) do n = n + 1 end end
out[#out+1] = "选项数=" .. tostring(n)
for i = 1, math.min(n, 60) do
  local o = opt[i]
  if type(o) == "table" then
    local jl = tostring(o.跳转链接 or "")
    local bc = tostring(o.基本内容 or "")
    out[#out+1] = "  [" .. i .. "] 跳转=" .. jl .. " | 内容=" .. bc
  end
end
_G.__out = table.concat(out, "\n")'''
    d = lua(code)
    print(f"=== {tag} ===")
    print(d.get("result", {}).get("value") or ("<ERR: %s>" % d.get("error")))

# 绑定窗口
ok = window_manager.bind(pid=PID)
print("绑定:", ok)
hwnd = getattr(window_manager, "hwnd", None)
print("hwnd =", hwnd)
if not hwnd:
    print("无窗口句柄，退出"); sys.exit(1)

# 首次确认卡片菜单选项
dump_opts("卡片菜单(点击前)")

# 点击「门派传送」(选项[2] 中心 ~147,415)
cx, cy = 147, 415
user32 = ctypes.windll.user32
user32.PostMessageW(hwnd, WM_MOUSEMOVE, 0, _lp(cx, cy))
time.sleep(0.1)
user32.PostMessageW(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, _lp(cx, cy))
time.sleep(0.1)
user32.PostMessageW(hwnd, WM_LBUTTONUP, 0, _lp(cx, cy))
print(f"已点击 ({cx},{cy}) 门派传送项，等待子菜单...")
time.sleep(2.0)

dump_opts("门派传送子菜单(点击后)")