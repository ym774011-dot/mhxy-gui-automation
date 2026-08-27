# -*- coding: utf-8 -*-
"""探查会员卡/道具行囊的「使用/右键」方法，尝试 Lua 触发会员传送界面"""
import json, urllib.request

GW = "http://127.0.0.1:18083"

def lua(code):
    req = urllib.request.Request(GW + "/api/lua",
        data=json.dumps({"code": code}).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8", "replace"))

def show(tag, code):
    d = lua(code)
    v = d.get("result", {}).get("value")
    print(f"=== {tag} ===")
    print(v if v is not None else ("<ERR: %s>" % d.get("error")))

# 1) 道具列表卡 自带方法/字段（含函数）
show("道具列表[1] 函数型字段", r'''
local it = tp.道具列表[1]
local out = {}
if type(it) == "table" then
  for k, v in pairs(it) do
    if type(v) == "function" then out[#out+1] = tostring(k) .. "=function"
    else out[#out+1] = tostring(k) .. "=" .. tostring(v) end
  end
end
_G.__out = table.concat(out, "\n")''')

# 2) 道具行囊 上的 使用/右键 相关
show("道具行囊 函数/按钮字段", r'''
local t = tp.窗口.道具行囊
local out = {}
if type(t) == "table" then
  for k, v in pairs(t) do
    if type(v) == "function" then out[#out+1] = tostring(k) .. "=function" end
  end
end
_G.__out = table.concat(out, "\n")''')

# 3) 全局 使用物品 函数探测
show("全局 使用/右键 函数", r'''
local out = {}
local cand = {"使用物品","使用道具","右键物品","物品使用","使用","点击物品","打开物品"}
for _, n in ipairs(cand) do
  if type(_G[n]) == "function" then out[#out+1] = n .. "=function" end
end
-- tp 命名空间下
local ts = tp or {}
for _, n in ipairs(cand) do
  if type(ts[n]) == "function" then out[#out+1] = "tp." .. n .. "=function" end
end
_G.__out = table.concat(out, "\n")''')