# -*- coding: utf-8 -*-
"""只读探针：按称谓过滤地图单位里的玩家（江湖豪侠=队员称谓），避开 CLI 中文转码坑。"""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
spec = importlib.util.spec_from_file_location(
    "ZGUI", os.path.join(ROOT, "tasks", "library", "ZGUI.py"))
ZGUI = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ZGUI)

gws = sys.argv[1:] or ["file://pzxy_p7732", "file://pzxy_p3916",
                       "file://pzxy_p11568", "file://pzxy_p18736",
                       "file://pzxy_p18908"]
code = r"""
local acc = {}
local un = tp.地图.地图单位
if type(un) == 'table' then
  for _, v in pairs(un) do
    if type(v) == 'table' then
      local tt = tostring(v.称谓 or '')
      if tt:find('江湖') then
        local c = v.坐标
        acc[#acc+1] = tostring(v.名称 or '') .. '/' .. tt ..
          '/id' .. tostring(v.id or '') ..
          '@' .. (type(c) == 'table' and (tostring(c.x) .. ',' .. tostring(c.y)) or '?')
      end
    end
  end
end
__out = table.concat(acc, ' ;; ')
"""
for gw in gws:
    r = ZGUI._lua_call(gw, code, timeout=8.0)
    print(gw, "=>", r if r else "(空)")
