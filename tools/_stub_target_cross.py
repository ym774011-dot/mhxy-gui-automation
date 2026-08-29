# -*- coding: utf-8 -*-
"""_stub_target_cross - 2026-08-29 离线桩测试：验证 WORLD_BOSS 的"目标名单运行期登记 +
_boss_priority 兜底" 与 "_pick_target 平级交叉攻击"。

纯离线：只 import WORLD_BOSS 的纯函数（_pick_target/_boss_priority/_RUN_TARGET_BOSSES/
PRI_WHITELIST），不连游戏、不发网请求、不触碰窗口/网关。
运行：E:\\py\\python.exe tools\\_stub_target_cross.py
全体断言通过 → 打印 "ALL STUB ASSERTIONS PASSED"，否则抛 AssertionError。
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # e:\DS\mhxy-gui-automation
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from tasks.library.WORLD_BOSS import (  # noqa: E402
    _pick_target, _boss_priority, _RUN_TARGET_BOSSES, PRI_WHITELIST,
)


def _name(x):
    return x["name"] if x is not None else None


def _check(cond, msg):
    if not cond:
        raise AssertionError("FAIL: " + msg)


# ---- 断言 1：_RUN_TARGET_BOSSES 兜底 -------------------------------------
# 名单内且未映射档位 → PRI_WHITELIST
import tasks.library.WORLD_BOSS as WB

WB._RUN_TARGET_BOSSES = frozenset({"某种新白名单怪"})
_check(_boss_priority("某种新白名单怪") == PRI_WHITELIST,
       "断言1：名单内未登记名应兜底为 PRI_WHITELIST")
WB._RUN_TARGET_BOSSES = frozenset()
_check(_boss_priority("某种新白名单怪") is None,
       "断言1：名单清空后未登记名应为 None（非目标）")
# 2026-08-29：新型冠状病毒已直接登记进 BOSS_PRIORITY（PRI_WHITELIST）——
# 即使清空运行名单也恒为 P3，且默认名单包含它
_check("新型冠状病毒" in WB.DEFAULT_TARGET_BOSSES,
       "断言1b：默认目标名单应包含 新型冠状病毒")
_check(_boss_priority("新型冠状病毒") == PRI_WHITELIST,
       f"断言1b：新型冠状病毒 应为 P3，实际 {_boss_priority('新型冠状病毒')}")


def _mk(live, gx0, gy0, last=None, only_top=False):
    return _pick_target(live, gx0, gy0, only_top=only_top, last_name=last)


# ---- 断言 2：_pick_target 平级交叉攻击 -----------------------------------
WB._RUN_TARGET_BOSSES = frozenset({"新型冠状病毒"})
live = [
    {"name": "下凡的灵猴", "gx": 5, "gy": 0},
    {"name": "新型冠状病毒", "gx": 8, "gy": 0},
    {"name": "下凡的灵猴", "gx": 40, "gy": 0},
]
# 2a) last_name=None → 距离优先，选最近"下凡的灵猴"@(5,0)
_check(_name(_mk(live, 0, 0)) == "下凡的灵猴"
       and _mk(live, 0, 0)["gx"] == 5,
       "断言2a：last_name=None 应选最近同名@(5,0)")
# 2b) last_name=灵猴 → 异名目标仍在容差内，切换为"新型冠状病毒"@(8,0)
r2b = _mk(live, 0, 0, last="下凡的灵猴")
_check(r2b["name"] == "新型冠状病毒" and r2b["gx"] == 8,
       f"断言2b：应切异名@(8,0)，实际 {r2b}")
# 2c) last_name=灵猴 且异名移远(gx=60 远超容差) → 仍选"下凡的灵猴"@(5,0)
live_far = [
    {"name": "下凡的灵猴", "gx": 5, "gy": 0},
    {"name": "新型冠状病毒", "gx": 60, "gy": 0},
    {"name": "下凡的灵猴", "gx": 40, "gy": 0},
]
r2c = _mk(live_far, 0, 0, last="下凡的灵猴")
_check(r2c["name"] == "下凡的灵猴" and r2c["gx"] == 5,
       f"断言2c：异名太远不应切换，实际 {r2c}")


# ---- 断言 3：优先级链（2026-08-29 用户定案新链：财神爷＞星宿＞头领=统领=知了王＞白名单＞杂鱼）
chain = [
    ("三界财神爷", 0), ("娄金狗", 1), ("知了王", 2),
    ("妖魔头领", 2), ("妖魔统领", 2), ("下凡的灵猴", 3), ("妖魔", 4),
]
for nm, p in chain:
    _check(_boss_priority(nm) == p, f"断言3：{nm} 应为 P{p}，实际 {_boss_priority(nm)}")
_check(_boss_priority("妖魔头领") == _boss_priority("妖魔统领"),
       "断言3：妖魔头领 == 妖魔统领 同级")
_check(_boss_priority("妖魔统领") == _boss_priority("知了王"),
       "断言3：妖魔统领 == 知了王 同级（P2）")
for i in range(len(chain) - 1):
    _check(_boss_priority(chain[i][0]) <= _boss_priority(chain[i + 1][0]),
           f"断言3：{chain[i][0]} 应 ≤ {chain[i+1][0]}")


# ---- 断言 4：only_top=True 只选顶级目标 ---------------------------------
# P3 灵猴很近 + P1 娄金狗略远 → 应选星宿且不选灵猴
live_top = [
    {"name": "下凡的灵猴", "gx": 2, "gy": 0},    # P3，极近但不是顶级
    {"name": "娄金狗", "gx": 15, "gy": 0},      # P1，略远但顶级
]
r4 = _mk(live_top, 0, 0, only_top=True)
_check(r4["name"] == "娄金狗", f"断言4：only_top 应选顶级娄金狗，实际 {_name(r4)}")


print("ALL STUB ASSERTIONS PASSED")