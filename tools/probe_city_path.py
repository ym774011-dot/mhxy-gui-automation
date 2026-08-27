# -*- coding: utf-8 -*-
"""探查：当前地图 + 场景传送表是否有到长安/城市 + 会员卡根菜单选项"""
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

# 1) 当前地图 + 传送表(含 长安/建邺/城市 关键字)
print(lua(r'''
local out={"地图="..tostring(tp.当前地图)}
local t=tp.场景.传送
out[2]="传送条数="..tostring(type(t)=='table' and #t or 0)
if type(t)=='table' then
  local hit={}
  for i=1,#t do
    local s=tostring(t[i].切换 or '')
    if string.find(s,'长安') or string.find(s,'建邺') or string.find(s,'府') then hit[#hit+1]=i..':'..s end
  end
  out[3]="城市相关="..table.concat(hit,' | ')
end
_G.__out=table.concat(out,'\n')'''))

# 2) 会员卡根菜单（右键开卡）
pid = (json.loads(urllib.request.urlopen(GW + "/api/status", timeout=10)
                  .read().decode("utf-8", "replace")).get("result") or {}).get("pid")
window_manager.bind(pid=int(pid))
hwnd = getattr(window_manager, "hwnd", None)
u = ctypes.windll.user32
# 确保袋开
r = M._lua_expr(GW, "tostring(tp.窗口.道具行囊.可视 or false)")
if r != "true":
    M._open_bag(GW)
    time.sleep(1)
# 读会员卡坐标
card = lua(r'''
local card=nil
if tp.窗口.道具行囊 and tp.窗口.道具行囊.物品 then
  for k,it in pairs(tp.窗口.道具行囊.物品) do
    if type(it)=='table' and tostring(it.名称 or '')=='鲜衣怒马会员卡' then card=it end
  end
end
_G.__out=card and (tostring(card.x)..','..tostring(card.y)) or 'nil' ''')
print("会员卡坐标:", card)
if card and card != "nil":
    cx, cy = map(int, card.split(","))
    lp = (cy << 16) | (cx & 0xFFFF)
    u.PostMessageW(hwnd, 0x0200, 0, lp); time.sleep(0.1)
    u.PostMessageW(hwnd, 0x0204, 0x0002, lp); time.sleep(0.1)
    u.PostMessageW(hwnd, 0x0205, 0, lp)
    time.sleep(1.3)
    print("会员卡根菜单:", lua(r'''
local d=tp.窗口.对话栏
local out={}
if d and d.选项 then
  for i=1,20 do
    local o=d.选项[i]
    if type(o)~='table' then break end
    out[#out+1]=i..':'..tostring(o.文字 or o.跳转链接 or '')
  end
end
_G.__out=table.concat(out,' | ')'''))