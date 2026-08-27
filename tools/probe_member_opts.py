# -*- coding: utf-8 -*-
"""读取 对话栏(会员传送) 的选项 — 门派传送列表 → desc/坐标"""
import json, urllib.request, time

GW = "http://127.0.0.1:18083"

def lua(code):
    req = urllib.request.Request(GW + "/api/lua",
        data=json.dumps({"code": code}).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8", "replace"))

# 对话栏 目前状态
code = r'''
local d = tp.窗口.对话栏
local out = {}
out[#out+1] = "名称=" .. tostring(d and d.名称 or "")
out[#out+1] = "可视=" .. tostring(d and d.可视 or false)
local opt = d and d.选项
local n = 0
if type(opt) == "table" then
  for _ in pairs(opt) do n = n + 1 end
end
out[#out+1] = "选项数=" .. tostring(n)
for i = 1, math.min(n, 40) do
  local o = opt[i]
  if type(o) == "table" then
    local bits = {}
    for k, v in pairs(o) do
      if type(v) == "table" then
        local sub = {}
        for k2, v2 in pairs(v) do
          sub[#sub+1] = k2 .. "=" .. tostring(v2)
        end
        bits[#bits+1] = tostring(k) .. "{" .. table.concat(sub, ",") .. "}"
      else
        bits[#bits+1] = tostring(k) .. "=" .. tostring(v)
      end
    end
    out[#out+1] = "  [" .. i .. "] {" .. table.concat(bits, "; ") .. "}"
  end
end
_G.__out = table.concat(out, "\n")'''
d = lua(code)
print(d.get("result", {}).get("value") or ("<ERR: %s>" % d.get("error")))