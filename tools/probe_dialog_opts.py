# -*- coding: utf-8 -*-
"""dump 会员卡对话框 的 选项 与 丰富文本，提取门派传送 desc"""
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

print("=== 对话栏.选项 (1..10) 全字段 ===")
code = r'''
local opt = tp.窗口.对话栏.选项
local out = {}
if type(opt) ~= "table" then out[1]="NOTABLE" end
for i = 1, 20 do
  local o = opt[i]
  if type(o) == "table" then
    out[#out+1] = "== 选项[" .. i .. "] =="
    for k, v in pairs(o) do
      local tv = type(v)
      if tv == "table" then
        local sub={}
        for k2,v2 in pairs(v) do
          if type(v2)=="table" then sub[#sub+1]=tostring(k2).."{...}"
          else sub[#sub+1]=tostring(k2).."="..tostring(v2) end
        end
        out[#out+1]="  "..tostring(k).." = {"..table.concat(sub,", ").."}"
      else
        out[#out+1]="  "..tostring(k).." = "..tostring(v).." ("..tv..")"
      end
    end
    out[#out+1]=""
  else
    break
  end
end
_G.__out = table.concat(out, "\n")'''
print(lua(code))