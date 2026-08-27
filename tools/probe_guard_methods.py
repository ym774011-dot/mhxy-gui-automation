# -*- coding: utf-8 -*-
"""探查护法/对话框对象暴露的方法（getmetatable），寻找可编程直接触发战斗的入口"""
import json, urllib.request
GW = "http://127.0.0.1:18083"
def lua(code):
    d = json.loads(urllib.request.urlopen(urllib.request.Request(
        GW + "/api/lua", data=json.dumps({"code": code}).encode("utf-8"),
        headers={"Content-Type": "application/json"}), timeout=20).read().decode("utf-8", "replace"))
    if d.get("ok") is False:
        return "<ERR>: " + str(d.get("error"))
    v = d.get("result", {}).get("value")
    return v if v is not None else "(nil)"

print("=== 场景.假人 列表（名称+方法） ===")
print(lua(r'''
local j = tp.场景.假人
local rows = {}
rows[1] = '假人数='..tostring(#j or 0)
for i=1,#j do
  local o = j[i]
  if type(o)=='table' then
    local mt = getmetatable(o)
    local fns = {}
    if type(mt)=='table' then
      for k in pairs(mt.__index or {}) do
        if type((mt.__index or {})[k])=='function' then fns[#fns+1]=tostring(k) end
      end
    end
    rows[#rows+1] = i..':'..tostring(o.名称 or '')..' 方法={'..table.concat(fns,',')..'}'
  end
end
_G.__out = table.concat(rows,'\n')
'''))

print()
print("=== 对话栏方法 ===")
print(lua(r'''
local d = tp.窗口.对话栏
local mt = getmetatable(d)
local fns = {}
if type(mt)=='table' and type(mt.__index)=='table' then
  for k,v in pairs(mt.__index) do
    if type(v)=='function' then fns[#fns+1]=tostring(k) end
  end
end
_G.__out = '对话栏方法={'..table.concat(fns,',')..'}'
'''))

print()
print("=== 当前对话+选项 ===")
print(lua(r'''
local d = tp.窗口.对话栏
local rows = {}
rows[1] = '名='..tostring(d.名称 or '')..' | 文='..tostring(d.文本内容 or '')
local o = d.选项
if type(o)=='table' then
  for i=1,20 do
    local it = o[i]
    if type(it)~='table' then break end
    local mt = getmetatable(it)
    local fns = {}
    if type(mt)=='table' and type(mt.__index)=='table' then
      for k,v in pairs(mt.__index) do if type(v)=='function' then fns[#fns+1]=tostring(k) end end
    end
    rows[#rows+1] = '  opt'..i..'['..tostring(it.跳转链接 or it.基本内容 or '')..'] fns={'..table.concat(fns,',')..'}'
  end
end
_G.__out = table.concat(rows,'\n')
'''))