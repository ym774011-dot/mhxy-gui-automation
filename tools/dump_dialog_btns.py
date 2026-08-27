# -*- coding: utf-8 -*-
"""挖对话栏资源组3/4的按钮坐标与文字。"""
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
  for _,gi in ipairs({3,4}) do
    local g = d.资源组 and d.资源组[gi]
    if g then
      out[#out+1] = "== 资源组"..gi.." 按钮数量="..tostring(g.按钮数量)
      out[#out+1] = "   按钮文字=["..tostring(g.按钮文字).."]"
      out[#out+1] = "   事件="..tostring(g.事件).." 窗口按钮="..tostring(g.窗口按钮)
      if g.按钮 then
        for bi=1,#g.按钮 do
          local b = g.按钮[bi]
          if type(b) == "table" then
            local parts = {}
            for kk,vv in pairs(b) do
              if type(vv) == "number" then parts[#parts+1] = tostring(kk).."="..tostring(vv)
              elseif type(vv) == "string" then parts[#parts+1] = tostring(kk).."=["..vv.."]"
              else parts[#parts+1] = tostring(kk)..":"..type(vv) end
            end
            out[#out+1] = "   btn"..bi.."{ "..table.concat(parts," ").." }"
          else
            out[#out+1] = "   btn"..bi.." type="..type(b)
          end
        end
      end
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
