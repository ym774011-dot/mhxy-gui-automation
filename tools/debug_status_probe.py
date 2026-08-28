# -*- coding: utf-8 -*-
"""诊断 1：读当前游戏状态（地图/坐标/战斗态），纯只读不干扰。"""
import json
import urllib.request

GW = "http://127.0.0.1:18082"


def expr(e):
    req = urllib.request.Request(
        GW + "/api/lua/expr", json.dumps({"expr": e}).encode("utf-8"),
        {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=8) as r:
        d = json.loads(r.read().decode("utf-8", "replace"))
    return d


r = expr('tostring(tp.场景.地图.名称).."|@|"..tostring(tp.角色坐标.x)..'
         '","..tostring(tp.角色坐标.y).."|@|"..tostring(tp.战斗中)')
print(json.dumps(r, ensure_ascii=False))
