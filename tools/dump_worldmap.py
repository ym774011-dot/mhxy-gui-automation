# -*- coding: utf-8 -*-
"""dump 世界大地图分类窗口，找地图连接表。"""
import sys

sys.path.insert(0, r'E:\DS\mhxy-gui-automation')
from tools.probe_routes import lua

code = r'''
local out = {}
local ok, err = pcall(function()
  for _, wname in ipairs({"世界大地图分类a","世界大地图分类b","世界大地图分类c","世界大地图分类d","世界大地图"}) do
    local w = tp.窗口[wname]
    if w then
      out[#out+1] = "== "..wname
      for k,v in pairs(w) do
        local ks = tostring(k)
        if type(v) == "string" and #v > 0 and #v < 80 then
          out[#out+1] = "  "..ks.."=["..v.."]"
        elseif type(v) == "number" then
          out[#out+1] = "  "..ks.."="..tostring(v)
        elseif type(v) == "table" then
          local parts = {}
          local cnt = 0
          for kk,vv in pairs(v) do
            cnt = cnt + 1
            if cnt > 10 then parts[#parts+1] = "..." break end
            parts[#parts+1] = tostring(kk)..":"..type(vv)..(type(vv)=="number" and ("="..tostring(vv)) or (type(vv)=="string" and ("=["..vv.."]") or ""))
          end
          out[#out+1] = "  "..ks.."{ "..table.concat(parts," ").." }"
        end
      end
    end
  end
end)
if not ok then out[#out+1] = "ERR:"..tostring(err) end
_G.__out = table.concat(out, "\n")
'''
print(lua(code))
