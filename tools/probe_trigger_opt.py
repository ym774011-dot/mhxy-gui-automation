# -*- coding: utf-8 -*-
"""探查 对话栏 选项触发机制 + 尝试触发 门派传送 子菜单"""
import json, urllib.request, time

GW = "http://127.0.0.1:18083"

def lua(code):
    req = urllib.request.Request(GW + "/api/lua",
        data=json.dumps({"code": code}).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8", "replace"))

def show(tag, code):
    d = lua(code)
    v = d.get("result", {}).get("value")
    print(f"=== {tag} ===")
    print(v if v is not None else ("<ERR: %s>" % d.get("error")))

# 1) 对话栏 函数字段
show("对话栏 函数字段", r'''
local t = tp.窗口.对话栏
local out = {}
for k, v in pairs(t) do
  if type(v) == "function" then out[#out+1] = tostring(k) .. "=function" end
end
_G.__out = table.concat(out, "\n")''')

# 2) 选项[2]对象 完整字段类型
show("选项[2] 全部字段", r'''
local o = tp.窗口.对话栏.选项[2]
local out = {"选项[2] type=" .. type(o)}
if type(o) == "table" then
  for k, v in pairs(o) do
    if type(v) == "function" then out[#out+1] = tostring(k) .. "=function"
    elseif type(v) == "table" then
      local sub = {}
      for k2, v2 in pairs(v) do sub[#sub+1] = tostring(k2) .. "=" .. tostring(v2) end
      out[#out+1] = tostring(k) .. "={" .. table.concat(sub, ",") .. "}"
    else out[#out+1] = tostring(k) .. "=" .. tostring(v) end
  end
end
_G.__out = table.concat(out, "\n")''')

# 3) 尝试调用选项自身的触发函数（如果有）
show("尝试触发 选项[2]", r'''
local o = tp.窗口.对话栏.选项[2]
local fns = {"触发","点击","事件","跳转","执行","选择"}
local out = {}
for _, n in ipairs(fns) do
  if type(o[n]) == "function" then
    local ok, r = pcall(function() return o[n](o) end)
    out[#out+1] = n .. "=" .. tostring(ok) .. " r=" .. tostring(r)
  end
end
_G.__out = table.concat(out, "\n")''')