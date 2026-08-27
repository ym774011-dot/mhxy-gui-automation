# -*- coding: utf-8 -*-
"""探查大唐官府→长安的传送口"""
import json, urllib.request, time, sys, os
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

print("出发地图:", lua("_G.__out= tostring(tp.当前地图 or '')"))
r = M.MPCG_teleport_sect(map_name="大唐官府", gateway=GW, verbose=True)
print("传送大唐官府:", json.dumps(r, ensure_ascii=False))
time.sleep(1)
print("到步地图:", lua("_G.__out= tostring(tp.当前地图 or '')"))
print("大唐官府传送表:", lua(r'''
local t=tp.场景.传送
local out={}
out[1]="条数="..tostring(type(t)=='table' and #t or 0)
if type(t)=='table' then
  for i=1,#t do
    local s=tostring(t[i].切换 or '')
    if string.len(s)>0 then
      local x,y='',''
      if t[i].坐标 then x=tostring(t[i].坐标.x or ''); y=tostring(t[i].坐标.y or '') end
      out[#out+1]=i..':'..s..'@'..x..','..y
    end
  end
end
_G.__out=table.concat(out,' | ')'''))