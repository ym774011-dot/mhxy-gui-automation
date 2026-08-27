# -*- coding: utf-8 -*-
"""深度 dump 对话栏选项结构（带错误捕获）。"""
import json
import sys

sys.path.insert(0, r'E:\DS\mhxy-gui-automation')
from tools.probe_routes import http_json

code = r'''
local ok, err = pcall(function()
  local d = tp.窗口.对话栏
  if not d then _G.__out = "no_dialog" return end
  local out = {}
  for _,k in ipairs({"内容","文本","说明"}) do
    local v = d[k]
    if type(v) == "function" then
      local ok2, r = pcall(v, d)
      if ok2 and r then out[#out+1] = k.."="..tostring(r) end
    elseif type(v) == "string" then
      out[#out+1] = k.."="..v
    end
  end
  if d.选项 then
    for i=1,#d.选项 do
      local o = d.选项[i]
      local parts = {}
      for kk,vv in pairs(o) do
        local sv
        if type(vv) == "function" then
          local ok2, r = pcall(vv, o)
          sv = ok2 and tostring(r) or "fn"
        elseif type(vv) == "table" then
          sv = "tbl"
        else
          sv = tostring(vv)
        end
        parts[#parts+1] = tostring(kk).."="..sv
      end
      out[#out+1] = "opt"..i.."{"..table.concat(parts,",").."}"
    end
  end
  _G.__out = table.concat(out, "\n")
end)
if not ok then _G.__out = "ERR:"..tostring(err) end
'''
r = http_json('/api/lua', {'code': code})
print(json.dumps(r, ensure_ascii=False)[:2000])
