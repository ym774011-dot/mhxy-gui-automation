# -*- coding: utf-8 -*-
"""枚举 _G 全部菌数，定位 物品使用/开窗/切图 入口"""
import json, urllib.request

GW = "http://127.0.0.1:18083"

def jget(gw, path, data=None, timeout=30):
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

code = r'''
local out={}
for k,v in pairs(_G) do
  if type(v)=="function" then out[#out+1]=tostring(k).."()" end
end
table.sort(out)
_G.__out=table.concat(out,"\n")'''
print(lua(code))