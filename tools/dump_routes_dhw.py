# -*- coding: utf-8 -*-
"""dump 东海湾传送路线表。"""
import sys

sys.path.insert(0, r'E:\DS\mhxy-gui-automation')
from tools.probe_routes import lua

code = r'''
local out = {}
local ok, err = pcall(function()
  local r = tp.场景.传送路线
  if r then
    for k,v in pairs(r) do
      local sv
      if type(v) == "table" then
        local parts = {}
        for kk,vv in pairs(v) do
          parts[#parts+1] = tostring(kk).."="..tostring(vv)
        end
        sv = "{"..table.concat(parts,",").."}"
      else
        sv = tostring(v)
      end
      out[#out+1] = tostring(k).." -> "..sv
    end
  else
    out[#out+1] = "no_routes"
  end
end)
if not ok then out[#out+1] = "ERR:"..tostring(err) end
_G.__out = table.concat(out, "\n")
'''
print(lua(code))
