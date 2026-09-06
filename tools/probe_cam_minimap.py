# -*- coding: utf-8 -*-
"""只读探针：自身坐标候选（小地图/相机偏移）+ 单位名称全量聚合。"""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
spec = importlib.util.spec_from_file_location(
    "ZGUI", os.path.join(ROOT, "tasks", "library", "ZGUI.py"))
ZGUI = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ZGUI)

gw = sys.argv[1] if len(sys.argv) > 1 else "file://pzxy_p7732"
code = r"""
local parts = {}
local function dumpty(t, tag, depth)
  if type(t) ~= 'table' then parts[#parts+1] = tag .. '=' .. type(t) return end
  local acc = {}
  for k, v in pairs(t) do
    local sv
    if type(v) == 'table' then
      if (depth or 0) > 0 then sv = 'T' else
        local a2 = {}
        for k2, v2 in pairs(v) do a2[#a2+1] = tostring(k2) .. '=' .. (type(v2) == 'table' and 'T' or tostring(v2)) end
        sv = '{' .. table.concat(a2, ' ') .. '}'
      end
    else sv = tostring(v) end
    acc[#acc+1] = tostring(k) .. '=' .. sv
  end
  parts[#parts+1] = tag .. '{' .. table.concat(acc, ' ') .. '}'
end
local m = tp.地图
dumpty(m and m.小地图, '小地图', 1)
dumpty(m and m.起始xy, '起始xy', 1)
dumpty(m and m.开始位置, '开始位置', 1)
dumpty(m and m.选中数据, '选中数据', 1)
local o = tp.屏幕
dumpty(o, '屏幕', 1)
-- 单位名称聚合
local un = m and m.地图单位
if type(un) == 'table' then
  local names = {}
  local n = 0
  for _, v in pairs(un) do
    if type(v) == 'table' then
      n = n + 1
      local nm = tostring(v.名称 or '') .. '/' .. tostring(v.称谓 or '')
      names[nm] = (names[nm] or 0) + 1
    end
  end
  local acc = {}
  for k, c in pairs(names) do acc[#acc+1] = k .. 'x' .. c end
  parts[#parts+1] = '单位名[' .. n .. ']{ ' .. table.concat(acc, ' ') .. '}'
end
__out = table.concat(parts, ' ;; ')
"""
r = ZGUI._lua_call(gw, code, timeout=8.0) or ""
print(r.replace(" ;; ", "\n"))
