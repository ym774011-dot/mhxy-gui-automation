# -*- coding: utf-8 -*-
"""dump选项选中判断条件。"""
import sys
import time

sys.path.insert(0, r'E:\DS\mhxy-gui-automation')
from tools.probe_routes import lua
from tools.chuanfu_full import CALL, POLL

DUMP = r'''
local d = tp.窗口.对话栏
if not d or not d.可视 then _G.__out = "no_visible_dialog" return end
local out = {}
local ok, err = pcall(function()
  for i=1,#d.选项 do
    local o = d.选项[i]
    local sj = o.选中判断
    if type(sj) == "table" then
      local parts = {}
      for kk,vv in pairs(sj) do
        if type(vv) == "table" then
          local sub = {}
          for k3,v3 in pairs(vv) do sub[#sub+1] = tostring(k3).."="..tostring(v3) end
          parts[#parts+1] = tostring(kk).."{"..table.concat(sub,",").."}"
        else
          parts[#parts+1] = tostring(kk).."="..tostring(vv)
        end
      end
      out[#out+1] = "opt"..i.." 选中判断{ "..table.concat(parts," ").." }"
    else
      out[#out+1] = "opt"..i.." 选中判断类型="..type(sj)
    end
  end
end)
if not ok then out[#out+1] = "ERR:"..tostring(err) end
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
    print(lua(DUMP))
