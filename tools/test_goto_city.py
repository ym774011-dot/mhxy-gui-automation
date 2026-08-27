# -*- coding: utf-8 -*-
"""实测 MPCG_goto_city：回长安(193,125) → CALL使者 → 点准备好了 → 确认任务激活"""
import json, urllib.request, time, sys, os, ctypes
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(ROOT))
from library.map_packs import MPCG as M
from core.window_manager import window_manager
GW = "http://127.0.0.1:18083"
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
    u.PostMessageW(hwnd, 0x0205, 0, lp); time.sleep(0.5)
def lclick(x, y):
    lp = (int(y) << 16) | (int(x) & 0xFFFF)
    u.PostMessageW(hwnd, 0x0200, 0, lp); time.sleep(0.1)
    u.PostMessageW(hwnd, 0x0204, 0x0001, lp); time.sleep(0.1)
    u.PostMessageW(hwnd, 0x0205, 0, lp); time.sleep(0.5)

# 起于大唐官府(1198)
print("起于地图:", lua("_G.__out=tostring(tp.当前地图 or '')"))
r = M.MPCG_goto_city(gateway=GW, verbose=True)
print("goto_city:", json.dumps(r, ensure_ascii=False))
time.sleep(1)
print("到步地图:", lua("_G.__out=tostring(tp.当前地图 or '')"))

# 找使者
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