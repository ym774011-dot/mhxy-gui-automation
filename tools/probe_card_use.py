# -*- coding: utf-8 -*-
"""探查 会员卡 使用机制 + tp.传送点 全局传送表 + 招唤接口"""
import json, urllib.request, sys

GW = "http://127.0.0.1:18083"


def lua(code):
    try:
        d = jget(GW, "/api/lua", {"code": code})
        return d.get("result", {}).get("value") or f"<err:{d.get('error')}>"
    except Exception as e:
        return f"<EXC {e}>"


def jget(gw, path, data=None, timeout=15):
    req = urllib.request.Request(gw + path,
        data=json.dumps(data).encode("utf-8") if data is not None else None,
        headers={"Content-Type": "application/json"} if data is not None else {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


print("=== 1) 会员卡物品完整字段 (tp.道具列表[1]) ===")
code = r'''
local it = tp.道具列表[1]
if type(it) ~= "table" then _G.__out = "notable"; return end
local out = {}
for k, v in pairs(it) do
  local tv = type(v)
  if tv == "table" then
    local sub = {}
    for k2, v2 in pairs(v) do sub[#sub+1] = tostring(k2) .. "=" .. tostring(v2) end
    out[#out+1] = tostring(k) .. " = {" .. table.concat(sub, ",") .. "}"
  else
    out[#out+1] = tostring(k) .. " = " .. tostring(v) .. " (" .. tv .. ")"
  end
end
_G.__out = table.concat(out, "\n")'''
print(lua(code))


print("\n=== 2) tp._物品.super / 初始化 是否有 使用方法 ===")
code = r'''
local m = tp._物品
local out = {}
if type(m) == "table" then
  for k, v in pairs(m) do out[#out+1] = tostring(k) .. " : " .. type(v) end
  local sup = m.super
  if type(sup) == "table" then
    for k, v in pairs(sup) do out[#out+1] = "super." .. tostring(k) .. " : " .. type(v) end
  end
end
_G.__out = table.concat(out, "\n")'''
print(lua(code))


print("\n=== 3) tp.传送点 全局结构（找 15 门派）===")
code = r'''
local t = tp.传送点
if type(t) ~= "table" then _G.__out = "NOTABLE"; return end
local out = {}
for k, v in pairs(t) do
  out[#out+1] = tostring(k) .. " : " .. type(v)
end
_G.__out = table.concat(out, "\n")'''
print(lua(code))