# -*- coding: utf-8 -*-
"""探查门派图传送表 + 实测合成desc跨图是否被服务端校验（非长安直达门派）"""
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

def cross(desc, x, y):
    try:
        d = jget(GW, "/api/act/cross_map", {"desc": desc, "x": x, "y": y, "wait_ms": 2500, "sync": True})
        return d.get("ok")
    except Exception as e:
        return False

def mapid():
    return expr("tostring(tp.当前地图 or '')")

# 1) 当前地图 + 传送表(找返回长安的入口)
print("=== 当前地图 ===", mapid())
code = r'''
local t = tp.场景.传送
if type(t) ~= "table" then _G.__out="NOTABLE"; return end
local out={}
for i=1,#t do out[#out+1]=tostring(i).."|"..tostring(t[i].切换 or "") end
_G.__out=table.concat(out,"\n")'''
print(lua(code))

# 2) 尝试跳回长安（若在门派图，找其中"长安"入口）
print("\n尝试回长安...")
code_find = r'''
local t=tp.场景.传送; local s=""
for i=1,#t do local v=tostring(t[i].切换 or ""); if string.find(v,"长安酒店楼") or string.find(v,"长安") then s=v; break end end
_G.__out=s'''
back_desc = lua(code_find)
print("回长安desc=", back_desc)
if back_desc:
    ok = cross(back_desc, 1882, 549)  # 长安客栈附近，任意安全坐标
    print("回长安 ok=", ok)
    time.sleep(2)
print("现在地图 =", mapid())