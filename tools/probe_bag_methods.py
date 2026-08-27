# -*- coding: utf-8 -*-
"""探查 道具行囊窗口 / 容器 层可 CALL 的函数字典"""
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
local out = {}
local bag = tp.窗口.道具行囊
-- 方法（函数字段）
local funkeys = {}
local strkeys = {}
if type(bag) == "table" then
  for k, v in pairs(bag) do
    if type(k) == "string" then
      if type(v) == "function" then funkeys[#funkeys+1] = k
      elseif type(v) ~= "table" then strkeys[#strkeys+1] = k
      end
    end
  end
end
out[1] = "[道具行囊] 函数=" .. table.concat(funkeys, ", ")
out[2] = "[道具行囊] 字段=" .. table.concat(strkeys, ", ")

-- 容器方法（可能是标准窗口基类）
local cont = tp.窗口.道具行囊.容器
if type(cont) == "table" then
  local cf = {}
  local cs = {}
  for k, v in pairs(cont) do
    if type(k) == "string" then
      if type(v) == "function" then cf[#cf+1] = k
      elseif type(v) ~= "table" then cs[#cs+1] = k
      end
    end
  end
  out[3] = "[容器] 函数=" .. table.concat(cf, ", ")
  out[4] = "[容器] 字段=" .. table.concat(cs, ", ")
else
  out[3] = "[容器] = " .. tostring(cont)
end

-- 全局函数里带 使用/物品/会员 的
local gfun = {}
do
  for k, v in pairs(_G or {}) do
    if type(v) == "function" and type(k) == "string" then
      if string.find(k, "物品") or string.find(k, "道具") or string.find(k, "会员")
         or string.find(k, "使用") or string.find(k, "传送") or string.find(k, "门派") then
        gfun[#gfun+1] = k
      end
    end
  end
end
out[5] = "全局相关函数=" .. table.concat(gfun, ", ")
_G.__out = table.concat(out, "\n")'''))