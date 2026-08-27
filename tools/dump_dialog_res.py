# -*- coding: utf-8 -*-
"""dump 对话栏 资源组/丰富文本/记录文本 结构找按钮坐标。"""
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
  out[#out+1] = "win x="..tostring(d.x).." y="..tostring(d.y)
  local function dtbl(name, t, depth)
    if not t or depth > 2 then return end
    local n = 0
    for k,v in pairs(t) do
      n = n + 1
      if n > 12 then out[#out+1] = name.."...(truncated)" break end
      if type(v) == "table" then
        local sub = {}
        local m = 0
        for kk,vv in pairs(v) do
          m = m + 1
          if m > 8 then sub[#sub+1] = "..." break end
          sub[#sub+1] = tostring(kk)..":"..type(vv)..(type(vv)=="number" and ("="..tostring(vv)) or "")
        end
        out[#out+1] = name.."."..tostring(k).."{ "..table.concat(sub," ").." }"
      else
        out[#out+1] = name.."."..tostring(k).."="..type(v)..(type(v)=="string" and ("["..tostring(v).."]") or (type(v)=="number" and ("="..tostring(v)) or ""))
      end
    end
  end
  dtbl("资源组", d.资源组, 1)
  dtbl("丰富文本", d.丰富文本, 1)
  dtbl("记录文本", d.记录文本, 1)
  dtbl("头像", d.头像, 1)
  dtbl("背景窗口", d.背景窗口, 1)
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
