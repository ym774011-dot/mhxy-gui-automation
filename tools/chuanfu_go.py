# -*- coding: utf-8 -*-
"""船夫对话点'是的我要去'，确认落地傲来国。"""
import sys
import time

sys.path.insert(0, r'E:\DS\mhxy-gui-automation')
from tools.probe_routes import lua, cur_map

PICK = r'''
local d = tp.窗口.对话栏
if not d or not d.可视 or not d.选项 then _G.__out = "no_dialog" return end
for i=1,#d.选项 do
  local c = tostring(d.选项[i].基本内容 or "")
  if c:find("我要去") or c:find("是") and not c:find("逛") then
    local ok, err = pcall(function() d:事件解析(d.选项[i].跳转链接) end)
    _G.__out = "picked["..c.."] ok="..tostring(ok).." err="..tostring(err)
    return
  end
end
_G.__out = "no_go_option"
'''

if __name__ == '__main__':
    print('pick:', lua(PICK))
    time.sleep(2.5)
    print('落地:', cur_map())
