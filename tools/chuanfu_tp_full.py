# -*- coding: utf-8 -*-
"""船夫传送完整链路 + 落地验证。"""
import sys
import time

sys.path.insert(0, r'E:\DS\mhxy-gui-automation')
from tools.probe_routes import lua, cur_map

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
  _G.__out = "wait"
end
'''

PICK = r'''
local d = tp.窗口.对话栏
if not d or not d.可视 or not d.选项 then _G.__out = "no_dialog" return end
for i=1,#d.选项 do
  local c = tostring(d.选项[i].基本内容 or "")
  if c:find("我要去") then
    local ok, err = pcall(function() d:事件解析(d.选项[i].跳转链接) end)
    _G.__out = "picked ok="..tostring(ok)
    return
  end
end
_G.__out = "no_go_option"
'''

STATE = r'''
local m = tostring(tp.当前地图 or "?")
local p = tp.角色坐标
local pos = "?"
if p and type(p) == "table" then pos = tostring(p.x)..","..tostring(p.y) end
_G.__out = "map="..m.." pos="..pos
'''

if __name__ == '__main__':
    print('before:', lua(STATE))
    lua(r'pcall(function() if tp.窗口.对话栏 and tp.窗口.对话栏.关闭 then tp.窗口.对话栏:关闭() end end)')
    time.sleep(0.5)
    print('call:', lua(CALL))
    for i in range(12):
        time.sleep(0.3)
        s = lua(POLL)
        if s.startswith('ready'):
            break
    print('poll:', s)
    time.sleep(0.2)
    print('pick:', lua(PICK))
    for i in range(6):
        time.sleep(1.0)
        st = lua(STATE)
        print(f'{i+1}s:', st)
    print('final:', cur_map())
