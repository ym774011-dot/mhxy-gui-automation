# -*- coding: utf-8 -*-
"""test_sell_junk.py — 一次性实测：zhuagui_sell_junk 全链路（只卖判据命中的垃圾）

前置：游戏开着、worker 心跳活着、背包已打开。
输出：卖前列表 → 逐件交互过程 → 卖后列表。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, ROOT)

import importlib.util  # noqa: E402

spec = importlib.util.spec_from_file_location("ZGUI", os.path.join(ROOT, "tasks", "library", "ZGUI.py"))
ZGUI = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ZGUI)

GW = "file://pzxy"


def dump_list(tag):
    items = ZGUI._sellable_items(GW)
    print("[%s] 可卖 %d 件: %s" % (tag, len(items),
                                  ["%s@格子%s(%d,%d)" % (n, g, x, y) for g, x, y, n in items]))
    return items


def main():
    hwnd = ZGUI.get_hwnd()
    if not hwnd:
        print("[X] 未找到游戏窗口")
        return 1
    print("[ok] hwnd=%d" % hwnd)
    if not ZGUI._bag_ensure_open(GW, hwnd):
        print("[X] 背包打不开")
        return 1
    print("[ok] 背包已确认打开")
    before = dump_list("卖前")
    if not before:
        print("[i] 背包里没有判据命中的可卖物品（需要 类型=武器/装备 或 上古锻造图策）")
        return 0
    n = ZGUI.zhuagui_sell_junk(GW, hwnd=hwnd, verbose=True)
    print("[结果] 卖出 %d 件" % n)
    after = dump_list("卖后")
    gone = [it for it in before if it not in after]
    print("[校验] 消失的格子: %s" % ["%s@格子%s" % (x[3], x[0]) for x in gone])
    print("[拿起状态] %s" % ZGUI._bag_pick_state(GW))
    return 0 if n > 0 or not before else 2


if __name__ == "__main__":
    sys.exit(main())
