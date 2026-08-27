# -*- coding: utf-8 -*-
"""确认是否已进入战斗"""
import json, urllib.request
GW="http://127.0.0.1:18083"
def lua(code):
    d=json.loads(urllib.request.urlopen(urllib.request.Request(GW+"/api/lua",
        data=json.dumps({"code":code}).encode("utf-8"),
        headers={"Content-Type":"application/json"}),timeout=20).read().decode("utf-8","replace"))
    if d.get("ok") is False: return f"<ERR:{d.get('error')}>"
    return d.get("result",{}).get("value")
print("战斗状态:", lua(r'''
local out={}
out[1]="tp.战斗="..type(tp.战斗)
out[2]="tp.战斗.进行中="..tostring(tp.战斗 and tp.战斗.进行中)
out[3]="tp.战斗.是否进行="..tostring(tp.战斗 and tp.战斗.是否进行)
out[4]="等待中="..tostring((tp.战斗 and tp.战斗.等待中) or (type(tp.战斗)=='table' and tp.战斗.进行中 or false))
_G.__out=table.concat(out,"\n")'''))
print("当前地图:", lua(r"""_G.__out=tostring(tp.当前地图 or "")"""))