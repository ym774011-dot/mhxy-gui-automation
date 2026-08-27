# -*- coding: utf-8 -*-
"""探查护法对话框选项：完整键、类型、可调方法，用于定位正确点击/触发方式"""
import json, urllib.request, time
GW = "http://127.0.0.1:18083"
def lua(code):
    d = json.loads(urllib.request.urlopen(urllib.request.Request(
        GW + "/api/lua", data=json.dumps({"code": code}).encode("utf-8"),
        headers={"Content-Type": "application/json"}), timeout=20).read().decode("utf-8", "replace"))
    if d.get("ok") is False:
        return "<ERR>: " + str(d.get("error"))
    v = d.get("result", {}).get("value")
    return v if v is not None else "(nil)"

print("=== 选项完整键值 ===")
print(lua(r'''
local d = tp.窗口.对话栏
local o = d.选项
local rows = {}
rows[1] = '选项表类型='..type(o)
if type(o)~='table' then _G.__out=table.concat(rows,'\n'); return end
-- 通用遍历前若干键
local found = 0
for kk,it in pairs(o) do
  if type(it)=='table' then
    found = found + 1
    if found > 20 then break end
    local row = 'opt['..tostring(kk)..']:'
    for a,b in pairs(it) do
      local tv = type(b)
      if tv=='table' then
        local sub={}
        for m,n in pairs(b) do sub[#sub+1]=tostring(m)..'='..tostring(n) end
        row = row .. ' ['..tostring(a)..']=table{'..table.concat(sub,';')..'}'
      else
        row = row .. ' ['..tostring(a)..']='..tostring(b)
      end
    end
    rows[#rows+1]=row
  end
end
_G.__out=table.concat(rows,'\n')'''))