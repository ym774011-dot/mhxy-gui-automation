# -*- coding: utf-8 -*-
"""dump 小地图窗口找地图名。"""
import sys

sys.path.insert(0, r'E:\DS\mhxy-gui-automation')
from tools.probe_routes import lua

code = r'''
local out = {}
local ok, err = pcall(function()
  local m = tp.窗口.小地图
  if m then
    for k,v in pairs(m) do
      if type(v) == "string" and #v > 0 then
        out[#out+1] = tostring(k).."=["..v.."]"
      end
    end
  else
    out[#out+1] = "no_minimap"
  end
end)
if not ok then out[#out+1] = "ERR:"..tostring(err) end
_G.__out = table.concat(out, " ;; ")
'''
print(lua(code))
