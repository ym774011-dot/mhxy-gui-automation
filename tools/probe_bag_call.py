# -*- coding: utf-8 -*-
"""探查 道具行囊 对象结构、可用打开方法，及试验 Lua 直开背包"""
import json, urllib.request
GW="http://127.0.0.1:18083"
def lua(code):
    d=json.loads(urllib.request.urlopen(urllib.request.Request(GW+"/api/lua",
        data=json.dumps({"code":code}).encode("utf-8"),
        headers={"Content-Type":"application/json"}),timeout=20).read().decode("utf-8","replace"))
    if d.get("ok") is False: return f"<ERR:{d.get('error')}>"
    return d.get("result",{}).get("value")

print("=== 道具行囊 对象结构（字段+方法）===")
print(lua(r'''
local b = tp.窗口 and tp.窗口.道具行囊
local out={}
if type(b)~="table" then out[1]="无道具行囊"; _G.__out=table.concat(out,"\n"); return end
for k,v in pairs(b) do
  if type(v)=="function" then
    out[#out+1]="  [方法] "..tostring(k)
  elseif type(v)=="table" then
    local n=0; for _ in pairs(v) do n=n+1 end
    out[#out+1]="  [表] "..tostring(k).." (n="..n..")"
  else
    out[#out+1]="  "..tostring(k).." = "..tostring(v)
  end
end
-- 查找 __index 中的方法
local mt = getmetatable(b)
if mt and type(mt.__index)=="table" then
  for k,v in pairs(mt.__index) do
    if type(v)=="function" then out[#out+1]="  [继承方法] "..tostring(k) end
  end
end
_G.__out=table.concat(out,"\n")'''))