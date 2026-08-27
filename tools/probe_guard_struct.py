# -*- coding: utf-8 -*-
"""dump 大唐官府护法 对象结构（字段+方法）"""
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
        if d.get("ok") is False:
            return f"<LUA_ERR:{d.get('error')}>"
        return d.get("result", {}).get("value")
    except Exception as e:
        return f"<EXC {e}>"

# dump 假人表所有对象的结构概览 + 护法详细结构
print(lua(r'''
local out = {}
local target = nil
for id, u in pairs(tp.场景.假人 or {}) do
  if type(u)=="table" and tostring(u.名称 or "")=="大唐官府护法" then target={id=id,u=u} break end
end
if not target then _G.__out="NO"; return end
local u = target.u
out[#out+1] = "=== 假人#"..tostring(target.id).." 大唐官府护法 字段 ==="
for k, v in pairs(u) do
  local tv = type(v)
  if tv == "function" then
    out[#out+1] = "  [方法]" .. tostring(k)
  elseif tv == "table" then
    local n = 0
    for _ in pairs(v) do n = n + 1 end
    out[#out+1] = "  [表]" .. tostring(k) .. " (n=" .. n .. ")"
  else
    out[#out+1] = "  " .. tostring(k) .. " = " .. tostring(v) .. " (" .. tv .. ")"
  end
end
_G.__out = table.concat(out, "\n")'''))