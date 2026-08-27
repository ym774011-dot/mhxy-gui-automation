# -*- coding: utf-8 -*-
"""遍历枢纽图, 采集各图传送表里含门派名的 desc → 建立 15门派直达desc 映射"""
import json, urllib.request, time, sys

GW = "http://127.0.0.1:18083"
HUB_DESC = {
    "长安": "江南野外传送长安",
    "江南野外": "长安传送江南野外",
    "建邺城": "江南野外传送建邺城",
    "东海湾": "建邺城进东海湾新",
    "大唐国境": "长安传送大唐国境",
    "长寿村": "大唐国境传送长寿郊外",
}
HUB_ORDER = ["长安", "江南野外", "建邺城", "东海湾", "大唐国境", "长寿村"]

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

def cross(desc, x=1000, y=1000):
    try:
        d = jget(GW, "/api/act/cross_map", {"desc": desc, "x": x, "y": y, "wait_ms": 2500, "sync": False})
        return d.get("ok")
    except Exception as e:
        return False

def dump_transport():
    code = r'''
local t = tp.场景.传送
if type(t) ~= "table" then return "NOTABLE" end
local out={}
for i=1,#t do out[#out+1]=tostring(t[i].切换 or "") end
_G.__out = table.concat(out, "\n")'''
    return lua(code)

mid = expr("tostring(tp.当前地图 or '')")
print("当前地图 =", mid)
# 先把角色带回 长安
if mid != "1001":
    print("先回长安...")
    print("  cross 长安 =", cross(HUB_DESC["长安"]))
    time.sleep(2)
    print("  现在地图 =", expr("tostring(tp.当前地图 or '')"))

# 遍历枢纽, 采集传送表, 匹配门派
sect_hits = {}
for hub in HUB_ORDER:
    # 跨到该枢纽
    ok = cross(HUB_DESC[hub]); time.sleep(1.5)
    cur = expr("tostring(tp.当前地图 or '')")
    print(f"\n=== [{hub}] 地图={cur} ===")
    tl = dump_transport()
    for line in (tl or "").splitlines():
        line = line.strip()
        if not line: continue
        # 记录所有含 门派名的 desc
        for s in ["大唐官府","方寸山","女儿村","神木林","化生寺","盘丝洞",
                  "阴曹地府","无底洞","魔王寨","狮驼岭","天宫","普陀山",
                  "凌波城","五庄观","龙宫"]:
            if s in line and s not in sect_hits:
                sect_hits[s] = line
                print(f"  ★[{s}] <- {line}")
    if len(sect_hits) >= 15:
        break

print("\n\n======== 采集结果: 15门派 → desc ========")
import json as _j
order = ["长安","大唐官府","方寸山","化生寺","凌波城","龙宫","魔王寨","女儿村",
         "普陀山","盘丝洞","神木林","狮驼岭","天宫","无底洞","五庄观","阴曹地府"]
for s in order:
    if s in sect_hits:
        print(f'  "{s}": "{sect_hits[s]}",')
    else:
        print(f'  "{s}": "",   # 未命中')