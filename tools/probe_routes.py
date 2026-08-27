# -*- coding: utf-8 -*-
"""WORLD_BOSS 路线探测临时脚本：dump 各图传送表，收集精确切换 desc。"""
import json
import time
import urllib.request

GW = 'http://127.0.0.1:18082'


def http_json(path, data=None, timeout=25):
    body = json.dumps(data).encode('utf-8') if data is not None else None
    req = urllib.request.Request(GW + path, data=body,
                                 headers={'Content-Type': 'application/json'}
                                 if body else {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8', 'replace'))


def lua(code):
    r = http_json('/api/lua', {'code': code})
    return (r.get('result') or {}).get('value')


def lua_expr(expr):
    return http_json('/api/lua/expr', {'expr': expr})['result']['value']


def cur_map():
    mid = lua_expr('tostring(tp.当前地图 or "?")')
    mname = lua_expr("tostring(tp.场景 and tp.场景.名称 or '-')")
    return f'{mid}|{mname}'


def routes():
    code = ('local out={} local t=tp.场景.传送 '
            'if t then for i=1,#t do '
            'local s=tostring(t[i].切换 or "?") local xy="" '
            'if t[i].坐标 then xy=tostring(t[i].坐标.x)..","..tostring(t[i].坐标.y) end '
            'out[#out+1]=s.." @"..xy end end '
            '_G.__out=table.concat(out," ;; ")')
    v = lua(code)
    return [x.strip() for x in (v or '').split(';;') if x.strip()]


def cross_map(desc, wait=3.5):
    r = http_json('/api/act/cross_map',
                  {'desc': desc, 'x': 100, 'y': 100,
                   'wait_ms': int(wait * 1000), 'sync': True}, timeout=30)
    time.sleep(1.8)
    return r


def hop(chain):
    for desc in chain:
        print(f'  hop: {desc} -> {cross_map(desc)}')


if __name__ == '__main__':
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'info'
    if cmd == 'info':
        print('MAP:', cur_map())
        for r in routes():
            print(' ', r)
    elif cmd == 'chain':
        # 用法: python probe_routes.py chain "desc1|desc2|desc3"
        chain = sys.argv[2].split('|')
        hop(chain)
        print('NOW:', cur_map())
