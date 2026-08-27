# -*- coding: utf-8 -*-
"""探查已打开的会员卡窗口: 找门派传送列表"""
import json, urllib.request

GW = "http://127.0.0.1:18083"

def jget(gw, path, data=None, timeout=25):
    req = urllib.request.Request(gw + path,
        data=json.dumps(data).encode("utf-8") if data is not None else None,
        headers={"Content-Type": "application/json"} if data is not None else {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))

def lua(code):
    try:
        d = jget(GW, "/api/lua", {"code": code})
        return d.get("result", {}).get("value") or f"<err:{d.get('error')}>"
    except Exception as e:
        return f"<EXC {e}>"

# 1) 当前打开的窗口
code = r'''
local w = tp.窗口
local out = {}
if type(w) == "table" then
  for k, v in pairs(w) do
    out[#out+1] = tostring(k) .. " : " .. type(v)
  end
end
table.sort(out)
_G.__out = table.concat(out, "\n")'''
print("=== tp.窗口 顶层字段 ===")
print(lua(code))

# 2) 找含 门派 的窗口/按钮/文本
print("\n=== 深扫 td.窗口 找『门派』『传送』关键词 ===")
code = r'''
local out = {}
local seen = {}
local function scan(t, path, depth)
  if depth > 6 then return end
  if type(t) ~= "table" then
    if type(t) == "string" and (string.find(t, "门派") or string.find(t, "传送")) then
      if not seen[t] then seen[t]=true; if #out<80 then out[#out+1]=path.." = "..t end end
    end
    return
  end
  for k, v in pairs(t) do
    scan(v, path.."."..tostring(k), depth+1)
  end
end
scan(tp.窗口, "win", 0)
_G.__out = table.concat(out, "\n")'''
print(lua(code))