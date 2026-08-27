# -*- coding: utf-8 -*-
"""用 选项解析 点船夫传送选项。"""
import sys
import time

sys.path.insert(0, r'E:\DS\mhxy-gui-automation')
from tools.probe_routes import lua

STATE = r'''
local m = tostring(tp.当前地图 or "?")
local p = tp.角色坐标
local pos = "?"
if p and type(p) == "table" then pos = tostring(p.x)..","..tostring(p.y) end
_G.__out = "map="..m.." pos="..pos
'''

PICK2 = r'''
local d = tp.窗口.对话栏
if not d or not d.可视 or not d.选项 then _G.__out = "no_dialog" return end
local opt
for i=1,#d.选项 do
  if tostring(d.选项[i].基本内容 or ""):find("我要去") then opt = d.选项[i] break end
end
if not opt then _G.__out = "no_opt" return end
local ok, err = pcall(function() d:选项解析(opt) end)
_G.__out = "sel_ok="..tostring(ok).." err="..tostring(err)
'''

if __name__ == '__main__':
    print('state0:', lua(STATE))
    # 对话可能已被上次实验关掉，重新走一遍
    from tools.chuanfu_full import CALL, POLL
    lua(r'pcall(function() if tp.窗口.对话栏 and tp.窗口.对话栏.关闭 then tp.窗口.对话栏:关闭() end end)')
    time.sleep(0.5)
    print('call:', lua(CALL))
    s = ''
    for i in range(12):
        time.sleep(0.3)
        s = lua(POLL)
        if s.startswith('ready'):
            break
    print('poll:', s)
    time.sleep(0.2)
    print('pick:', lua(PICK2))
    for i in range(5):
        time.sleep(1.0)
        print(f'{i+1}s:', lua(STATE))
