# -*- coding: utf-8 -*-
"""dump 物品格子.super 全部方法"""
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

for tgt in ["tp._物品格子", "tp._按钮"]:
    code = r'''
local t = EXPR
if type(t) ~= "table" then _G.__out="NOTABLE"; return end
local sup = t.super
local out = {}
if type(sup) == "table" then
  for k, v in pairs(sup) do
    out[#out+1] = tostring(k) .. " : " .. type(v)
  end
end
table.sort(out)
_G.__out = table.concat(out, "\n")'''.replace("EXPR", tgt)
    print(f"=== {tgt}.super ===")
    print(lua(code))
    print()