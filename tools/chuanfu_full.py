# -*- coding: utf-8 -*-
"""船夫交互完整流程：CALL → 轮询对话 → 深挖结构。"""
import sys
import time

sys.path.insert(0, r'E:\DS\mhxy-gui-automation')
from tools.probe_routes import lua

CALL = r'''
local t = tp.场景.场景人物
local target
if t then for k,v in pairs(t) do
  if tostring(v.名称 or "?"):find("船夫") then target = v break end
end end
if target then
  local mt = getmetatable(target)
  pcall(mt.__index.事件开始, target)
  _G.__out = "called"
else
  _G.__out = "no_target"
end
'''

POLL = r'''
local d = tp.窗口.对话栏
if d and d.可视 and d.选项 and #d.选项 > 0 then
  _G.__out = "ready:"..tostring(#d.选项)
else
  _G.__out = "wait:"..tostring(d and d.可视)
end
'''

DUMP = r'''
local d = tp.窗口.对话栏
if not d then _G.__out = "no_dialog" return end
local out = {}
for _,k in ipairs({"内容","文本","说明","标题"}) do
  local v = d[k]
  if type(v) == "function" then
    local ok2, r = pcall(v, d)
    out[#out+1] = k.."("..tostring(ok2)..")="..tostring(r)
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
        sv = tostring(r)
      elseif type(vv) == "table" then
        local sub = {}
        for k3,v3 in pairs(vv) do sub[#sub+1] = tostring(k3).."="..tostring(v3) end
        sv = "{"..table.concat(sub,",").."}"
      else
        sv = tostring(vv)
      end
      parts[#parts+1] = tostring(kk).."="..sv
    end
    out[#out+1] = "opt"..i.."["..table.concat(parts," ; ").."]"
  end
end
_G.__out = table.concat(out, "\n")
'''

if __name__ == '__main__':
    # 先关掉可能残留的旧对话
    lua(r'pcall(function() if tp.窗口.对话栏 and tp.窗口.对话栏.关闭 then tp.窗口.对话栏:关闭() end end)')
    time.sleep(0.5)
    print('call:', lua(CALL))
    state = ''
    for i in range(12):
        time.sleep(0.3)
        state = lua(POLL)
        if state.startswith('ready'):
            break
    print('poll:', state)
    if state.startswith('ready'):
        time.sleep(0.3)
        print(lua(DUMP))
