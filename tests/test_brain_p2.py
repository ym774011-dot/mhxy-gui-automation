# -*- coding: utf-8 -*-
"""P2 热点图/效率榜 加权选图测试（2026-09-01）。

验证：
  1) hot_map_rank 效率榜正确（样本门限 + 排序）；
  2) hot_weighted_pick：高频高效图权重更高，多轮抽样统计占优；
  3) 候选排除模型（recent/当前图）正常；
  4) 无数据图退化为均匀随机；异常输入不抛。
运行：E:\\py\\python.exe tests\\test_brain_p2.py
"""
import os
import sys
import tempfile
from collections import Counter

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


def test_rank():
    print("\n[P2-1] 效率榜排序 + 样本门限")
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    bm = BRAIN.BrainMemory(mem_file=path)
    for m, cost, n in (("长寿村", 8.0, 5), ("花果山", 13.0, 4), ("大唐国境", 6.5, 6)):
        for i in range(n):
            bm.hot_kill(m, cost)
    rank = bm.hot_map_rank(min_kills=4)
    check("三图都进榜（>=4样本）", len(rank) == 3)
    check("按耗时升序: 国境(6.5)<长寿(8)<花果(13)",
          [r["map"] for r in rank] == ["大唐国境", "长寿村", "花果山"])
    check("平均值正确", all(r["avg_cost"] == exp for r, exp in
                          zip(rank, [6.5, 8.0, 13.0])))
    # min_kills=6 → 只有国境 6 杀进榜
    rank2 = bm.hot_map_rank(min_kills=6)
    check("min_kills=6 只有国境", [r["map"] for r in rank2] == ["大唐国境"])
    os.unlink(path)


def test_weighted_pick():
    print("\n[P2-2] 加权选图占优（多轮统计）")
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    bm = BRAIN.BrainMemory(mem_file=path)
    # 优质图：长寿村 均耗 6s；普通图：长安城 均耗 18s
    for i in range(5):
        bm.hot_kill("长寿村", 6.0)
    for i in range(5):
        bm.hot_kill("长安城", 18.0)
    candidates = ["长寿村", "长安城"]
    cnt = Counter(bm.hot_weighted_pick(candidates, pool_avg=15.0) for _ in range(200))
    check("两图都会被选到", len(cnt) == 2)
    good = cnt.get("长寿村", 0)
    check(f"长寿村明显占优 ({good}/200 > 120)", good > 120)
    # 排除图不在候选里 → 绝不会返回
    out = [bm.hot_weighted_pick(["长安城"], pool_avg=15.0) for _ in range(20)]
    check("候选只有长安城 → 只返回长安城", set(out) == {"长安城"})
    os.unlink(path)


def test_no_data_fallback():
    print("\n[P2-3] 无数据图退化为均匀（原始 _pick_random_map 行为兼容）")
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    bm = BRAIN.BrainMemory(mem_file=path)
    cands = ["图A", "图B", "图C"]
    cnt = Counter(bm.hot_weighted_pick(cands, pool_avg=12.0) for _ in range(300))
    check("无数据 → 三图都会被选（均匀）", len(cnt) == 3)
    worst = max(cnt.values())
    best = min(cnt.values())
    # 均匀性粗检：占比最悬殊不超过 60/40（不严格，仅防公式崩坏）
    check(f"均匀性尚可 (max={worst}/300, min={best}/300)", worst < 180 and best > 80)
    # 兼容：原 _pick_random_map 也是随机
    for _ in range(10):
        assert W._pick_random_map("图A", cands, ()) in cands
    check("_pick_random_map 返回候选内", True)
    os.unlink(path)


def test_weighted_pick_robust():
    print("\n[P2-4] 加权选图容错")
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    bm = BRAIN.BrainMemory(mem_file=path)
    check("空候选 → 空串", bm.hot_weighted_pick([]) == "")
    # 单 v 候选
    check("单候选 → 该候选", bm.hot_weighted_pick(["图A"]) == "图A")
    # 候选含 None/non-str
    check("含异常候选不抛", isinstance(bm.hot_weighted_pick(["图A", 1, None], pool_avg=5), str))
    os.unlink(path)


if __name__ == "__main__":
    test_rank()
    test_weighted_pick()
    test_no_data_fallback()
    test_weighted_pick_robust()
    print(f"\n=== P2 测试完成: 通过 {_PASS} / 失败 {_FAIL} ===")
    sys.exit(1 if _FAIL else 0)