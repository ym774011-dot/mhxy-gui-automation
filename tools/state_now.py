# -*- coding: utf-8 -*-
"""检查当前战斗/对话栏/地图状态"""
import json, urllib.request
GW="http://127.0.0.1:18083"
def lua(code):
    d=json.loads(urllib.request.urlopen(urllib.request.Request(GW+"/api/lua",
        data=json.dumps({"code":code}).encode("utf-8"),
        headers={"Content-Type":"application/json"}),timeout=20).read().decode("utf-8","replace"))
    if d.get("ok") is False: return f"<ERR:{d.get('error')}>"
    return d.get("result",{}).get("value")
print(lua(r'''
local out={}
out[1]="当前地图="..tostring(tp.当前地图)
out[2]="战斗中="..tostring(tp.战斗中)
local d=tp.窗口.对话栏
out[3]="对话栏 名称="..tostring(d and d.名称).." 可视="..tostring(d and d.可视)
out[4]="对话文本="..tostring(d and d.文本内容 or "")
local opt=d and d.选项
local links={}
if type(opt)=="table" then for i=1,20 do local o=opt[i]; if type(o)~="table" then break end links[#links+1]=tostring(o.跳转链接 or o.文字 or "") end end
out[5]="对话选项="..table.concat(links,"|")
_G.__out=table.concat(out,"\n")'''))