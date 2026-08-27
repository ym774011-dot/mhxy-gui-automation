# -*- coding: utf-8 -*-
"""BFS 链式 hop 探索全图：从当前图出发，逐图 dump 传送表并 hop 到未访问目标。"""
import sys, os, time, json, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tasks.library import WORLD_BOSS as WB

GW = WB.DEFAULT_GATEWAY

DESC_RE = re.compile(r"^(.*?)(?:传送|进)(.+)$")


def dump_table():
    code = '''
local t = tp.场景.传送
local out = tostring(tp.当前地图) .. "\\n"
if t then for i = 1, #t do
  local e = t[i]
  out = out .. tostring(e.切换 or "?")
  if e.坐标 then out = out .. "@" .. tostring(e.坐标.x) .. "," .. tostring(e.坐标.y) end
  out = out .. "\\n"
end end
_G.__out = out
'''
    d = WB._http_json(GW, "/api/lua", {"code": code})
    lines = (d.get("result", {}).get("value") or "").splitlines()
    cur = lines[0] if lines else "?"
    hops = []
    for ln in lines[1:]:
        m = DESC_RE.match(ln)
        if not m:
            continue
        dest = m.group(2).strip()
        xy = ln.split("@", 1)[1] if "@" in ln else "0,0"
        x, y = xy.split(",")[:2]
        hops.append({"desc": m.group(0).split("@")[0], "dest": dest,
                     "x": int(float(x)), "y": int(float(y))})
    return cur, hops


def cross(desc, x, y):
    return WB._http_json(GW, "/api/act/cross_map",
                         {"desc": desc, "x": int(x), "y": int(y),
                          "wait_ms": 3500, "sync": True}, timeout=25.0)


visited_desc = set()
seen_maps = []
queue = []
cur, hops = dump_table()
seen_maps.append(cur)
queue.extend(hops)

MAX_HOPS = 45
n = 0
while queue and n < MAX_HOPS:
    h = queue.pop(0)
    key = h["desc"]
    if key in visited_desc:
        continue
    visited_desc.add(key)
    n += 1
    cur_before = WB._lua_expr(GW, "tostring(tp.当前地图)")
    try:
        d = cross(h["desc"], h["x"], h["y"])
        ok = d.get("ok")
    except Exception as e:
        ok = False
        print("ERR", key, repr(e))
    time.sleep(2.2)
    cur_after = WB._lua_expr(GW, "tostring(tp.当前地图)")
    status = "MOVED" if cur_before != cur_after else "REJECT"
    print(f"[{n:02d}] {key}  {cur_before}->{cur_after}  {status}", flush=True)
    if cur_after not in seen_maps:
        seen_maps.append(cur_after)
    if status == "MOVED":
        _, new_hops = dump_table()
        for nh in new_hops:
            if nh["desc"] not in visited_desc:
                queue.append(nh)

print("MAPS_VISITED:", seen_maps)
