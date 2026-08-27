# -*- coding: utf-8 -*-
"""确认护法交互：真实坐标 + 是否有事件开始/如何触发对话"""
import json, urllib.request, time

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
        if d.get("ok") is False:
            return f"<LUA_ERR:{d.get('error')}>"
        return d.get("result", {}).get("value")
    except Exception as e:
        return f"<EXC {e}>"

def has_dg():
    return lua(r'''
local u = nil
for id, x in pairs(tp.场景.假人 or {}) do
  if type(x)=="table" and tostring(x.名称 or "")=="大唐官府护法" then u=x break end
end
if not u then _G.__out="NO"; return end
local out = {}
out[1]="真实坐标="..tostring(u.真实坐标 and u.真实坐标[1])..","..tostring(u.真实坐标 and u.真实坐标[2])
out[2]="地图坐标="..tostring(u.地图坐标 and u.地图坐标[1])..","..tostring(u.地图坐标 and u.地图坐标[2])
out[3]="格子="..tostring(u.格子x)..","..tostring(u.格子y)
out[4]="事件开始 type="..type(u["事件开始"])
out[5]="执行事件="..tostring(u.执行事件)
_G.__out=table.concat(out,"\n")''')

print("=== 护法信息 ===")
print(has_dg())

print("\n=== 尝试调用 事件开始 ===")
print(lua(r'''
local u = nil
for id, x in pairs(tp.场景.假人 or {}) do
  if type(x)=="table" and tostring(x.名称 or "")=="大唐官府护法" then u=x break end
end
local out={}
if not u then out[1]="NO"; _G.__out=table.concat(out,"\n"); return end
local es = u["事件开始"]
out[1] = "事件开始 type=" .. type(es)
if type(es)=="function" then
  local ok, r = pcall(function() return es(u) end)
  out[2] = "调用 ok=" .. tostring(ok) .. " r=" .. tostring(r)
end
-- 用 __index 查方法
local mt = getmetatable(u)
out[3] = "有元表=" .. tostring(mt ~= nil)
if mt then
  local m = {}
  for k,v in pairs(mt) do m[#m+1]=tostring(k).."="..type(v) end
  out[4] = "元表: " .. table.concat(m,", ")
end
_G.__out=table.concat(out,"\n")'''))

# 若调用成功，等待后读对话栏
print("\n=== 读对话栏 ===")
time.sleep(0.8)
print(lua(r'''
local d = tp.窗口.对话栏
local out = {}
out[1]="可视="..tostring(d and d.可视).." 名称="..tostring(d and d.名称)
out[2]="文本内容="..tostring(d and d.文本内容 or "")
_G.__out=table.concat(out,"\n")'''))