# -*- coding: utf-8 -*-
"""探查会员卡物品 Lua 方法/事件结构，以及是否有可 CALL 的函数字段"""
import json, urllib.request
GW = "http://127.0.0.1:18083"
def lua(code):
    d = json.loads(urllib.request.urlopen(urllib.request.Request(
        GW + "/api/lua", data=json.dumps({"code": code}).encode("utf-8"),
        headers={"Content-Type": "application/json"}), timeout=20).read().decode("utf-8", "replace"))
    if d.get("ok") is False:
        return f"<ERR:{d.get('error')}>"
    return d.get("result", {}).get("value")
print(lua(r'''
-- 1) 背包是否开
local bag = tp.窗口.道具行囊
local out = {}
out[1] = "袋可视=" .. tostring(bag and bag.可视 or false)
-- 2) 找会员卡
local card = nil
if type(bag) == "table" and type(bag.物品) == "table" then
  for k, it in pairs(bag.物品) do
    if type(it) == "table" and tostring(it.名称 or "") == "鲜衣怒马会员卡" then card = it end
  end
end
if not card then _G.__out = table.concat(out, "\n") .. "\n会员卡=nil"; return end
out[2] = "会员卡=x" .. tostring(card.x) .. ",y" .. tostring(card.y)
-- 列出会员卡对象的 字符串字段 + 函数字段
local strkeys = {}
local funkeys = {}
for k, v in pairs(card) do
  if type(k) == "string" then
    if type(v) == "function" then funkeys[#funkeys+1] = k
    elseif type(v) ~= "table" then strkeys[#strkeys+1] = k .. "=" .. tostring(v)
    end
  end
end
out[3] = "字符串字段=" .. table.concat(strkeys, ",")
out[4] = "函数字段=" .. table.concat(funkeys, ",")
_G.__out = table.concat(out, "\n")'''))