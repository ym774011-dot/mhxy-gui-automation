# -*- coding: utf-8 -*-
"""只读探针：组队自动化前置数据——自己名称/坐标字段、场景人物表、队伍数据、申请列表。"""
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
parts[#parts+1] = 'map=' .. tostring(tp.地图 and tp.地图.地图名称 or '')
-- 自己的角色字段探测
local function try(t, f)
  local v = type(t) == 'table' and t[f]
  if v ~= nil then return tostring(f) .. '=' .. (type(v) == 'table' and 'T' or tostring(v)) end
  return nil
end
for _, root in ipairs({tp.人物, tp.角色, tp.主角}) do
  if type(root) == 'table' then
    local acc = {}
    for _, f in ipairs({'名称','名字','id','ID','等级','x','y'}) do
      local s = try(root, f)
      if s then acc[#acc+1] = s end
    end
    local c = root.坐标
    if type(c) == 'table' then
      acc[#acc+1] = '坐标=' .. tostring(c.x) .. ',' .. tostring(c.y)
    end
    if #acc > 0 then parts[#parts+1] = 'SELF{' .. table.concat(acc, ' ') .. '}' end
  end
end
-- 场景人物表（找队长身体用）
local sc = tp.场景 and tp.场景.场景人物
if type(sc) == 'table' then
  local acc = {}
  local n = 0
  for _, v in pairs(sc) do
    if type(v) == 'table' and n < 12 then
      n = n + 1
      local c = v.坐标
      acc[#acc+1] = tostring(v.名称 or '') .. '@' ..
        (type(c) == 'table' and (tostring(c.x) .. ',' .. tostring(c.y)) or '?') ..
        '/' .. tostring(v.称谓 or '')
    end
  end
  parts[#parts+1] = 'SCENE[' .. n .. ']{' .. table.concat(acc, ' ') .. '}'
else
  parts[#parts+1] = 'SCENE=' .. type(sc)
end
-- 队伍面板
local jd = tp.主界面 and tp.主界面.界面数据
local p7 = type(jd) == 'table' and jd[7]
if type(p7) == 'table' then
  local td = p7.队伍数据
  if type(td) == 'table' then
    local acc = {}
    for k, v in pairs(td) do
      if type(v) == 'table' then
        acc[#acc+1] = tostring(v.名称 or '') .. '|队' .. tostring(v.队长 or '') ..
          '@' .. tostring(v.x or '') .. ',' .. tostring(v.y or '')
      end
    end
    parts[#parts+1] = '队伍数据[' .. #acc .. ']=' .. table.concat(acc, ' ')
  else
    parts[#parts+1] = '队伍数据=' .. type(td)
  end
  local sq = p7.申请列表
  if type(sq) == 'table' then
    local acc = {}
    for k, v in pairs(sq) do
      if type(v) == 'table' then
        acc[#acc+1] = tostring(k) .. ':' .. tostring(v.名称 or v.名字 or '') ..
          '|' .. tostring(v.id or v.ID or '')
      else
        acc[#acc+1] = tostring(k) .. '=' .. tostring(v)
      end
    end
    parts[#parts+1] = '申请列表(' .. #acc .. ')=' .. table.concat(acc, ' ')
  else
    parts[#parts+1] = '申请列表=' .. type(sq)
  end
  parts[#parts+1] = 'p7可视=' .. tostring(p7.可视) .. ',开关=' .. tostring(p7.本类开关)
else
  parts[#parts+1] = 'p7=nil'
end
__out = table.concat(parts, ' ;; ')
"""
r = ZGUI._lua_call(gw, code, timeout=8.0) or ""
print(r)
