# -*- coding: utf-8 -*-
"""1093 北行用完整 ALG 流程。"""
import sys
import time

sys.path.insert(0, r'E:\DS\mhxy-gui-automation')
from tools.probe_routes import lua
from library.map_packs.ALG import ALG

STATE = r'''
local p = tp.角色坐标
local pos = type(p)=="table" and string.format("%.0f,%.0f", p.x, p.y) or "?"
local mm = tp.窗口.小地图 and tp.窗口.小地图.地图名称 or "?"
_G.__out = "mapid="..tostring(tp.当前地图).." name=["..tostring(mm).."] pos="..pos
'''

if __name__ == '__main__':
    for target in [(38, 15), (38, 5), (38, 2)]:
        print(f'--- ALG walk {target} ---')
        try:
            ALG(target, pid=13924, background=True, verbose=True)
        except Exception as e:
            print('ALG err:', e)
        prev = ''
        for i in range(10):
            time.sleep(1.0)
            st = lua(STATE)
            if st != prev:
                print(f'{i+1}s:', st)
                prev = st
            if 'mapid=1093' not in st:
                print('>>> 地图切换！', st)
                sys.exit(0)
