# -*- coding: utf-8 -*-
"""在东海湾找船夫并交互，观察传送傲来国的方式。"""
import sys
import time

sys.path.insert(0, r'E:\DS\mhxy-gui-automation')
from tools.probe_routes import http_json, lua, lua_expr, cur_map, routes

# 1. 确保在东海湾
m = cur_map()
print('当前:', m)
if not m.startswith('1506'):
    print('hop 回东海湾...')
    for d in ['长安传送江南野外', '江南野外传送建邺城', '建邺城进东海湾新']:
        http_json('/api/act/cross_map', {'desc': d, 'x': 100, 'y': 100,
                                         'wait_ms': 3500, 'sync': True}, timeout=30)
        time.sleep(1.5)
    print('现在:', cur_map())

# 2. 扫描场景人物找船夫
code = r'''
local out = {}
local t = tp.场景.场景人物
if t then for k,v in pairs(t) do
  local n = tostring(v.名称 or "?")
  if n:find("船夫") or n:find("傲来") or n:find("传送") then
    local id = tostring(v.编号 or v.ID or "?")
    local x = v.坐标 and tostring(v.坐标.x) or "?"
    local y = v.坐标 and tostring(v.坐标.y) or "?"
    out[#out+1] = n.."#"..id.."@"..x..","..y
  end
end end
_G.__out = table.concat(out, " ;; ")
'''
print('船夫:', lua(code))

# 3. 全人物列表（找相近的）
code2 = r'''
local out = {}
local t = tp.场景.场景人物
if t then for k,v in pairs(t) do
  out[#out+1] = tostring(v.名称 or "?")
end end
_G.__out = table.concat(out, ",")
'''
print('全部人物:', lua(code2))
