# -*- coding: utf-8 -*-
"""二分定位 Lua 探针故障段。"""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
spec = importlib.util.spec_from_file_location(
    "ZGUI", os.path.join(ROOT, "tasks", "library", "ZGUI.py"))
ZGUI = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ZGUI)

gw = sys.argv[1] if len(sys.argv) > 1 else "file://pzxy_p18908"
tests = {
    "t1 类型": "local jd=tp.主界面 and tp.主界面.界面数据 __out=type(jd)",
    "t2 计数": "local jd=tp.主界面.界面数据 local n=0 for i=1,80 do if type(jd[i])=='table' then n=n+1 end end __out=tostring(n)",
    "t3 pattern": "local s='朱紫国 [158,511]' __out=tostring(s:find('朱紫国')~=nil)..tostring(s:match('%[%d+,%d+%]')~=nil)",
    "t4 找朱紫国": "local jd=tp.主界面.界面数据 local h={} for i=1,80 do local p=jd[i] if type(p)=='table' then local v=p.文字 if type(v)=='string' and v:find('朱紫国') then h[#h+1]=i end end end __out=table.concat(h,',')",
    "t5 寻路": "local a={} local m=tp.地图.寻路 if type(m)=='table' then local n=0 for k,v in pairs(m) do n=n+1 if n<=10 then a[#a+1]=tostring(k)..'='..(type(v)=='table' and 'T' or tostring(v)) end end __out='n'..n..' '..table.concat(a,' ') else __out=type(m) end",
    "t6 选中数据": "local a={} local m=tp.地图.选中数据 if type(m)=='table' then for k,v in pairs(m) do a[#a+1]=tostring(k)..'='..(type(v)=='table' and 'T' or tostring(v)) end end __out=table.concat(a,' ')",
}
for tag, c in tests.items():
    try:
        r = ZGUI._lua_call(gw, c, timeout=10.0)
        print(tag, "=>", repr(r))
    except Exception as e:
        print(tag, "EXC", e)
