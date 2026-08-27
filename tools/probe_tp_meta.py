# -*- coding: utf-8 -*-
"""tp元表 + 深扫含『会员』『传送』字符串的配置表 + 全tp方法"""
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

print("=== 1) tp 元表 __index ===")
code = r'''
local mt = getmetatable(tp)
local out = {}
out[#out+1] = "mt=" .. type(mt)
if type(mt) == "table" then
  out[#out+1] = "__index=" .. type(mt.__index)
  if type(mt.__index) == "table" then
    local n=0
    for k in pairs(mt.__index) do n=n+1; if n<=50 then out[#out+1]="  "..tostring(k) end end
    out[#out+1]="  __index_total~"..n
  end
end
_G.__out=table.concat(out,"\n")'''
print(lua(code))


print("\n=== 2) tp 直接方法全表 ===")
code = r'''
local out={}
for k,v in pairs(tp) do out[#out+1]=tostring(k).." : "..type(v) end
table.sort(out)
_G.__out=table.concat(out,"\n")'''
print(lua(code))