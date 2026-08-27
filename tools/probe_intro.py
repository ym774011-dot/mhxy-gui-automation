# -*- coding: utf-8 -*-
"""dump 任务追踪栏.介绍文本 完整结构。"""
import json, sys, urllib.request
sys.path.insert(0, r"e:\DS\mhxy-gui-automation")
GW = "http://127.0.0.1:18083"
def lua(code):
    req = urllib.request.Request(GW + "/api/lua", data=json.dumps({"code": code}).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    d = json.loads(urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "replace"))
    return d.get("result", {}).get("value") or (f"<ERR:{d.get('error')}>" if d.get("ok") is False else "")

print(lua(r'''
local out={}
local function dump(v, depth)
  local pad=string.rep('  ', depth)
  if depth>4 then return end
  if type(v)=='table' then
    for k,val in pairs(v) do
      local kk=tostring(k)
      if type(val)=='table' then
        local n=#val
        out[#out+1]=pad..kk..'=table['..n..']'
        dump(val, depth+1)
      else
        out[#out+1]=pad..kk..'='..tostring(val)
      end
    end
  end
end
local tb=tp.窗口.任务追踪栏.介绍文本
if not tb then _G.__out='无介绍文本'; return end
dump(tb,0)
_G.__out=table.concat(out,'\n')
'''))