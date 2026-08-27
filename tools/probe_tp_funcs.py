# -*- coding: utf-8 -*-
"""枚举 tp 命名空间的方法函数: 找 使用物品/打开界面/切图 入口"""
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

keywords = ["使用", "打开", "弹出", "界面", "地图", "场景", "切换", "会员", "传送", "飞行"]
code = r'''
local out = {}
for k, v in pairs(tp) do
  if type(v) == "function" then
    out[#out+1] = tostring(k) .. "()"
  end
end
table.sort(out)
_G.__out = table.concat(out, "\n")'''
allm = lua(code)
lines = [l for l in (allm or "").splitlines() if any(k in l for k in keywords)]
print(f"=== tp 方法中与 使用/窗口/地图/场景/传送/飞行 相关 ({len(lines)}) ===")
for l in lines:
    print(l)
print("\n=== tp 方法总数 ===")
print(len(allm.splitlines()))