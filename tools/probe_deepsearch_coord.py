# -*- coding: utf-8 -*-
"""只读探针：深搜 tp 找 自身坐标 来源（字符串含 '朱紫国' 或 '%d,%d' 模式的字段）。"""
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
local seen, hits = {}, {}
local function walk(t, path, depth)
  if depth > 4 or #hits >= 12 then return end
  seen[t] = true
  for k, v in pairs(t) do
    local kp = path .. '.' .. tostring(k)
    local tv = type(v)
    if tv == 'string' then
      if #v < 60 and (v:find('朱紫国') or v:match('%[%d+,%d+%]')) then
        hits[#hits+1] = kp .. '=' .. v
      end
    elseif tv == 'number' then
      -- 数字坐标不好认，跳过
    elseif tv == 'table' and not seen[v] then
      walk(v, kp, depth + 1)
    end
  end
end
walk(tp, 'tp', 0)
__out = table.concat(hits, ' ;; ')
"""
r = ZGUI._lua_call(gw, code, timeout=15.0) or ""
print(r.replace(" ;; ", "\n"))
