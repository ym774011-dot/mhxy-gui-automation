# -*- coding: utf-8 -*-
"""枚举 tp.窗口 找「会员传送」相关窗口，dump 其选项/传送数据"""
import json, urllib.request

GW = "http://127.0.0.1:18083"

def lua(code):
    req = urllib.request.Request(GW + "/api/lua",
        data=json.dumps({"code": code}).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8", "replace"))

# 1) 枚举全部窗口名 + 可视
code = r'''
local out = {}
local t = tp.窗口
if type(t) ~= "table" then out[1] = "NOTABLE" end
local names = {}
for k, v in pairs(t) do
  if type(v) == "table" then
    local nm = tostring(v.名称 or "")
    local vis = tostring(v.可视 or false)
    out[#out+1] = tostring(k) .. "|名=" .. nm .. "|可视=" .. vis
  end
end
_G.__out = table.concat(out, "\n")'''
d = lua(code)
print("=== 全部窗口 ===")
print(d.get("result", {}).get("value") or d.get("error"))