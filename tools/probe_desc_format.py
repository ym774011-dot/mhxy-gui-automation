# -*- coding: utf-8 -*-
"""探查当前场景传送表 desc 格式 + 实测通用 desc 跨图能否直达门派"""
import json, urllib.request, time

GW = "http://127.0.0.1:18083"
SECTS = ["大唐官府", "方寸山", "女儿村", "神木林", "化生寺", "盘丝洞",
         "阴曹地府", "无底洞", "魔王寨", "狮驼岭", "天宫", "普陀山",
         "凌波城", "五庄观", "龙宫"]


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


print("=== 当前地图 + 传送表 desc(切换) 格式 ===")
print("当前地图 =", expr("tostring(tp.当前地图 or '')"))
print("小地图名 =", expr("tostring(tp.窗口.小地图.地图名称 or '')"))
code = r'''
local t = tp.场景.传送
if type(t) ~= "table" then _G.__out = "NOTABLE"; return end
local out = {}
for i = 1, #t do
  local e = t[i]
  out[#out+1] = tostring(i) .. "|" .. tostring(e and e.切换 or "") .. "|" ..
    ((e and e.坐标 and (e.坐标.x .. "," .. e.坐标.y)) or "noXY")
end
_G.__out = table.concat(out, "\n")'''
print(lua(code))