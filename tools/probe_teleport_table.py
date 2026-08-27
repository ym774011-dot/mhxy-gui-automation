# -*- coding: utf-8 -*-
"""dump 取传送点() 返回的全局传送表"""
import json, urllib.request

GW = "http://127.0.0.1:18083"

def jget(gw, path, data=None, timeout=20):
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

# 取传送点() 结构
code = r'''
local t = _G['取传送点']()
local out = {}
out[#out+1] = "type=" .. type(t)
if type(t) == "table" then
  out[#out+1] = "len=" .. tostring(#t) .. " count=" .. tostring(table_count_count or 0)
  local n = 0
  for k, v in pairs(t) do
    n = n + 1
    if n <= 300 then
      local sv = type(v) == "table" and "table" or tostring(v)
      -- 若内层是 table 且有名称/切换，展开一行
      out[#out+1] = tostring(k) .. " | " .. sv
    end
  end
  out[#out+1] = "pairs_total~=" .. n
end
_G.__out = table.concat(out, "\n")'''
print("取传送点():")
print(lua(code))