# -*- coding: utf-8 -*-
"""ALT+E 打开背包 → 找会员卡"""
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
user32.ShowWindow(hwnd, 9); user32.SetForegroundWindow(hwnd); time.sleep(0.8)

def alt_e():
    VK_MENU=0x12; VK_E=0x45
    user32.keybd_event(VK_MENU,0,0,0); time.sleep(0.08)
    user32.keybd_event(VK_E,0,0,0); time.sleep(0.08)
    user32.keybd_event(VK_E,0,2,0); time.sleep(0.08)
    user32.keybd_event(VK_MENU,0,2,0); time.sleep(0.08)

print("袋可视(前):", lua(r'_G.__out=tostring(tp.窗口 and tp.窗口.道具行囊 and tp.窗口.道具行囊.可视)'))
alt_e()
time.sleep(1.2)
print("袋可视(ALT+E后):", lua(r'_G.__out=tostring(tp.窗口 and tp.窗口.道具行囊 and tp.窗口.道具行囊.可视)'))
print("找卡:", lua(r'''
local bag=tp.窗口 and tp.窗口.道具行囊
local out={}; local card=nil
local function scan(t,kk)
  if type(t)=="table" then
    if type(t.名称)=="string" and tostring(t.名称)=="鲜衣怒马会员卡" then card=kk end
    for k,v in pairs(t) do if not card and type(v)=="table" then scan(v,tostring(kk).."."..tostring(k)) end end
  end
end
scan(bag,"bag")
out[1]=card and ("找到 @"..card) or "未找到"
_G.__out=table.concat(out,"\n")'''))