# -*- coding: utf-8 -*-
"""dump 小地图NPC + 世界大地图分类窗口结构。"""
import sys

sys.path.insert(0, r'E:\DS\mhxy-gui-automation')
from tools.probe_routes import lua

code = r'''
local out = {}
local ok, err = pcall(function()
  local n = tp.窗口.小地图NPC
  if n then
    for k,v in pairs(n) do
      if type(v) == "table" then
        local parts = {}
        local cnt = 0
        for kk,vv in pairs(v) do
          cnt = cnt + 1
          if cnt > 15 then parts[#parts+1] = "..." break end
          if type(vv) == "table" then
            local sub = {}
            for k3,v3 in pairs(vv) do sub[#sub+1] = tostring(k3).."="..tostring(v3) end
            parts[#parts+1] = tostring(kk).."{ "..table.concat(sub,",").." }"
          else
            parts[#parts+1] = tostring(kk).."="..tostring(vv)
          end
        end
        out[#out+1] = "NPC窗口."..tostring(k).."{ "..table.concat(parts," ").." }"
      elseif type(v) == "string" then
        out[#out+1] = "NPC窗口."..tostring(k).."=["..v.."]"
      else
        out[#out+1] = "NPC窗口."..tostring(k).."="..tostring(v)
      end
    end
  else
    out[#out+1] = "no_npc_window"
  end
end)
if not ok then out[#out+1] = "ERR:"..tostring(err) end
_G.__out = table.concat(out, "\n")
'''
print(lua(code))
