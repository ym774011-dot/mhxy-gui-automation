# -*- coding: utf-8 -*-
"""傲来国往北走探测花果山边界。"""
import sys
import time

sys.path.insert(0, r'E:\DS\mhxy-gui-automation')
from core.window_manager import window_manager as wm
from tools.probe_routes import lua

ok = wm.find_by_pid(13924)
print('bind:', ok, 'hwnd:', wm.hwnd)

STATE = r'''
local p = tp.角色坐标
local pos = "?"
if p and type(p) == "table" then pos = string.format("%.0f,%.0f", p.x, p.y) end
local m = tostring(tp.当前地图 or "?")
_G.__out = "map="..m.." pos="..pos
'''
print('now:', lua(STATE))

# 用 ALG 包往北走：先到 (166,100)（角色x保持船夫附近区域），再 (166,20) 顶部
from library.map_packs.ALG import ALG

for target in [(166, 100), (166, 40), (166, 10)]:
    print(f'--- walk to {target} ---')
    try:
        ALG(target, pid=13924, background=True, verbose=True)
    except Exception as e:
        print('ALG err:', e)
    for i in range(8):
        time.sleep(1.0)
        st = lua(STATE)
        print(f'{i+1}s:', st)
        m = st.split('map=')[1].split(' ')[0]
        if m != '1092':
            print('地图切换！', st)
            sys.exit(0)
