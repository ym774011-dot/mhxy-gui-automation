# -*- coding: utf-8 -*-
"""回到长安, 定位 门派传送人/门派闯关使者 等NPC, 触发事件读取传送选项"""
import json, urllib.request, time

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

def expr(e):
    try:
        d = jget(GW, "/api/lua/expr", {"expr": e})
        return d.get("result", {}).get("value") or f"<err:{d.get('error')}>"
    except Exception as e:
        return f"<EXC {e}>"

def cross(desc, x, y):
    try:
        d = jget(GW, "/api/act/cross_map", {"desc": desc, "x": x, "y": y, "wait_ms": 2500, "sync": False})
        return d.get("ok")
    except Exception:
        return False

# 回长安(若不在)
mid = expr("tostring(tp.当前地图 or '')")
print("当前地图 =", mid)
if mid != "1001":
    print("回长安...", cross("江南野外传送长安", 500, 500))
    time.sleep(2)
    print("现在是", expr("tostring(tp.当前地图 or '')"))

# 定位当前场景中的目标NPC(场景人物/临时Npc/假人)
print("\n=== 当前场景 查找 门派相关NPC ===")
code = r'''
local out = {}
local function scanlist(container, label)
  if type(container) ~= "table" then return end
  for id, u in pairs(container) do
    if type(u) == "table" then
      local nm = tostring(u.名称 or "")
      if string.find(nm, "门派") or string.find(nm, "传送人") or string.find(nm, "闯关") then
        out[#out+1] = label .. "[" .. tostring(id) .. "] 名称=" .. nm ..
          " 格子=" .. tostring(u.格子x or "?") .. "," .. tostring(u.格子y or "?") ..
          " 坐标=" .. tostring(u.坐标 and (u.坐标.x or "") or "?") .. "," .. tostring(u.坐标 and (u.坐标.y or "") or "?")
      end
    end
  end
end
for _, n in ipairs({"场景人物","人物","Npc","临时Npc","假人","场景假人"}) do
  local c = tp.场景[n]
  if type(c) == "table" then scanlist(c, n) end
end
_G.__out = table.concat(out, "\n")'''
print(lua(code))