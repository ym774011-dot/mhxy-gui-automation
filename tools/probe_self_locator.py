# -*- coding: utf-8 -*-
"""只读探针：找"自己/其他玩家"的屏幕定位数据源（地图单位是否含玩家、主角坐标字段）。"""
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
-- tp 顶层键
local acc = {}
for k, v in pairs(tp) do acc[#acc+1] = tostring(k) .. '(' .. type(v) .. ')' end
parts[#parts+1] = 'TP{' .. table.concat(acc, ' ') .. '}'
-- 地图顶层键
acc = {}
local m = tp.地图
if type(m) == 'table' then
  for k, v in pairs(m) do acc[#acc+1] = tostring(k) .. '(' .. type(v) .. ')' end
end
parts[#parts+1] = 'MAP{' .. table.concat(acc, ' ') .. '}'
-- 地图单位：看有没有玩家（名称=角色名 如 一号美人/这是帅哥）
local un = m and m.地图单位
if type(un) == 'table' then
  acc = {}
  local n = 0
  for _, v in pairs(un) do
    if type(v) == 'table' then
      n = n + 1
      if n <= 25 then
        local c = v.坐标
        acc[#acc+1] = tostring(v.名称 or '') .. '/' .. tostring(v.称谓 or '') ..
          '@' .. (type(c) == 'table' and (tostring(c.x) .. ',' .. tostring(c.y)) or '?')
      end
    end
  end
  parts[#parts+1] = 'UNITS[' .. n .. ']{' .. table.concat(acc, ' ') .. '}'
end
__out = table.concat(parts, ' ;; ')
"""
r = ZGUI._lua_call(gw, code, timeout=8.0) or ""
print(r)
