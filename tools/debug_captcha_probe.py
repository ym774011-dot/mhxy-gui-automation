# -*- coding: utf-8 -*-
"""防外挂弹窗专项探针：读 验证码/验证按钮/弹窗可见性 + 地图名复核。"""
import json
import sys
import urllib.request

GW = "http://127.0.0.1:18082"


def expr(e, timeout=8):
    req = urllib.request.Request(
        GW + "/api/lua/expr", json.dumps({"expr": e}).encode("utf-8"),
        {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read().decode("utf-8", "replace"))
    if not d.get("ok"):
        return "ERR:" + str(d.get("error"))
    return (d.get("result") or {}).get("value")


QUERIES = [
    ("地图名", 'tostring(tp.场景.地图.名称)'),
    ("坐标", 'tostring(tp.角色坐标.x)..","..tostring(tp.角色坐标.y)'),
    ("战斗中", 'tostring(tp.战斗中)'),
    ("防脚本表存在", 'tostring(type(tp.窗口.防脚本))'),
    ("验证码", 'tostring(tp.窗口.防脚本 and tp.窗口.防脚本.验证码 or "无字段")'),
    ("验证按钮", 'tostring(tp.窗口.防脚本 and tp.窗口.防脚本.验证按钮 and tp.窗口.防脚本.验证按钮.按钮 and "有按钮" or "无按钮")'),
    ("防脚本keys", 'local t={} for k,v in pairs(tp.窗口.防脚本 or {}) do t[#t+1]=tostring(k) end return table.concat(t,",")'),
]

if __name__ == "__main__":
    for name, q in QUERIES:
        print(f"{name}: {expr(q)}")
