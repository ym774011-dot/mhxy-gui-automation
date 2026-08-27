# -*- coding: utf-8 -*-
"""探测当前地图中的「X门派护法」NPC，输出其位置与可用事件方法"""
import json, urllib.request, time

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

# 1) 当前地图信息
print("=== 当前地图 ===")
print(lua(r'''
local m = tp.场景.当前地图
local out = {}
out[1] = "地图名=" .. tostring(m and m.名称 or "?")
out[2] = "地图id=" .. tostring(m and m.id or m.ID or "?")
out[3] = "当前坐标=" .. tostring(_G.__player and _G.__player[1]) .. "," .. tostring(_G.__player and _G.__player[2])
_G.__out = table.concat(out, "\n")'''))

# 2) 在所有 假人/场景人物 中找名称含「护法」的
print("\n=== 查找 护法 NPC（假人表 + 场景人物表）===")
print(lua(r'''
local out = {}
local found = 0
local function dump(u, src, id)
  if type(u) ~= "table" then return end
  local nm = tostring(u.名称 or "")
  if nm == "" then return end
  -- 只关注护法
  if not (string.find(nm, "护法") ~= nil) then return end
  found = found + 1
  local loc = u.坐标 or u.位置 or u.所在地图 or ""
  if type(loc)=="table" then loc = tostring(loc[1])..","..tostring(loc[2]) end
  out[#out+1] = "["..tostring(src).."#"..tostring(id).."] "..nm.." loc="..tostring(loc)
  -- 可用事件方法
  local methods = {}
  for k, v in pairs(u) do
    if type(v)=="function" then methods[#methods+1]=tostring(k) end
  end
  out[#out+1] = "    事件方法: " .. table.concat(methods, ",")
end
for id, u in pairs(tp.场景.假人 or {}) do dump(u, "假人", id) end
for id, u in pairs(tp.场景.场景人物 or {}) do dump(u, "人物", id) end
out[#out+1] = "_found=" .. found
_G.__out = table.concat(out, "\n")'''))