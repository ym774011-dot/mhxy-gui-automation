# -*- coding: utf-8 -*-
"""诊断会员卡菜单为何打不开"""
import json, urllib.request
GW="http://127.0.0.1:18083"
def lua(code):
    d=json.loads(urllib.request.urlopen(urllib.request.Request(GW+"/api/lua",
        data=json.dumps({"code":code}).encode("utf-8"),
        headers={"Content-Type":"application/json"}),timeout=20).read().decode("utf-8","replace"))
    if d.get("ok") is False: return f"<ERR:{d.get('error')}>"
    return d.get("result",{}).get("value")

print("=== 袋/会员卡/对话栏状态 ===")
print(lua(r'''
local out={}
local bag = tp.窗口 and tp.窗口.道具行囊
out[1]="道具行囊.可视="..tostring(bag and bag.可视)
-- 搜索 鲜衣怒马会员卡
local card = nil
if bag and type(bag.物品)=="table" then
  for k,it in pairs(bag.物品) do
    if type(it)=="table" and tostring(it.名称 or "")=="鲜衣怒马会员卡" then card=it; out[#out+1]="会员卡 找到: x="..tostring(it.x).." y="..tostring(it.y) break end
  end
end
if not card then out[#out+1]="会员卡 未找到(可能已消耗)!" end
local d = tp.窗口 and tp.窗口.对话栏
out[#out+1]="对话栏.可视="..tostring(d and d.可视).." 名称="..tostring(d and d.名称).." 文本="..tostring(d and d.文本内容 or "")
local opt=d and d.选项
local links={}
if type(opt)=="table" then
  for i=1,30 do
    local o=opt[i]
    if type(o)~="table" then break end
    links[#links+1]=tostring(o.跳转链接 or o.文字 or "")
  end
end
out[#out+1]="对话选项="..table.concat(links,"|")
out[#out+1]="当前地图="..tostring(tp.当前地图 or "")
out[#out+1]="战斗中="..tostring(tp.战斗中)
_G.__out=table.concat(out,"\n")'''))