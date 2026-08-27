# -*- coding: utf-8 -*-
"""深度 dump 对话栏选项结构。"""
import sys

sys.path.insert(0, r'E:\DS\mhxy-gui-automation')
from tools.probe_routes import lua

code = r'''
local d = tp.窗口.对话栏
if not d then _G.__out = "no_dialog" return end
local out = {}
-- 文本: 试 CALL 函数字段
for _,k in ipairs({"内容","文本","说明"}) do
  local v = d[k]
  if type(v) == "function" then
    local ok, r = pcall(v, d)
    if ok and r then out[#out+1] = k.."(call)="..tostring(r) end
  elseif type(v) == "string" then
    out[#out+1] = k.."="..v
  end
end
-- 选项
if d.选项 then
  for i=1,#d.选项 do
    local o = d.选项[i]
    local parts = {}
    for kk,vv in pairs(o) do
      local sv
      if type(vv) == "function" then
        local ok, r = pcall(vv, o)
        sv = ok and tostring(r) or "fn"
      else
        sv = tostring(vv)
      end
      parts[#parts+1] = tostring(kk).."="..sv
    end
    out[#out+1] = "opt"..i.."{"..table.concat(parts,",").."}"
  end
end
_G.__out = table.concat(out, "\n")
'''
print(lua(code))
