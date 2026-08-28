# -*- coding: utf-8 -*-
"""_boss_priority 离线回归（六定案：未登记=None，词缀归级）。

运行：E:/py/python.exe tools/_test_priority_regress.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tasks.library.WORLD_BOSS import _boss_priority, BOSS_PRIORITY

CASES = [
    # (输入, 期望优先级, 说明)
    ("三界财神爷", 0, "财神最高"),
    ("知了王", 1, "稀有1"),
    ("天降灵猴", 1, "稀有1"),
    ("下凡的灵猴", 1, "稀有1"),
    ("地煞星", 1, "星1"),
    ("天罡星", 1, "星1"),
    ("初出茅庐地煞星", 1, "词缀归级=1"),
    ("六耳猕猴天罡星", 1, "任意词缀+天罡星归级=1"),
    ("妖魔头领", 2, "头领2"),
    ("妖魔统领", 2, "统领2"),
    ("妖魔鬼怪", 3, "垫底3"),
    ("妖魔", 3, "垫底3"),
    ("鬼怪", 3, "垫底3"),
    ("赐福星官", None, "星官黑名单=非目标"),
    ("心魔", None, "心魔=非目标"),
    ("江湖大盗", None, "未登记NPC=非目标"),
    ("白骨精", None, "未登记=非目标"),
    ("", None, "空串=非目标"),
    (None, None, "None输入安全"),
]

fails = 0
for name, want, note in CASES:
    got = _boss_priority(name)
    ok = got == want
    if not ok:
        fails += 1
    print(f"  {'PASS' if ok else 'FAIL'}  {name!r:<20} -> {got}  (期望 {want})  {note}")

# 排序验证：财神 > 地煞词缀 > 头领 > 妖魔鬼怪 > 未登记
names = ["妖魔鬼怪", "初出茅庐地煞星", "赐福星官", "妖魔头领", "三界财神爷", "江湖大盗"]
ranked = sorted(names, key=lambda n: (_boss_priority(n) is None, _boss_priority(n) if _boss_priority(n) is not None else 99))
expect_order = ["三界财神爷", "初出茅庐地煞星", "妖魔头领", "妖魔鬼怪"]
order_ok = [n for n in ranked if _boss_priority(n) is not None] == expect_order
print(f"  {'PASS' if order_ok else 'FAIL'}  排序: {ranked}")
if not order_ok:
    fails += 1

print(f"\n=== {'ALL PASS' if fails == 0 else f'{fails} FAIL'} ===")
sys.exit(0 if fails == 0 else 1)
