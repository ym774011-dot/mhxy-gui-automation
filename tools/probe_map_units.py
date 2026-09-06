# -*- coding: utf-8 -*-
"""只读探针：dump 当前地图单位（找传送点单位形态）+ 任务说明原文。"""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
spec = importlib.util.spec_from_file_location(
    "ZGUI", os.path.join(ROOT, "tasks", "library", "ZGUI.py"))
ZGUI = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ZGUI)

gw = sys.argv[1] if len(sys.argv) > 1 else "file://pzxy_p17164"
code = r"""
local m = tp.地图
__out = 'MAP=' .. tostring(m and m.地图名称 or '') .. '\n'
local un = m and m.地图单位
if type(un) == 'table' then
  for _, v in pairs(un) do
    if type(v) == 'table' then
      local wx = tonumber(tostring(v.坐标 and v.坐标.x or '')) or 0
      local wy = tonumber(tostring(v.坐标 and v.坐标.y or '')) or 0
      __out = __out .. 'UNIT|' .. tostring(v.名称 or '') .. '|' ..
              tostring(v.称谓 or '') .. '|' .. tostring(v.标识 or '') .. '|' ..
              wx .. ',' .. wy .. '\n'
    end
  end
end
local t = tp.窗口.任务栏.任务
if type(t) == 'table' then
  for i = 1, #t do
    local v = t[i]
    if type(v) == 'table' and tostring(v.名称 or '') == '抓鬼任务' then
      __out = __out .. 'TASK=' .. tostring(v.说明 or '') .. '\n'
    end
  end
end
"""
r = ZGUI._lua_call(gw, code) or ""
print(r.replace("\x0a", "\n"))
