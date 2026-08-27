# -*- coding: utf-8 -*-
"""正确枚举背包结构 + 探测传送护卫"""
import json, urllib.request, time
GW="http://127.0.0.1:18083"
def lua(code):
    d=json.loads(urllib.request.urlopen(urllib.request.Request(GW+"/api/lua",
        data=json.dumps({"code":code}).encode("utf-8"),
        headers={"Content-Type":"application/json"}),timeout=20).read().decode("utf-8","replace"))
    if d.get("ok") is False: return f"<ERR:{d.get('error')}>"
    return d.get("result",{}).get("value")

print("=== 道具行囊 结构 dump（前若干字段+物品计数）===")
print(lua(r'''
local bag=tp.窗口 and tp.窗口.道具行囊
local out={}
out[1]="bag type="..type(bag)
if type(bag)=="table" then
  for k,v in pairs(bag) do
    if type(v)=="table" then
      local n=0; for _ in pairs(v) do n=n+1 end
      out[#out+1]=tostring(k).."=table(n="..n..")"
    else
      out[#out+1]=tostring(k).."="..tostring(v)
    end
  end
end
_G.__out=table.concat(out,"\n")'''))

print("\n=== 物品数组索引快照（若有连续索引）===")
print(lua(r'''
local bag=tp.窗口 and tp.窗口.道具行囊
local out={}
local it=bag and bag.物品 or bag and bag.道具
if type(it)=="table" then
  for i=1,40 do
    local v=it[i]
    if type(v)=="table" then
      out[#out+1]="["..i.."]="..tostring(v.名称 or "?")
    elseif v==nil then
      if i>1 then break end
    end
  end
else
  out[1]="no 物品/道具 array type="..type(it)
end
_G.__out=table.concat(out,"\n")'''))