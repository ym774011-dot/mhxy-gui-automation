# -*- coding: utf-8 -*-
"""枚举客户端 Lua 全局里与场景/地图相关的表。"""
import sys

sys.path.insert(0, r'E:\DS\mhxy-gui-automation')
from tools.probe_routes import lua

CODE = r'''
local out = {}
for k,v in pairs(_G) do
  local ks = tostring(k)
  local tv = type(v)
  if tv == "table" and (ks:find("场景") or ks:find("传送") or ks:find("地图") or ks:find("地图")) then
    out[#out+1] = "T:"..ks
  end
end
table.sort(out)
_G.__out = table.concat(out, " ;; ")
'''

if __name__ == '__main__':
    print(lua(CODE))
