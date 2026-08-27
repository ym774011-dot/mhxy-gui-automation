# -*- coding: utf-8 -*-
"""dump 门派传送子菜单每个选项的完整字段（找 desc/坐标/切换）"""
import json, urllib.request

GW = "http://127.0.0.1:18083"

def lua(code):
    req = urllib.request.Request(GW + "/api/lua",
        data=json.dumps({"code": code}).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8", "replace"))

code = r'''
local opt = tp.窗口.对话栏.选项
local out = {}
if type(opt) ~= "table" then out[1] = "NOTABLE" end
for i = 1, 20 do
  local o = opt[i]
  if type(o) ~= "table" then break end
  out[#out+1] = "== [" .. i .. "] =="
  for k, v in pairs(o) do
    if type(v) == "table" then
      local sub = {}
      for k2, v2 in pairs(v) do sub[#sub+1] = tostring(k2) .. "=" .. tostring(v2) end
      out[#out+1] = "   " .. tostring(k) .. "={" .. table.concat(sub, ",") .. "}"
    elseif type(v) == "function" then
      out[#out+1] = "   " .. tostring(k) .. "=function"
    else
      out[#out+1] = "   " .. tostring(k) .. "=" .. tostring(v)
    end
  end
end
_G.__out = table.concat(out, "\n")'''
d = lua(code)
print(d.get("result", {}).get("value") or ("<ERR: %s>" % d.get("error")))