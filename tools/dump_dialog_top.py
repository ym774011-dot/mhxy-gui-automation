# -*- coding: utf-8 -*-
"""dump 对话栏顶层所有键与选项元素类型。"""
import sys
import time

sys.path.insert(0, r'E:\DS\mhxy-gui-automation')
from tools.probe_routes import lua
from tools.chuanfu_full import CALL, POLL

TOP = r'''
local d = tp.窗口.对话栏
if not d or not d.可视 then _G.__out = "no_visible_dialog" return end
local out = {}
for k,v in pairs(d) do
  out[#out+1] = tostring(k)..":"..type(v)
end
local sel = d.选项
if type(sel) == "table" then
  out[#out+1] = "sel_len="..tostring(#sel)
  for i=1,math.min(#sel,5) do
    local o = sel[i]
    local sub = {}
    if type(o) == "table" then
      for kk,vv in pairs(o) do sub[#sub+1] = tostring(kk)..":"..type(vv) end
    end
    out[#out+1] = "opt"..i.." type="..type(o).." keys=["..table.concat(sub,",").."]"
  end
else
  out[#out+1] = "sel_type="..type(sel)
end
_G.__out = table.concat(out, "\n")
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
    print(lua(TOP))
