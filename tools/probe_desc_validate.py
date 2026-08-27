# -*- coding: utf-8 -*-
"""实测: 合成desc是否被服务端校验(当前图无该传送门时能否直达) + 取地图名映射"""
import json, urllib.request, time

GW = "http://127.0.0.1:18083"

def jget(gw, path, data=None, timeout=15):
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
        d = jget(GW, "/api/act/cross_map", {"desc": desc, "x": x, "y": y, "wait_ms": 2500, "sync": True})
        return d.get("ok")
    except Exception as e:
        return False

def mapid():
    return expr("tostring(tp.当前地图 or '')")

print("当前地图 =", mapid(), "小地图名=", expr("tostring(tp.窗口.小地图.地图名称 or '')"))

# 尝试地图名→ID 全局索引
print("\n=== 探地图名→ID 映射（当前场景）===")
code = r'''
local out={}
local function scan(t, path, depth)
  if depth>2 then return end
  if type(t)~="table" then return end
  for k,v in pairs(t) do
    local ks=tostring(k)
    if type(v)=="table" and (v.地图名称 or v.名称) then
      if string.find(tostring(v.地图名称 or v.名称 or ""), "龙宫") or
         string.find(tostring(v.地图名称 or v.名称 or ""), "天宫") or
         string.find(tostring(v.地图名称 or v.名称 or ""), "大唐官府") then
        out[#out+1]=path.."."..ks.." 地图名称="..tostring(v.地图名称 or v.名称 or "").." id="..tostring(v.当前地图 or v.地图ID or "")
      end
    end
    scan(v, path.."."..ks, depth+1)
    if #out>=40 then break end
  end
end
scan(tp, "tp", 0)
_G.__out=table.concat(out,"\n")'''
print(lua(code))

print("\n=== 测试合成desc直达(当前无传送门的门派)===")
start = mapid()
print("出发地图 =", start)
test = "江南野外传送龙宫"
print("desc =", test)
ok = cross(test, 40, 40)
time.sleep(2)
print("ok=", ok, "到达地图=", mapid())