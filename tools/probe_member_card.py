# -*- coding: utf-8 -*-
"""探查 tp.窗口 结构 + tp._物品 + 物品使用触发, 定位会员传送"""
import sys, os, json, urllib.request

GW = "http://127.0.0.1:18083"


def lua(code):
    try:
        d = _jget(GW, "/api/lua", {"code": code})
        v = d.get("result", {}).get("value")
        return v if v is not None else f"<err:{d.get('error')}>"
    except Exception as e:
        return f"<EXC {e}>"


def _jget(gw, path, data=None, timeout=15):
    req = urllib.request.Request(gw + path,
        data=json.dumps(data).encode("utf-8") if data is not None else None,
        headers={"Content-Type": "application/json"} if data is not None else {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


# tp.窗口 顶层字段
code = r'''
local w = tp.窗口
local ks = {}
if type(w) == "table" then for k in pairs(w) do ks[#ks+1] = tostring(k) end end
table.sort(ks)
_G.__out = table.concat(ks, ",")
'''
print("=== tp.窗口 顶层字段 ===")
print(lua(code))

# tp._物品 结构（物品槽）
code2 = r'''
local item = tp._物品
local ks = {}
if type(item) == "table" then for k in pairs(item) do ks[#ks+1] = tostring(k) end end
table.sort(ks)
_G.__out = table.concat(ks, ",")
'''
print("\n=== tp._物品 字段 ===")
print(lua(code2))