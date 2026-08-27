# -*- coding: utf-8 -*-
"""CALL 船夫 + 深挖对话一次完成。"""
import json
import sys

sys.path.insert(0, r'E:\DS\mhxy-gui-automation')
from tools.probe_routes import http_json

code = r'''
local ok, err = pcall(function()
  local t = tp.场景.场景人物
  local target
  if t then for k,v in pairs(t) do
    if tostring(v.名称 or "?"):find("船夫") then target = v break end
  end end
  if not target then _G.__out = "no_target" return end
  local mt = getmetatable(target)
  pcall(mt.__index.事件开始, target)
  -- 等待对话弹出
  local d
  for i=1,20 do
    d = tp.窗口.对话栏
    if d and d.可视 then break end
    -- busy wait 无 sleep，循环空转
  end
  if not d or not d.可视 then _G.__out = "no_dialog_after_call" return end
  local out = {"vis=true"}
  for _,k in ipairs({"内容","文本","说明","标题"}) do
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
print((r.get('result') or {}).get('value'))
print('ERR:', r.get('error'))
