# -*- coding: utf-8 -*-
"""_boss_priority 离线回归（六定案：未登记=None，词缀归级）。

★ 2026-08-29 同步：优先级档位由用户重新定案为六档（WORLD_BOSS.PRI_* 常量），
本用例随之对齐。旧版用例仍编码 2026-08-28 的三档（稀有1 / 头领2 / 杂鱼3），
与新实现不符，会误报 13 FAIL —— 那不是代码回归，是本文件过期。
改档位时务必同步 BOSS_PRIORITY 与本文件，否则回归失效。

现行档位（数字越小越优先）：
    P0 三界财神爷 ＞ P1 二十八星君 ＞ P2 知了王 ＞ P3 头领/统领
      ＞ P4 其余白名单（灵猴/十二生肖/天罡星/地煞星）＞ P5 妖族杂鱼

运行：E:/py/python.exe tools/_test_priority_regress.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tasks.library.WORLD_BOSS import (_boss_priority, BOSS_PRIORITY,
                                      PRI_CAISHEN, PRI_STARLORD, PRI_ZHILIAO,
                                      PRI_TOULING, PRI_WHITELIST, PRI_TRASH)

CASES = [
    # (输入, 期望优先级, 说明)
    ("三界财神爷", PRI_CAISHEN, "P0 财神最高"),
    ("娄金狗", PRI_STARLORD, "P1 二十八星君"),
    ("知了王", PRI_ZHILIAO, "P2 知了王"),
    ("妖魔头领", PRI_TOULING, "P3 头领"),
    ("妖魔统领", PRI_TOULING, "P3 统领"),
    ("天降灵猴", PRI_WHITELIST, "P4 灵猴"),
    ("下凡的灵猴", PRI_WHITELIST, "P4 灵猴"),
    ("地煞星", PRI_WHITELIST, "P4 地煞星"),
    ("天罡星", PRI_WHITELIST, "P4 天罡星"),
    ("初出茅庐地煞星", PRI_WHITELIST, "P4 词缀归级（地煞星）"),
    ("六耳猕猴天罡星", PRI_WHITELIST, "P4 任意词缀+天罡星归级"),
    ("妖魔鬼怪", PRI_TRASH, "P5 垫底"),
    ("妖魔", PRI_TRASH, "P5 垫底"),
    ("鬼怪", PRI_TRASH, "P5 垫底"),
    ("赐福星官", None, "星官黑名单=非目标"),
    ("心魔", None, "心魔=非目标"),
    ("江湖大盗", None, "未登记NPC=非目标"),
    ("白骨精", None, "未登记=非目标"),
    ("", None, "空串=非目标"),
    (None, None, "None输入安全"),
]

# 档位单调性：P0 < P1 < P2 < P3 < P4 < P5（数字越小越优先）
_tiers = [PRI_CAISHEN, PRI_STARLORD, PRI_ZHILIAO, PRI_TOULING, PRI_WHITELIST, PRI_TRASH]
_monotonic = all(_tiers[i] < _tiers[i + 1] for i in range(len(_tiers) - 1))
print(f"  {'PASS' if _monotonic else 'FAIL'}  档位单调性 P0<P1<P2<P3<P4<P5: {_tiers}")
if not _monotonic:
    globals()['fails'] = globals().get('fails', 0) + 1

fails = 0
for name, want, note in CASES:
    got = _boss_priority(name)
    ok = got == want
    if not ok:
        fails += 1
    print(f"  {'PASS' if ok else 'FAIL'}  {name!r:<20} -> {got}  (期望 {want})  {note}")

# 排序验证：财神(P0) > 头领(P3) > 地煞词缀(P4) > 妖魔鬼怪(P5) > 未登记
names = ["妖魔鬼怪", "初出茅庐地煞星", "赐福星官", "妖魔头领", "三界财神爷", "江湖大盗"]
ranked = sorted(names, key=lambda n: (_boss_priority(n) is None, _boss_priority(n) if _boss_priority(n) is not None else 99))
expect_order = ["三界财神爷", "妖魔头领", "初出茅庐地煞星", "妖魔鬼怪"]
order_ok = [n for n in ranked if _boss_priority(n) is not None] == expect_order
print(f"  {'PASS' if order_ok else 'FAIL'}  排序: {ranked}")
if not order_ok:
    fails += 1

print(f"\n=== {'ALL PASS' if fails == 0 else f'{fails} FAIL'} ===")
sys.exit(0 if fails == 0 else 1)
