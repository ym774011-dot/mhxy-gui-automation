# -*- coding: utf-8 -*-
"""1093 场景人物扫描 + 继续北行探花果山。"""
import sys
import time

sys.path.insert(0, r'E:\DS\mhxy-gui-automation')
from tools.probe_routes import lua

STATE = r'''
local p = tp.角色坐标
local pos = type(p)=="table" and string.format("%.0f,%.0f", p.x, p.y) or "?"
local mm = tp.窗口.小地图 and tp.窗口.小地图.地图名称 or "?"
_G.__out = "mapid="..tostring(tp.当前地图).." name=["..tostring(mm).."] pos="..pos
'''

NPCS = r'''
local out = {}
local t = tp.场景.场景人物
if t then for k,v in pairs(t) do
  local n = tostring(v.名称 or "?")
  local x = v.坐标 and string.format("%.0f", v.坐标.x) or "?"
  local y = v.坐标 and string.format("%.0f", v.坐标.y) or "?"
  out[#out+1] = n.."@"..x..","..y
end end
_G.__out = table.concat(out, " ;; ")
'''

if __name__ == '__main__':
    print('state:', lua(STATE))
    print('npcs:', lua(NPCS))

    # 继续北行：当前(38,27)，往 (38,8) 走（1093 客户区缩放与1092相同？用同套换算）
    from library.map_packs.ALG import game_to_pixel, _click_background
    from core.window_manager import window_manager as wm
    for target in [(38, 15), (38, 5)]:
        gx, gy = target
        px, py = game_to_pixel(gx, gy)
        print(f'--- click {target} -> pixel({px},{py}) ---')
        _click_background(wm.hwnd, px, py)
        prev = None
        for i in range(10):
            time.sleep(1.0)
            st = lua(STATE)
            if st != prev:
                print(f'{i+1}s:', st)
                prev = st
            if 'mapid=1093' not in st:
                print('地图切换！', st)
                sys.exit(0)
