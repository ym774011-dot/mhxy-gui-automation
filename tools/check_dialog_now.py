# -*- coding: utf-8 -*-
"""检查当前对话栏状态与选项"""
import json, urllib.request
GW="http://127.0.0.1:18083"
def lua(code):
    d=json.loads(urllib.request.urlopen(urllib.request.Request(GW+"/api/lua",
        data=json.dumps({"code":code}).encode("utf-8"),
        headers={"Content-Type":"application/json"}),timeout=20).read().decode("utf-8","replace"))
    if d.get("ok") is False: return f"<ERR:{d.get('error')}>"
    return d.get("result",{}).get("value")
print("对话栏:", lua(r'''
local d=tp.窗口.对话栏
local out={}
out[1]="可视="..tostring(d and d.可视).." 名称="..tostring(d and d.名称).." 文本="..tostring(d and d.文本内容 or "")
local opt=d and d.选项
local links={}
if type(opt)=="table" then
  for i=1,20 do
    local o=opt[i]
    if type(o)~="table" then break end
    local j=o.选中判断
    local cx,cy="",""
    if type(j)=="table" then cx=tostring((tonumber(j.x or 0)+tonumber(j.x2 or 0))/2); cy=tostring((tonumber(j.y or 0)+tonumber(j.y2 or 0))/2) end
    links[#links+1]="["..i.."]="..tostring(o.跳转链接 or o.文字 or "").."@"..cx..","..cy
  end
end
out[2]="选项: "..table.concat(links," | ")
out[3]="当前地图="..tostring(tp.当前地图)
_G.__out=table.concat(out,"\n")'''))