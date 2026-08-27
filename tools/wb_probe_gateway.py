# -*- coding: utf-8 -*-
"""探测 gateway 字段：地图名/场景人物/战斗态/对话栏。"""
import json
import sys
import urllib.request

GW = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:18082"


def api_lua(code, result_var="ret", timeout=12):
    body = json.dumps({"code": code, "result_var": result_var}).encode("utf-8")
    req = urllib.request.Request(GW + "/api/lua", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def api_expr(expr, timeout=12):
    body = json.dumps({"expr": expr}).encode("utf-8")
    req = urllib.request.Request(GW + "/api/lua/expr", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


if __name__ == "__main__":
    checks = [
        ("地图ID", "ret=tostring(tp.当前地图)"),
        ("地图名", 'ret=tostring(tp.场景.地图 and tp.场景.地图.名称 or "no-field")'),
        ("战斗态", "ret=tostring(tp.战斗中)"),
        ("场景人物数", "local n=0 for _ in pairs(tp.场景.场景人物 or {}) do n=n+1 end ret=tostring(n)"),
        ("对话栏可视", "ret=tostring(tp.窗口.对话栏 and tp.窗口.对话栏.可视 or false)"),
    ]
    for label, code in checks:
        try:
            print(label, "=>", json.dumps(api_lua(code), ensure_ascii=False)[:300])
        except Exception as e:
            print(label, "ERR", e)

    # 场景人物名列表（前 40 个）
    code = r'''
local names = {}
local arr = tp.场景.场景人物 or {}
for i, v in ipairs(arr) do
  if i > 40 then break end
  local nm = "?"
  if type(v) == "table" then
    nm = tostring(v.名称 or v.name or v.名字 or "?")
  else
    nm = tostring(v)
  end
  names[#names+1] = nm
end
ret=table.concat(names, ",")
'''
    try:
        print("人物列表 =>", json.dumps(api_lua(code), ensure_ascii=False)[:1500])
    except Exception as e:
        print("人物列表 ERR", e)
