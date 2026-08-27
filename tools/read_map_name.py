# -*- coding: utf-8 -*-
"""读当前地图名称 + 窗口列表找雷达/地图窗口。"""
import sys

sys.path.insert(0, r'E:\DS\mhxy-gui-automation')
from tools.probe_routes import lua

code = r'''
local out = {}
local cands = {
  {"tp.当前地图名", tostring(tp.当前地图名)},
  {"tp.场景.地图.名称", tp.场景 and tp.场景.地图 and tostring(tp.场景.地图.名称)},
  {"tp.场景.地图名", tp.场景 and tostring(tp.场景.地图名)},
  {"tp.场景.名称", tp.场景 and tostring(tp.场景.名称)},
  {"tp.地图名称", tostring(tp.地图名称)},
}
for _,c in ipairs(cands) do out[#out+1] = c[1].."="..tostring(c[2]) end
local ok, err = pcall(function()
  for k,w in pairs(tp.窗口 or {}) do
    local ks = tostring(k)
    if ks:find("地图") or ks:find("雷达") then
      out[#out+1] = "窗口."..ks
      local n = type(w) == "table" and w.名称 or nil
      if n then out[#out+1] = "  名称="..tostring(n) end
    end
  end
end)
if not ok then out[#out+1] = "ERR:"..tostring(err) end
_G.__out = table.concat(out, "\n")
'''
print(lua(code))
