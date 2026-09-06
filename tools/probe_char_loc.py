# -*- coding: utf-8 -*-
"""只读探针：tp.角色坐标 内容 + 地图单位里找指定玩家名 + 地图.p 含义。"""
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
target = sys.argv[2] if len(sys.argv) > 2 else "二号美人"
code = r"""
local parts = {}
local cc = tp.角色坐标
if type(cc) == 'table' then
  local acc = {}
  for k, v in pairs(cc) do
    acc[#acc+1] = tostring(k) .. '=' .. (type(v) == 'table' and 'T' or tostring(v))
  end
  parts[#parts+1] = '角色坐标{' .. table.concat(acc, ' ') .. '}'
  local c = cc.坐标
  if type(c) == 'table' then
    parts[#parts+1] = '角色坐标.坐标=' .. tostring(c.x) .. ',' .. tostring(c.y)
  end
else
  parts[#parts+1] = '角色坐标=' .. type(cc)
end
local m = tp.地图
parts[#parts+1] = '地图.p=' .. tostring(m and m.p)
local target = [[TARGET]]
local un = m and m.地图单位
if type(un) == 'table' then
  for _, v in pairs(un) do
    if type(v) == 'table' then
      local nm = tostring(v.名称 or '')
      if nm:find(target) then
        local acc = {}
        for k, v2 in pairs(v) do
          acc[#acc+1] = tostring(k) .. '=' .. (type(v2) == 'table' and 'T' or tostring(v2))
        end
        parts[#parts+1] = '命中{' .. table.concat(acc, ' ') .. '}'
      end
    end
  end
end
__out = table.concat(parts, ' ;; ')
"""
code = code.replace("[[TARGET]]", target)
r = ZGUI._lua_call(gw, code, timeout=8.0) or ""
print(r)
