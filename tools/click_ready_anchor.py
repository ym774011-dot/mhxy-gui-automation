# -*- coding: utf-8 -*-
"""用选中判断原始坐标 (119,354) 点「准备好了」"""
import json, urllib.request, time, sys, os, ctypes
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(ROOT))
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
def lclick(x, y):
    lp = (int(y) << 16) | (int(x) & 0xFFFF)
    u.PostMessageW(hwnd, 0x0200, 0, lp); time.sleep(0.08)
    u.PostMessageW(hwnd, 0x0204, 0x0001, lp); time.sleep(0.08)
    u.PostMessageW(hwnd, 0x0205, 0, lp); time.sleep(0.4)
def rclick(x, y):
    lp = (int(y) << 16) | (int(x) & 0xFFFF)
    u.PostMessageW(hwnd, 0x0200, 0, lp); time.sleep(0.08)
    u.PostMessageW(hwnd, 0x0204, 0x0002, lp); time.sleep(0.08)
    u.PostMessageW(hwnd, 0x0205, 0, lp); time.sleep(0.3)
def vis():
    return lua("local d=tp.窗口.对话栏; local x=0 if d and d.可视 then x=1 end; _G.__out=tostring(x)") == "1"
# 清残留
for _ in range(5):
    if vis(): rclick(320, 150)
    else: break
    time.sleep(0.3)
# CALL使者
lua(r'''
local j=tp.场景.假人
local idx=nil
for i=1,#j do
  if type(j[i])=='table' and tostring(j[i].名称 or ''):find('门派闯关') then idx=i end
end
if idx then local o=j[idx]; pcall(function() return o['事件开始'](o) end) end
_G.__out=tostring(idx and 'ok' or 'NO')''')
time.sleep(1.2)
appear = lua(r'''
local d=tp.窗口.对话栏
local out={}
out[1]="可视="..tostring(d.可视).." 名="..tostring(d.名称 or '').." 文="..tostring(d.文本内容 or '')
if d.选项 then
  for i=1,20 do
    local o=d.选项[i]
    if type(o)~='table' then break end
    local jj=o.选中判断
    out[#out+1]=i..':'..tostring(o.跳转 or o.跳转链接 or '')..'@x='..tostring(jj and jj.x or '')..',y='..tostring(jj and jj.y or '')..',x2='..tostring(jj and jj.x2 or '')..',y2='..tostring(jj and jj.y2 or '')..',cx='..tostring(d.客户端动画 or '')..',dx='..tostring(d.x or '')
  end
end
_G.__out=table.concat(out,' | ')''')
print("对话:", appear)
# 用选中判断 x,y 点击选项1
xy = lua(r'''
local jj=nil
local d=tp.窗口.对话栏
if d.选项 then local o=d.选项[1]; jj=(type(o)=='table') and o.选中判断 end
_G.__out=jj and (tostring(jj.x)..','..tostring(jj.y)) or '' ''')
print("选项1 判断锚点:", xy)
if xy and ',' in xy:
    px, py = map(float, xy.split(","))
    print(f"点击 准备好了 @ ({int(px)},{int(py)})")
    lclick(px, py)
time.sleep(2.5)
print("点击后对话:", lua(r'''
local d=tp.窗口.对话栏
local out={}
out[1]="可视="..tostring(d.可视).." 名="..tostring(d.名称 or '').." 文="..tostring(d.文本内容 or '')
if d.选项 then
  for i=1,20 do
    local o=d.选项[i]
    if type(o)~='table' then break end
    out[#out+1]=i..':'..tostring(o.跳转 or o.跳转链接 or '')
  end
end
_G.__out=table.concat(out,' | ')'''))
print("107:", lua(r'''
local n=0
if tp.窗口.任务追踪栏 and tp.窗口.任务追踪栏.数据记录 then
  for i,v in pairs(tp.窗口.任务追踪栏.数据记录) do
    if type(v)=='table' and tostring(v.类型 or '')=='107' then n=n+1 end
  end
end
_G.__out=tostring(n)'''))