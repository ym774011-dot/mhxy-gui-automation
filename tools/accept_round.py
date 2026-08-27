# -*- coding: utf-8 -*-
"""干净重做：关残留菜单 → CALL使者 → 点「准备好了」接受 → 确认任务激活"""
import json, urllib.request, time, os, sys, ctypes
GW = "http://127.0.0.1:18083"
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(ROOT))
from library.map_packs import MPCG as M
from core.window_manager import window_manager
def lua(code):
    d = json.loads(urllib.request.urlopen(urllib.request.Request(
        GW + "/api/lua", data=json.dumps({"code": code}).encode("utf-8"),
        headers={"Content-Type": "application/json"}), timeout=20).read().decode("utf-8", "replace"))
    if d.get("ok") is False:
        return f"<ERR:{d.get('error')}>"
    return d.get("result", {}).get("value")

pid = (json.loads(urllib.request.urlopen(GW + "/api/status", timeout=10)
                  .read().decode("utf-8", "replace")).get("result") or {}).get("pid")
window_manager.bind(pid=int(pid))
hwnd = getattr(window_manager, "hwnd", None)
u = ctypes.windll.user32
def rclick(x, y):
    lp = (int(y) << 16) | (int(x) & 0xFFFF)
    u.PostMessageW(hwnd, 0x0200, 0, lp); time.sleep(0.1)
    u.PostMessageW(hwnd, 0x0204, 0x0002, lp); time.sleep(0.1)
    u.PostMessageW(hwnd, 0x0205, 0, lp); time.sleep(0.6)
def lclick(x, y):
    lp = (int(y) << 16) | (int(x) & 0xFFFF)
    u.PostMessageW(hwnd, 0x0200, 0, lp); time.sleep(0.1)
    u.PostMessageW(hwnd, 0x0204, 0x0001, lp); time.sleep(0.1)
    u.PostMessageW(hwnd, 0x0205, 0, lp); time.sleep(0.6)
def close_any():
    v = lua("_G.__out = tostring(tp.窗口.对话栏.可视 or false)")
    if v == "true":
        rclick(320, 150)

# 1) 关闭一切残留对话框 & 会员菜单
for _ in range(4):
    close_any(); time.sleep(0.3)
print("清理后对话栏:", lua(r'''
local d=tp.窗口.对话栏
_G.__out="可视="..tostring(d and d.可视).." 名="..tostring(d and d.名称 or '').." 文="..tostring(d and d.文本内容 or '')'''))

# 2) 确保在长安(193,125)
M._gateway_teleport_xy(GW, 193, 125); time.sleep(1)

# 3) CALL 使者（按名称含'门派闯关'）
c = lua(r'''
local j=tp.场景.假人
local idx=nil
for i=1,#j do
  if type(j[i])=='table' and tostring(j[i].名称 or ''):find('门派闯关') then idx=i end
end
if not idx then _G.__out='NO'; return end
local o=j[idx]
local ok=pcall(function() return o['事件开始'](o) end)
_G.__out='IDX='..idx..' ok='..tostring(ok)''')
print("CALL使者:", c)
time.sleep(1.2)
print("使者对话:", lua(r'''
local d=tp.窗口.对话栏
local out={}
out[1]="可视="..tostring(d and d.可视).." 名="..tostring(d and d.名称 or '').." 文="..tostring(d and d.文本内容 or '')
if d and d.选项 then
  for i=1,20 do
    local o=d.选项[i]
    if type(o)~='table' then break end
    out[#out+1]=i..':'..tostring(o.文字 or o.跳转链接 or '')
  end
end
_G.__out=table.concat(out,' | ')'''))