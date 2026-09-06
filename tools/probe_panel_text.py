# -*- coding: utf-8 -*-
"""只读探针：扫界面数据各面板文本字段找自身坐标显示源 + 寻路/选中数据。"""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
spec = importlib.util.spec_from_file_location(
    "ZGUI", os.path.join(ROOT, "tasks", "library", "ZGUI.py"))
ZGUI = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ZGUI)

gw = sys.argv[1] if len(sys.argv) > 1 else "file://pzxy_p18908"
code = r"""
local hits = {}
local jd = tp.主界面 and tp.主界面.界面数据
if type(jd) == 'table' then
  for i = 1, 80 do
    local p = jd[i]
    if type(p) == 'table' then
      for _, f in ipairs({'文字', '标题文字', '介绍文本', '文本', '状态', '介绍加入'}) do
        local v = p[f]
        if type(v) == 'string' and #v < 60 and (v:find('朱紫国') or v:match('%[%d+,%d+%]')) then
          hits[#hits+1] = '[' .. i .. '].' .. f .. '=' .. v
        end
      end
    end
  end
end
local m = tp.地图
local function flat(t, tag)
  if type(t) ~= 'table' then hits[#hits+1] = tag .. '=' .. type(t) return end
  local a = {}
  local n = 0
  for k, v in pairs(t) do
    n = n + 1
    if n <= 15 then a[#a+1] = tostring(k) .. '=' .. (type(v) == 'table' and 'T' or tostring(v)) end
  end
  hits[#hits+1] = tag .. '[' .. n .. ']{ ' .. table.concat(a, ' ') .. '}'
end
flat(m and m.寻路, '寻路')
flat(m and m.选中数据, '选中数据')
flat(m and m.临时数据, '临时数据')
__out = table.concat(hits, ' ;; ')
"""
r = ZGUI._lua_call(gw, code, timeout=15.0) or ""
print(r.replace(" ;; ", "\n"))
