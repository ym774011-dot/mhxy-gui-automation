# -*- coding: utf-8 -*-
"""dump 每日活动窗口结构（会员卡/门派传送 所在）"""
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
        if d.get("ok") is False: return f"<ERR:{d.get('error')}>"
        return d.get("result", {}).get("value")
    except Exception as e:
        return f"<EXC {e}>"

print("=== tp.窗口.每日活动 顶层字段 ===")
code = r'''
local d = tp.窗口.每日活动
local out = {}
if type(d) ~= "table" then out[1]="NOTABLE" end
for k, v in pairs(d) do
  out[#out+1] = tostring(k) .. " : " .. type(v)
end
table.sort(out)
_G.__out = table.concat(out, "\n")'''
print(lua(code))

print("\n=== 每日活动 内 含 传送/门派/选项/按钮 的子结构 ===")
code = r'''
local d = tp.窗口.每日活动
local out = {}
local function scan(t, path, depth)
  if depth>4 then return end
  if type(t)~="table" then return end
  for k,v in pairs(t) do
    local ks=tostring(k)
    if string.find(ks,"传送") or string.find(ks,"门派") or string.find(ks,"选项") or string.find(ks,"按钮") or string.find(ks,"跳转") or string.find(ks,"链接") then
      out[#out+1]=path.."."..ks.." : "..type(v)
    end
    scan(v, path.."."..ks, depth+1)
    if #out>=120 then return end
  end
end
scan(d, "act", 0)
_G.__out = table.concat(out, "\n")'''
print(lua(code))

print("\n=== 每日活动.初始tp.场景 顶层 ===")
code = r'''
local d = tp.窗口.每日活动.初始tp
local out = {}
if type(d)~="table" then out[1]="NOTABLE:"..type(d) else
  for k,v in pairs(d) do out[#out+1]=tostring(k).." : "..type(v) end
end
table.sort(out)
_G.__out=table.concat(out,"\n")'''
print(lua(code))