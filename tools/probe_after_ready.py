# -*- coding: utf-8 -*-
"""CALL使者→点ready→打开任务追踪栏→读107记录+任务栏文本，排查是否激活"""
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
def lclick(x, y):
    lp = (int(y) << 16) | (int(x) & 0xFFFF)
    u.PostMessageW(hwnd, 0x0200, 0, lp); time.sleep(0.08)
    u.PostMessageW(hwnd, 0x0204, 0x0001, lp); time.sleep(0.08)
    u.PostMessageW(hwnd, 0x0205, 0, lp); time.sleep(0.4)
def rclick(x, y):
    lp = (int(y) << 16) | (int(x) & 0xFFFF)
    u.PostMessageW(hwnd, 0x0200, 0, lp); time.sleep(0.06)
    u.PostMessageW(hwnd, 0x0204, 0x0002, lp); time.sleep(0.06)
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
# 点选项1 中心 (245,361)
lclick(245, 361)
time.sleep(1)
print("ready后对话:", lua(r'''
local d=tp.窗口.对话栏
_G.__out="可视="..tostring(d.可视).." 名="..tostring(d.名称 or '').." 文="..tostring(d.文本内容 or '')'''))
# 打开任务追踪栏
try:
    M.MPCG_open_taskbar(gateway=GW, verbose=True)
except Exception as e:
    print("open_taskbar err", e)
time.sleep(1)
# 读 data记录 全量（打印所有记录类型）
print("任务追踪栏数据记录:", lua(r'''
local tk=tp.窗口.任务追踪栏
local out={}
out[1]="可视栏="..tostring(tk and tk.可视 or false)
if tk and tk.数据记录 then
  local n=0
  for i,v in pairs(tk.数据记录) do
    if type(v)=='table' then
      n=n+1
      out[#out+1]='#type='..tostring(v.类型 or v.任务类型 or '')..' 名='..tostring(v.任务名 or v.名称 or '')
    end
  end
  out[2]="记录数="..n
end
_G.__out=table.concat(out,' | ')'''))
# 任务栏可见文本
print("任务栏文本:", lua(r'''
local tk=tp.窗口.任务追踪栏
_G.__out=tostring(tk and tk.文本 or tk and tk.文本内容 or '')'''))