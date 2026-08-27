# -*- coding: utf-8 -*-
"""诊断当前真实状态：地图/任务记录/场景假人名"""
import json, urllib.request, sys, os
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(ROOT))
from library.map_packs import MPCG as M
GW = "http://127.0.0.1:18083"
def lua(code):
    d = json.loads(urllib.request.urlopen(urllib.request.Request(
        GW + "/api/lua", data=json.dumps({"code": code}).encode("utf-8"),
        headers={"Content-Type": "application/json"}), timeout=20).read().decode("utf-8", "replace"))
    if d.get("ok") is False:
        return f"<ERR:{d.get('error')}>"
    return d.get("result", {}).get("value")
print("地图=", lua("_G.__out= tostring(tp.当前地图 or '')"))
print("门派闯关107=", lua(r'''
local r=0
if tp.窗口.任务追踪栏 and tp.窗口.任务追踪栏.数据记录 then
  for i,v in pairs(tp.窗口.任务追踪栏.数据记录) do
    if type(v)=='table' and tostring(v.类型 or '')=='107' then r=r+1 end
  end
end
_G.__out=tostring(r)'''))
print("战斗=", lua("_G.__out= tostring(tp.战斗中 or false)"))
print("场景NPC:", lua(r'''
local j=tp.场景.假人
local names={}
if type(j)=='table' then
  for i=1,#j do
    if type(j[i])=='table' and tostring(j[i].名称 or '')~='' then names[#names+1]=tostring(j[i].名称) end
    if #names>=40 then break end
  end
end
_G.__out=table.concat(names,' | ')'''))