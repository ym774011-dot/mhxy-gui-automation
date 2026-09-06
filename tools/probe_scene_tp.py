# -*- coding: utf-8 -*-
"""只读探针（单行输出版）：场景.传送表 + 屏幕偏移 + 地图单位 + 抓鬼任务，用 ' ;; ' 分隔。"""
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
local parts = {}
local m = tp.地图
parts[#parts+1] = 'MAP=' .. tostring(m and m.地图名称 or '')
local off = tp.屏幕.xy
parts[#parts+1] = 'XY=' .. tostring(off and off.x or '-') .. ',' .. tostring(off and off.y or '-')
local sc = tp.场景
local tp2 = type(sc) == 'table' and sc.传送
if type(tp2) == 'table' then
  for i = 1, #tp2 do
    local e = tp2[i]
    if type(e) == 'table' then
      local cx = e.坐标 and tostring(e.坐标.x) or '-'
      local cy = e.坐标 and tostring(e.坐标.y) or '-'
      parts[#parts+1] = 'HOP|' .. tostring(e.切换 or '') .. '|' .. cx .. ',' .. cy
    end
  end
else
  parts[#parts+1] = 'HOPS=none(' .. type(tp2) .. ')'
end
local un = m and m.地图单位
if type(un) == 'table' then
  for _, v in pairs(un) do
    if type(v) == 'table' then
      local wx = tonumber(tostring(v.坐标 and v.坐标.x or '')) or 0
      local wy = tonumber(tostring(v.坐标 and v.坐标.y or '')) or 0
      parts[#parts+1] = 'UNIT|' .. tostring(v.名称 or '') .. '|' ..
        tostring(v.称谓 or '') .. '|' .. tostring(v.标识 or '') .. '|' .. wx .. ',' .. wy
    end
  end
else
  parts[#parts+1] = 'UNITS=none'
end
__out = table.concat(parts, ' ;; ')
"""
r = ZGUI._lua_call(gw, code) or ""
for part in r.split(" ;; "):
    print(part)
