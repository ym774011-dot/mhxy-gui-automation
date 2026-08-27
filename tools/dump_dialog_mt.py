# -*- coding: utf-8 -*-
"""dump 对话栏窗口元表方法列表。"""
import sys
import time

sys.path.insert(0, r'E:\DS\mhxy-gui-automation')
from tools.probe_routes import lua
from tools.chuanfu_full import CALL, POLL

MT = r'''
local d = tp.窗口.对话栏
if not d then _G.__out = "no_dialog" return end
local out = {}
local mt = getmetatable(d)
if mt and mt.__index then
  local mi = mt.__index
  local names = {}
  for k,v in pairs(mi) do
    names[#names+1] = tostring(k)..":"..type(v)
  end
  table.sort(names)
  out[#out+1] = table.concat(names, "\n")
else
  out[#out+1] = "no_mt"
end
_G.__out = table.concat(out, "\n")
'''

if __name__ == '__main__':
    lua(r'pcall(function() if tp.窗口.对话栏 and tp.窗口.对话栏.关闭 then tp.窗口.对话栏:关闭() end end)')
    time.sleep(0.5)
    lua(CALL)
    for i in range(12):
        time.sleep(0.3)
        s = lua(POLL)
        if s.startswith('ready'):
            break
    print('poll:', s)
    print(lua(MT))
