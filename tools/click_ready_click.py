# -*- coding: utf-8 -*-
"""用 MPCG._click（含WM_MOUSEMOVE前置）点「准备好了」"""
import json, urllib.request, time, sys, os
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
if not hwnd:
    print("无 hwnd")
    sys.exit(1)
# 清残留
for _ in range(5):
    v = lua("local d=tp.窗口.对话栏; local x=0 if d and d.可视 then x=1 end; _G.__out=tostring(x)")
    if v == "1":
        M._click(hwnd, 320, 150, rbutton=True); time.sleep(0.3)
    else:
        break
# CALL使者
lua(r'''
local j=tp.场景.假人
local idx=nil
for i=1,#j do
  if type(j[i])=='table' and tostring(j[i].名称 or ''):find('门派闯关') then idx=i end
end
if idx then local o=j[idx]; pcall(function() return o['事件开始'](o) end) end
_G.__out='' ''')
time.sleep(1.2)
print("使者对话:", lua(r'''
local d=tp.窗口.对话栏
_G.__out=tostring(d.可视)..'|'..tostring(d.名称 or '')..'|'..tostring(d.文本内容 or '')'''))
# 用 _click 点 ready 中心 (245,361)
print("点击 ready @(245,361)")
M._click(hwnd, 245, 361)
time.sleep(2)
# 状态
print("点击后对话:", lua(r'''
local d=tp.窗口.对话栏
local out={}
out[1]="可视="..tostring(d.可视).." 名="..tostring(d.名称 or '').." 文="..tostring(d.文本内容 or '')
if d.选项 then
  for i=1,20 do
    local o=d.选项[i]
    if type(o)~='table' then break end
    out[#out+1]=i..':'..tostring(o.跳转链接 or '')
  end
end
_G.__out=table.concat(out,' | ')'''))
print("107计数:", lua(r'''
local n=0
if tp.窗口.任务追踪栏 and tp.窗口.任务追踪栏.数据记录 then
  for i,v in pairs(tp.窗口.任务追踪栏.数据记录) do
    if type(v)=='table' and tostring(v.类型 or v.任务类型 or '')=='107' then n=n+1 end
  end
end
_G.__out=tostring(n)'''))