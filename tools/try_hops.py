# -*- coding: utf-8 -*-
"""尝试若干候选切换 desc，打印生效与否及当前图 ID。"""
import sys
import time

sys.path.insert(0, r'E:\DS\mhxy-gui-automation')
from tools.probe_routes import http_json, cur_map, cross_map


def try_descs(descs):
    for d in descs:
        m0 = cur_map()
        try:
            r = cross_map(d)
            time.sleep(1.0)
        except Exception as e:
            print(f'[{d}] EXC {e}')
            continue
        m1 = cur_map()
        changed = (m1 != m0) or not str(r.get('error'))
        print(f'[{d}] before={m0} after={m1} err={r.get("error")}')
        if m1 != m0:
            print('   >>> 生效! 现在所在:', m1)
            return d
    return None


if __name__ == '__main__':
    cands = [
        '大唐境外传送长寿郊外',
        '大唐境外进长寿郊外',
        '长寿郊外传送大唐境外',
    ]
    got = try_descs(cands)
    print('RESULT:', got or '全部失败')
