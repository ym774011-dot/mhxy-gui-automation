# -*- coding: utf-8 -*-
"""点击请出招吧后检查界面状态"""
import json, urllib.request
GW="http://127.0.0.1:18083"
def jget(path,data=None):
    d=json.loads(urllib.request.urlopen(urllib.request.Request(GW+path,
        data=json.dumps(data).encode("utf-8") if data else None,
        headers={"Content-Type":"application/json"} if data else {}),timeout=20
      ).read().decode("utf-8","replace"))
    return d
def lua(code):
    d=jget("/api/lua",{"code":code})
    if d.get("ok") is False: return f"<ERR:{d.get('error')}>"
    return d.get("result",{}).get("value")

print(lua(r'''
local out={}
-- 战斗相关字段探测
for _,f in ipairs({"战斗","战斗系统","战斗界面","战斗进行","战斗中"}) do
  local v=tp[f]
  if v~=nil then
    out[#out+1]=f.." = "..type(v)
    if type(v)=="table" then
      for k2,v2 in pairs(v) do
        if type(v2)~="table" then out[#out+1]="   "..f.."."..tostring(k2).."="..tostring(v2) end
      end
    end
  else
    out[#out+1]=f.." = nil"
  end
end
-- 对话栏状态
local d=tp.窗口.对话栏
out[#out+1]="对话栏.可视="..tostring(d and d.可视).." 名称="..tostring(d and d.名称).." 文本="..tostring(d and d.文本内容 or "")
-- 假人护法是否还在
local found=false
for i,o in pairs(tp.场景.假人 or {}) do
  if type(o)=="table" and tostring(o.名称 or "")=="大唐官府护法" then found=true break end
end
out[#out+1]="大唐官府护法 仍在场景="..tostring(found)
_G.__out=table.concat(out,"\n")'''))