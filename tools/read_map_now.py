# -*- coding: utf-8 -*-
"""正确读取当前地图名 + 角色坐标，判断是否已跨图"""
import json, urllib.request

GW = "http://127.0.0.1:18083"

def expr(e):
    req = urllib.request.Request(GW + "/api/lua/expr",
        data=json.dumps({"expr": e}).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        d = json.loads(r.read().decode("utf-8", "replace"))
    return d.get("result", {}).get("value")

cands = [
    "tostring(tp.窗口.小地图.地图名称 or '')",
    "tostring(tp.当前地图 or '')",
    "tostring(tp.当前图 or '')",
    "tostring(tp.地图 or '')",
    "tostring(tp.角色.坐标.x or '') .. ',' .. tostring(tp.角色.坐标.y or '')",
    "tostring(tp.角色坐标.x or '') .. ',' .. tostring(tp.角色坐标.y or '')",
]
for e in cands:
    print(f"{e}\n  => {expr(e)}")