# -*- coding: utf-8 -*-
"""dump 物品格子/按钮/控件 的方法(函数), 找物品使用入口"""
import json, urllib.request

GW = "http://127.0.0.1:18083"

def jget(gw, path, data=None, timeout=25):
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

targets = ["tp._物品格子", "tp._按钮", "tp._控件", "tp._物品_格子", "tp._窗口_格子"]
for tgt in targets:
    code = r'''
local t = EXPR
if type(t) ~= "table" then _G.__out = "NOTABLE"; return end
local out = {}
for k, v in pairs(t) do
  out[#out+1] = tostring(k) .. " : " .. type(v)
end
table.sort(out)
_G.__out = table.concat(out, "\n")'''.replace("EXPR", tgt)
    print(f"=== {tgt} 字段 ===")
    print(lua(code))
    print()