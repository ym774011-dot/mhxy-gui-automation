# -*- coding: utf-8 -*-
"""深挖世界大地图分类a的坐标表。"""
import sys

sys.path.insert(0, r'E:\DS\mhxy-gui-automation')
from tools.probe_routes import lua

code = r'''
local out = {}
local ok, err = pcall(function()
  local w = tp.窗口.世界大地图分类a
  if not w then out[#out+1] = "no_window" return end
  local c = w.坐标
  for i=1,#c do
    local e = c[i]
    local parts = {}
    for k,v in pairs(e) do
      parts[#parts+1] = tostring(k).."="..tostring(v)
    end
    out[#out+1] = "entry"..i.."{ "..table.concat(parts," ").." }"
  end
end)
if not ok then out[#out+1] = "ERR:"..tostring(err) end
_G.__out = table.concat(out, "\n")
'''
print(lua(code))
