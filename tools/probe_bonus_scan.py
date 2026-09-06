# -*- coding: utf-8 -*-
"""只读探针：验证 zhuagui_bonus_battle 新扫描 Lua（称谓判星宿）三段输出。"""
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
local t = tp.地图.地图单位
if type(t) ~= 'table' then __out = '' return end
for _, v in pairs(t) do
  if type(v) == 'table' then
    local name = tostring(v.名称 or '')
    local title = tostring(v.称谓 or '')
    local kind = ''
    if name:find('知了王') then kind = '知了王'
    elseif title:find('星宿') then kind = '星宿'
    elseif name:find('远古') then kind = '远古'
    end
    if kind ~= '' and v.标识 then
      __out = name .. '|' .. tostring(v.标识) .. '|' .. kind
      return
    end
  end
end
__out = ''
"""
r = ZGUI._lua_call(gw, code) or ""
print("SCAN_RESULT:", r)
