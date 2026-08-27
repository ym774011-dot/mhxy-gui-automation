# -*- coding: utf-8 -*-
"""触发 门派闯关使者/门派传送人 事件，读取传送对话框选项"""
import json, urllib.request, time

GW = "http://127.0.0.1:18083"

def jget(gw, path, data=None, timeout=20):
    req = urllib.request.Request(gw + path,
        data=json.dumps(data).encode("utf-8") if data is not None else None,
        headers={"Content-Type": "application/json"} if data is not None else {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))

def lua(code, timeout=20):
    try:
        d = jget(GW, "/api/lua", {"code": code}, timeout)
        return d.get("result", {}).get("value") or f"<err:{d.get('error')}>"
    except Exception as e:
        return f"<EXC {e}>"

# 找出 门派闯关使者 对象并调用 事件开始
print("=== 触发 门派闯关使者[31] 事件开始 ===")
code = r'''
local out = {}
local target = nil
for id, u in pairs(tp.场景.场景人物 or {}) do
  if type(u)=="table" and tostring(u.名称 or "")=="门派闯关使者" then target = {id=id, u=u}; break end
end
if not target then _G.__out = "NO_NPC"; return end
local u = target.u
out[#out+1] = "找到 id=" .. tostring(target.id)
out[#out+1] = "有 事件开始 = " .. tostring(type(u["事件开始"]))
local ok, r = pcall(function() return u["事件开始"](u) end)
out[#out+1] = "调用事件开始 ok=" .. tostring(ok) .. " r=" .. tostring(r)
_G.__out = table.concat(out, "\n")'''
print(lua(code))
time.sleep(1.5)

print("\n=== 读取 对话栏 结构 ===")
code = r'''
local d = tp.窗口.对话栏
local out = {}
if type(d) ~= "table" then out[1]="NOTABLE" end
for k, v in pairs(d) do
  local tv = type(v)
  if tv == "table" then
    local sub = {}
    for k2, v2 in pairs(v) do
      if type(v2) == "table" then sub[#sub+1]=tostring(k2).."{...}"
      else sub[#sub+1]=tostring(k2).."="..tostring(v2) end
    end
    out[#out+1]=tostring(k).." = {"..table.concat(sub,", ").."}"
  else
    out[#out+1]=tostring(k).." = "..tostring(v).." ("..tv..")"
  end
end
_G.__out = table.concat(out, "\n")'''
print(lua(code))