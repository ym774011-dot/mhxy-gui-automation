# -*- coding: utf-8 -*-
"""短时实测 WORLD_BOSS_auto_farm 完整循环。"""
import sys
sys.path.insert(0, r"E:/DS/mhxy-gui-automation")

from tasks.library.WORLD_BOSS import WORLD_BOSS_auto_farm

res = WORLD_BOSS_auto_farm(
    max_runtime=180.0,          # 只跑 3 分钟观察
    battle_timeout=90.0,
    verbose=True,
)
print("AUTO_FARM_RESULT:", res)
