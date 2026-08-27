# -*- coding: utf-8 -*-
"""前台 Tab 打开背包：置前 + keybd_event"""
import ctypes, time, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from library.map_packs import MPCG as M
GW="http://127.0.0.1:18083"

def lua(code):
    d = M._http_json(GW, "/api/lua", {"code": code})
    if d.get("ok") is False: return f"<ERR:{d.get('error')}>"
    return d.get("result", {}).get("value")

pid = M._gateway_pid(GW)
hwnd = M._bind_hwnd(GW, pid)
print("hwnd:", hex(hwnd), "pid:", pid)

user32 = ctypes.windll.user32
# 置前台
user32.SetForegroundWindow(hwnd)
time.sleep(0.8)
is_fg = user32.GetForegroundWindow() == hwnd
print("isForeground:", bool(is_fg))

def tab_send():
    # keybd_event Tab
    ctypes.windll.user32.keybd_event(0x09, 0, 0, 0)
    time.sleep(0.05)
    ctypes.windll.user32.keybd_event(0x09, 0, 2, 0)
    time.sleep(0.05)

print("袋可视(前):", lua(r'_G.__out=tostring(tp.窗口 and tp.窗口.道具行囊 and tp.窗口.道具行囊.可视)'))
tab_send()
time.sleep(1.2)
print("袋可视(前台Tab后):", lua(r'_G.__out=tostring(tp.窗口 and tp.窗口.道具行囊 and tp.窗口.道具行囊.可视)'))
# 找卡
print("找卡:", lua(r'''
local bag=tp.窗口 and tp.窗口.道具行囊
local out={}
local card=nil
local function scan(t)
  if type(t)=="table" then
    if type(t.名称)=="string" and tostring(t.名称)=="鲜衣怒马会员卡" then card=true end
    for _,v in pairs(t) do if not card and type(v)=="table" then scan(v) end end
  end
end
scan(bag)
out[1]=card and "找到" or "未找到"
_G.__out=table.concat(out,"\n")'''))