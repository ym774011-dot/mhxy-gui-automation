# -*- coding: utf-8 -*-
"""全面排查：所有背包物品 + 场景中的任务/传送NPC"""
import json, urllib.request
GW="http://127.0.0.1:18083"
def lua(code):
    d=json.loads(urllib.request.urlopen(urllib.request.Request(GW+"/api/lua",
        data=json.dumps({"code":code}).encode("utf-8"),
        headers={"Content-Type":"application/json"}),timeout=20).read().decode("utf-8","replace"))
    if d.get("ok") is False: return f"<ERR:{d.get('error')}>"
    return d.get("result",{}).get("value")

print("=== 道具行囊.物品 全部名称 ===")
print(lua(r'''
local bag=tp.窗口 and tp.窗口.道具行囊
local out={}
if type(bag)=="table" and type(bag.物品)=="table" then
  for k,it in pairs(bag.物品) do
    if type(it)=="table" then
      out[#out+1]=tostring(it.名称 or "?").." x="..tostring(it.x or "?").." y="..tostring(it.y or "?")
    end
  end
else
  out[1]="道具行囊 no 物品: "..type(bag)
end
out[#out+1]="_count="..#out
_G.__out=table.concat(out,"\n")'''))

print("\n=== 场景所有NPC（名称含 使者/传送/引导 或含 会员）===")
print(lua(r'''
local out={}
for _,tab in ipairs({"假人","场景人物"}) do
  local t=tp.场景[tab]
  if type(t)=="table" then
    for id,u in pairs(t) do
      if type(u)=="table" then
        local nm=tostring(u.名称 or "")
        if nm~="" and (string.find(nm,"使者") or string.find(nm,"传送") or string.find(nm,"引导") or string.find(nm,"会员") or string.find(nm,"商")) then
          out[#out+1]=tab.."#"..tostring(id).." "..nm
        end
      end
    end
  end
end
out[#out+1]="_done"
_G.__out=table.concat(out,"\n")'''))