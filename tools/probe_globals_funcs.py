# -*- coding: utf-8 -*-
"""枚举全局函数：找 打开窗口/使用物品/切地图 相关入口"""
import json, urllib.request

GW = "http://127.0.0.1:18083"

def jget(gw, path, data=None, timeout=20):
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

# 枚举 _G 所有函数名（含关键词过滤）
import re
keywords = ["使用", "窗口", "打开", "弹出", "界面", "地图", "场景", "切换", "会员", "传送", "飞行", "飞", "跳"]
code = r'''
local out = {}
for k, v in pairs(_G) do
  if type(v) == "function" or type(v) == "table" then
    out[#out+1] = tostring(k) .. " : " .. type(v)
  end
end
table.sort(out)
_G.__out = table.concat(out, "\n")'''
allg = lua(code)
lines = [l for l in (allg or "").splitlines() if any(k in l for k in keywords)]
print(f"=== _G 中与 使用/窗口/地图/场景/传送/飞 相关的项 ({len(lines)}) ===")
for l in lines[:120]:
    print(l)