# -*- coding: utf-8 -*-
"""读船夫对话选项文本与跳转链接。"""
import sys
import time

sys.path.insert(0, r'E:\DS\mhxy-gui-automation')
from tools.probe_routes import lua
from tools.chuanfu_full import CALL, POLL

READ = r'''
local d = tp.窗口.对话栏
if not d or not d.可视 then _G.__out = "no_visible_dialog" return end
local out = {"正文="..tostring(d.文本内容)}
if d.选项 then
  for i=1,#d.选项 do
    local o = d.选项[i]
    out[#out+1] = string.format("opt%d 内容=[%s] 链接=[%s]", i,
      tostring(o.基本内容), tostring(o.跳转链接))
  end
end
_G.__out = table.concat(out, "\n")
'''

PICK = r'''
local d = tp.窗口.对话栏
if not d or not d.可视 or not d.选项 then _G.__out = "no_dialog" return end
local link
for i=1,#d.选项 do
  local c = tostring(d.选项[i].基本内容 or "")
  if c:find("傲来") then link = d.选项[i].跳转链接 break end
end
if not link then _G.__out = "no_al_link" return end
local ok, err = pcall(function() d:事件解析(link) end)
_G.__out = "pick_ok="..tostring(ok).." err="..tostring(err)
'''

if __name__ == '__main__':
    lua(r'pcall(function() if tp.窗口.对话栏 and tp.窗口.对话栏.关闭 then tp.窗口.对话栏:关闭() end end)')
    time.sleep(0.5)
    print('call:', lua(CALL))
    for i in range(12):
        time.sleep(0.3)
        state = lua(POLL)
        if state.startswith('ready'):
            break
    print('poll:', state)
    time.sleep(0.3)
    print(lua(READ))
    print('--- 点傲来选项 ---')
    print(lua(PICK))
