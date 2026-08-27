# -*- coding: utf-8 -*-
"""完整 dump 使者对话窗结构：对话栏所有键 + 选项1所有键"""
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
def rclick(x, y):
    lp = (int(y) << 16) | (int(x) & 0xFFFF)
    u.PostMessageW(hwnd, 0x0200, 0, lp); time.sleep(0.06)
    u.PostMessageW(hwnd, 0x0204, 0x0002, lp); time.sleep(0.06)
    u.PostMessageW(hwnd, 0x0205, 0, lp); time.sleep(0.3)
def vis():
    return lua("local d=tp.窗口.对话栏; local x=0 if d and d.可视 then x=1 end; _G.__out=tostring(x)") == "1"
for _ in range(5):
    if vis(): rclick(320, 150)
    else: break
    time.sleep(0.3)
lua(r'''
local j=tp.场景.假人
local idx=nil
for i=1,#j do
  if type(j[i])=='table' and tostring(j[i].名称 or ''):find('门派闯关') then idx=i end
end
if idx then local o=j[idx]; pcall(function() return o['事件开始'](o) end) end
_G.__out='' ''')
time.sleep(1.2)
# dump 对话栏所有键（含类型）
print("对话栏键:", lua(r'''
local d=tp.窗口.对话栏
local ks={}
for k,v in pairs(d) do
  if type(k)=='string' and type(v)~='table' then ks[#ks+1]=k..'='..tostring(v)
  elseif type(k)=='string' then ks[#ks+1]=k..':T'
  end
end
table.sort(ks)
_G.__out=table.concat(ks,' | ')'''))
print("\n选项1所有键:", lua(r'''
local o=tp.窗口.对话栏.选项[1]
local ks={}
for k,v in pairs(o) do
  if type(k)=='string' then
    if type(v)=='table' then
      local sub={}
      for kk,vv in pairs(v) do sub[#sub+1]=kk..'='..tostring(vv) end
      table.sort(sub)
      ks[#ks+1]=k..'{'..table.concat(sub,',')..'}'
    else
      ks[#ks+1]=k..'='..tostring(v)
    end
  end
end
table.sort(ks)
_G.__out=table.concat(ks,' | ')'''))