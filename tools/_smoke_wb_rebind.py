# -*- coding: utf-8 -*-
"""临时冒烟 v2：用 _lua_expr（正确契约）验证 gateway attach 6232。"""
import sys
sys.path.insert(0, r"E:/DS/mhxy-gui-automation")

from tasks.library.WORLD_BOSS import _lua_expr, DEFAULT_GATEWAY

G = DEFAULT_GATEWAY
print("[smoke] tp 类型:", _lua_expr(G, "type(tp)"))
print("[smoke] 当前地图:", repr(_lua_expr(G, "tostring(tp.当前地图名 or tp.当前地图 or '')")))
print("[smoke] 角色 x:", _lua_expr(G, "tostring(tp.角色坐标.x)"))
print("[smoke] 角色 y:", _lua_expr(G, "tostring(tp.角色坐标.y)"))
print("[smoke] 场景人物数:", _lua_expr(G, "tostring(tp.场景.场景人物 and #tp.场景.场景人物 or -1)"))
