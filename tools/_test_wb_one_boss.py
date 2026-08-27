# -*- coding: utf-8 -*-
"""实测 WORLD_BOSS 单只 BOSS 完整链路：CALL→对话选项→战斗。"""
import sys
sys.path.insert(0, r"E:/DS/mhxy-gui-automation")

from tasks.library.WORLD_BOSS import (
    _lua_expr, _lua, DEFAULT_GATEWAY,
    _farm_one_boss, _boss_battle_keywords, DEFAULT_BATTLE_KEYWORDS,
    call_npc_event_start, close_dialog,
)

GW = DEFAULT_GATEWAY


def try_expr(expr):
    try:
        return repr(_lua_expr(GW, expr))
    except Exception as e:
        return f"ERR: {e}"


# ---- 1) 探测地图名与角色位置字段 ----
print("== 字段探测 ==")
for e in [
    'tostring(tp.当前地图 or "")',
    'tostring(tp.当前地图.名字 or "")',
    'tostring(type(tp.主角))',
    'tostring(tp.主角 and tp.主角.x or "nil_x")',
]:
    print(" ", e[:44], "=>", try_expr(e))

try:
    import json, urllib.request
    req = urllib.request.Request(GW + "/api/position")
    with urllib.request.urlopen(req, timeout=8) as r:
        print("  /api/position =>", r.read().decode("utf-8", "replace")[:300])
except Exception as e:
    print("  /api/position ERR:", e)

# ---- 2) 单只 BOSS 实测（最近一只：id=2 妖魔 @25,22）----
print("\n== 单只 BOSS 实测 ==")
boss = {"id": "2", "name": "妖魔", "gx": 25, "gy": 22,
        "bsid": "1_12_68_105_1787836200_80_91073671"}
kw = _boss_battle_keywords(boss["name"], DEFAULT_BATTLE_KEYWORDS)
print("关键词:", kw)

res = _farm_one_boss(
    gateway=GW, boss=boss, battle_keywords=kw,
    battle_timeout=120.0, walk_background=True, verbose=True, cur_map="",
)
print("RESULT:", res)
