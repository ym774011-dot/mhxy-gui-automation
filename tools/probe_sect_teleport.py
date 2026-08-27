# -*- coding: utf-8 -*-
"""探查：逐跳传送到长安，dump 每张图的传送表，找通向 15 门派地图的入口"""
import sys, os, json, urllib.request, time

GW = "http://127.0.0.1:18083"  # PID 17000


def jget(gw, path, data=None, timeout=10):
    req = urllib.request.Request(gw + path,
        data=json.dumps(data).encode("utf-8") if data is not None else None,
        headers={"Content-Type": "application/json"} if data is not None else {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def lua(code):
    try:
        d = jget(GW, "/api/lua", {"code": code})
        return d.get("result", {}).get("value")
    except Exception as e:
        return f"<ERR {e}>"


def expr(e):
    try:
        d = jget(GW, "/api/lua/expr", {"expr": e})
        return d.get("result", {}).get("value")
    except Exception as e:
        return f"<ERR {e}>"


def dump_transport(label):
    code = r'''
local t = tp.场景.传送
if type(t) ~= "table" then _G.__out = "NO_TABLE"; return end
local L = {}
for i = 1, #t do
  local e = t[i]
  local s = tostring(e and e.切换 or "")
  local c = "?"
  if e and e.坐标 then c = tostring(e.坐标.x) .. "," .. tostring(e.坐标.y) end
  L[#L+1] = i .. "|" .. s .. "|" .. c
end
_G.__out = table.concat(L, "\n")'''
    print(f"[{label}] 地图={expr('tp.当前地图')} 小地图名={expr('tostring(tp.窗口.小地图.地图名称 or '')')}")
    print("传送表:")
    print(lua(code))


def cross(desc, x, y, wait=2500):
    try:
        r = jget(GW, "/api/act/cross_map", {"desc": desc, "x": x, "y": y, "wait_ms": wait, "sync": False})
        print(f"  cross_map desc={desc} -> ok={r.get('ok')} map_raw={str(r.get('result',{}).get('map_switch_raw'))[:60]}")
        return r.get("ok")
    except Exception as e:
        print(f"  cross_map desc={desc} ERR {e}")
        return False


# 当前在东海湾(1506)。先 dump 东海湾传送表
print("====== 当前地图 ======")
dump_transport("东海湾")

# 逐跳去长安: 东海湾->建邺城->江南野外->长安
print("====== 东海湾 -> 建邺城 ======")
cross("东海湾进建邺城新", 100, 2240)
time.sleep(2)
dump_transport("建邺城")

print("====== 建邺城 -> 江南野外 ======")
# 找通往江南野外的 desc
code = "local t=tp.场景.传送; local s='' for i=1,#t do if string.find(tostring(t[i].切换 or ''),'江南野外') then s=tostring(t[i].切换); break end end _G.__out=s"
print("江南野外desc:", lua(code))