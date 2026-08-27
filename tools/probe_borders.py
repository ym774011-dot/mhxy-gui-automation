# -*- coding: utf-8 -*-
"""遍历边界找花果山入口。"""
import sys
import time

sys.path.insert(0, r'E:\DS\mhxy-gui-automation')
from tools.probe_routes import lua
from library.map_packs.ALG import ALG

STATE = r'''
local p = tp.角色坐标
local pos = type(p)=="table" and string.format("%.0f,%.0f", p.x, p.y) or "?"
_G.__out = "mapid="..tostring(tp.当前地图).." pos="..pos
'''

def wait_transition(base_map, tries=12):
    for i in range(tries):
        time.sleep(1.0)
        st = lua(STATE)
        if f'mapid={base_map}' not in st:
            return st
    return None

if __name__ == '__main__':
    cur = lua(STATE)
    print('start:', cur)
    mid = cur.split('mapid=')[1].split(' ')[0]

    # 1093 边界探测（若当前在1093）
    probes_1093 = [(45, 3), (45, 28), (3, 15), (80, 15), (3, 5), (80, 5)]
    # 1092 北缘不同 x 探测
    probes_1092 = [(50, 3), (100, 3), (150, 3), (190, 3), (20, 3)]

    probe_map = probes_1093 if mid == '1093' else probes_1092
    for target in probe_map:
        st = lua(STATE)
        m = st.split('mapid=')[1].split(' ')[0]
        print(f'--- probe {target} (now {m}) ---')
        if (m == '1093') != (target in probes_1093):
            print('  探测表不匹配当前地图，跳过（先手动走回）')
            continue
        try:
            ALG(target, pid=13924, background=True, verbose=False)
        except Exception as e:
            print('  ALG err:', e)
            continue
        r = wait_transition(m)
        if r:
            print('  >>> 切图:', r)
            newmid = r.split('mapid=')[1].split(' ')[0]
            if newmid != m:
                continue
        else:
            # 没切图，走下一个探测点
            print('  无切图:', lua(STATE))
