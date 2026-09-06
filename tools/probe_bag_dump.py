# -*- coding: utf-8 -*-
"""只读探针：dump 背包(面板3)物品原始字段，定位可售识别为何为空。"""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
spec = importlib.util.spec_from_file_location(
    "ZGUI", os.path.join(ROOT, "tasks", "library", "ZGUI.py"))
ZGUI = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ZGUI)

gw = sys.argv[1] if len(sys.argv) > 1 else "file://pzxy_p6880"
code = r"""
local j = tp.主界面 and tp.主界面.界面数据
local pd = type(j) == 'table' and type(j[3]) == 'table' and j[3].物品数据
if type(pd) ~= 'table' then __out = 'NO_TABLE' return end
local parts = {}
for i = 1, 100 do
  local it = pd[i]
  if type(it) == 'table' then
    local sa = it.小动画
    local x = type(sa) == 'table' and tostring(sa.x) or '-'
    local y = type(sa) == 'table' and tostring(sa.y) or '-'
    parts[#parts+1] = table.concat({
      tostring(it.格子id or i), tostring(it.名称 or ''), tostring(it.类型 or ''),
      tostring(it.分类 or ''), x, y}, '|')
  end
end
__out = table.concat(parts, ' ;; ')
"""
r = ZGUI._lua_call(gw, code) or ""
for part in r.split(" ;; "):
    if part and part != "NO_TABLE":
        print(part)
    elif part == "NO_TABLE":
        print("NO_TABLE")
