# -*- coding: utf-8 -*-
"""确认魔王寨考验结果 + 读取最新任务目标"""
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
out[1]="名称="..tostring(d and d.名称).." 可视="..tostring(d and d.可视).." 文本="..tostring(d and d.文本内容 or "")
_G.__out=table.concat(out,"\n")'''))
print("任务记录:", lua(r'''
local t=tp.窗口.任务追踪栏.数据记录
local hit=nil
if type(t)=="table" then for _,v in pairs(t) do if type(v)=="table" and tostring(v.类型 or "")=="107" then hit=v end end end
if not hit then _G.__out="NO"; return end
local seq={}
for i=1,20 do local x=hit.闯关序列 and hit.闯关序列[i]; if x==nil then break end seq[#seq+1]=tostring(x) end
_G.__out="当前序列="..tostring(hit.当前序列).." 闯关序列={"..table.concat(seq,",").."}"'''))