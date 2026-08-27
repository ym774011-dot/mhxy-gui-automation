# -*- coding: utf-8 -*-
"""验证：长安(193,125) CALL 门派闯关使者 → 读取是否弹出新一轮任务"""
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
def close_dialog():
    lp = (320 << 16) | 150
    u.PostMessageW(hwnd, 0x0200, 0, lp); time.sleep(0.1)
    u.PostMessageW(hwnd, 0x0204, 0x0002, lp); time.sleep(0.1)
    u.PostMessageW(hwnd, 0x0205, 0, lp); time.sleep(0.8)

# 1) 关掉会员卡菜单
close_dialog()
# 2) 瞬移到长安(193,125)
r = M._gateway_teleport_xy(GW, 193, 125)
print("瞬移(193,125):", r)
time.sleep(1)
# 3) 找使者
s = M._lua_find_guard(GW, "门派闯关") or {}
print("找使者(按'门派闯关'):", s)
code = r'''
local j=tp.场景.假人
local found=nil
for i=1,#j do
  if type(j[i])=='table' and tostring(j[i].名称 or ''):find('门派闯关') then found={i, tostring(j[i].名称 or '')} end
end
if not found then _G.__out='NO'; return end
local o=j[found[1]]
local ok,rr=pcall(function() return o['事件开始'](o) end)
_G.__out=tostring(found[1])..','..found[2]..',call='..tostring(ok)'''
print("CALL使者:", lua(code))
time.sleep(1)
# 4) 读对话栏
print("对话栏:", lua(r'''
local d=tp.窗口.对话栏
local out={}
out[1]="可视化="..tostring(d and d.可视).." 名="..tostring(d and d.名称 or '').." 文="..tostring(d and d.文本内容 or '')
if d and d.选项 then
  for i=1,20 do
    local o=d.选项[i]
    if type(o)~='table' then break end
    out[#out+1]=i..':'..tostring(o.文字 or o.跳转链接 or '')
  end
end
_G.__out=table.concat(out,' | ')'''))