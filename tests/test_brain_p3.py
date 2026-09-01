# -*- coding: utf-8 -*-
"""P3 参数自适应测试（2026-09-01）。

验证：观测/均值/最优绩效、软适应建议钳制、异常容错。
运行：E:\\py\\python.exe tests\\test_brain_p3.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from tasks.library import BRAIN  # noqa: E402
import tasks.library.WORLD_BOSS as W  # noqa: E402

_PASS = 0
_FAIL = 0


def check(name, cond):
    global _PASS, _FAIL
    if cond:
        _PASS += 1
        print(f"  ✔ {name}")
    else:
        _FAIL += 1
        print(f"  ✘ {name}")


def test_observe_agree():
    print("\n[P3-1] 观测/均值/最优绩效")
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    bm = BRAIN.BrainMemory(mem_file=path)
    bm.param_observe("gap_between_battles", 12.0, metric=12.0)
    bm.param_observe("gap_between_battles", 8.5, metric=8.5)
    bm.param_observe("gap_between_battles", 10.0, metric=10.0)
    avg, n = bm.param_current("gap_between_battles")
    check("均值=10.17", abs(avg - (12 + 8.5 + 10) / 3.0) < 1e-6)
    check("n=3", n == 3)
    check("最优=8.5（绩效最小那次）", bm.param_best("gap_between_battles") == 8.5)
    os.unlink(path)


def test_suggest_clamp():
    print("\n[P3-2] 软适应建议 + 范围钳制（防学歪）")
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    bm = BRAIN.BrainMemory(mem_file=path)
    # 无数据 → 返回 default
    check("无数据返回默认", bm.param_suggest("gap_between_battles", 10.0) == 10.0)
    # 观测到最优 8.5 → 建议 8.5
    bm.param_observe("gap_between_battles", 8.5, metric=8.5)
    check("有数据返回最优", bm.param_suggest("gap_between_battles", 10.0) == 8.5)
    # 下限钳制：观测最优变为 3.0（绩效3最小）→ min 钳到 5
    bm.param_observe("gap_between_battles", 3.0, metric=3.0)
    check("下限钳制 5", bm.param_suggest("gap_between_battles", 10.0, min_val=5.0) == 5.0)
    # 上限钳制：独立 key，观测最优=30（绩效30也最小，会被选为best）→ max 钳到 15
    bm2 = BRAIN.BrainMemory(mem_file=path + ".2")
    bm2.param_observe("teleport_dist", 30.0, metric=1.0)
    bm2.param_observe("teleport_dist", 30.0, metric=1.0)
    check("上限钳制(最优30→15)", bm2.param_suggest("teleport_dist", 10.0, max_val=15.0) == 15.0)
    bm2.done(force=True)
    os.unlink(path + ".2")
    os.unlink(path)


def test_robustness():
    print("\n[P3-3] 容错")
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    bm = BRAIN.BrainMemory(mem_file=path)
    check("无 key 返回 None", bm.param_best("nope") is None)
    check("无 key suggest 返回默认", bm.param_suggest("nope", 5.0) == 5.0)
    # 坏值不抛
    bm.param_observe("x", "not-number", metric="bad")
    check("坏值观测不抛", bm.param_current("x")[1] in (0, 1))
    os.unlink(path)


if __name__ == "__main__":
    test_observe_agree()
    test_suggest_clamp()
    test_robustness()
    print(f"\n=== P3 测试完成: 通过 {_PASS} / 失败 {_FAIL} ===")
    sys.exit(1 if _FAIL else 0)