# -*- coding: utf-8 -*-
"""打开背包 → 找会员卡 → 确认位置"""
import json, sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from library.map_packs import MPCG as M

GW="http://127.0.0.1:18083"
pid = M._gateway_pid(GW)
hwnd = M._bind_hwnd(GW, pid)
print("hwnd:", hwnd, "pid:", pid)

def lua(code):
    d = M._http_json(GW, "/api/lua", {"code": code})
    if d.get("ok") is False: return f"<ERR:{d.get('error')}>"
    return d.get("result", {}).get("value")

# 1) 当前袋状态
print("袋可视(开前):", lua(r'''
local bag=tp.窗口 and tp.窗口.道具行囊
_G.__out=tostring(bag and bag.可视)'''))

# 2) 按 Tab 打开背包
print("按 Tab 打开背包...")
M._press_key(hwnd, M._VK_TAB)
time.sleep(1.2)
print("袋可视(开后):", lua(r'''
local bag=tp.窗口 and tp.窗口.道具行囊
_G.__out=tostring(bag and bag.可视)'''))

# 3) 找会员卡
print("找会员卡:")
r = lua(r'''
local bag=tp.窗口 and tp.窗口.道具行囊
local out={}
local card=nil
local function scan(tbl, key)
  if type(tbl)=="table" then
    if type(tbl.名称)=="string" and tostring(tbl.名称)=="鲜衣怒马会员卡" then
      card=tbl; out[#out+1]="命中["..key.."] x="..tostring(tbl.x or tbl.格子x or '?').." y="..tostring(tbl.y or tbl.格子y or '?')
    end
    for k,v in pairs(tbl) do
      if card==nil and type(v)=="table" then scan(v, tostring(key).."."..tostring(k)) end
    end
  end
end
scan(bag,"bag")
if not card then
  -- 兜底扫描嵌套(行囊在窗口下可能多层)
  out[#out+1]="未找到会员卡"
end
_G.__out=table.concat(out,"\n")''')
print(r)