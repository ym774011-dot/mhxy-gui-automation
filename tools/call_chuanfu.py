# -*- coding: utf-8 -*-
"""CALL 船夫事件开始，读对话栏内容。"""
import sys
import time

sys.path.insert(0, r'E:\DS\mhxy-gui-automation')
from tools.probe_routes import lua

code = r'''
local out = {}
local t = tp.场景.场景人物
local target
if t then for k,v in pairs(t) do
  local n = tostring(v.名称 or "?")
  if n:find("船夫") then target = v break end
end end
if target then
  local mt = getmetatable(target)
  local ok, err = pcall(mt.__index.事件开始, target)
  out[#out+1] = "call_ok="..tostring(ok).." err="..tostring(err)
else
  out[#out+1] = "no_target"
end
_G.__out = table.concat(out, " ;; ")
'''
print('call:', lua(code))
time.sleep(1.2)

code2 = r'''
local d = tp.窗口.对话栏
if d then
  local s = "vis="..tostring(d.可视)
  local opts = {}
  if d.选项 then for i=1,#d.选项 do opts[#opts+1] = tostring(d.选项[i].内容 or d.选项[i].文本 or tostring(d.选项[i])) end end
  s = s.." opts=["..table.concat(opts,"|").."]"
  local txt = ""
  if d.内容 then txt = tostring(d.内容) elseif d.文本 then txt = tostring(d.文本) end
  s = s.." text="..txt
  _G.__out = s
else
  _G.__out = "no_dialog"
end
'''
print('dialog:', lua(code2))
