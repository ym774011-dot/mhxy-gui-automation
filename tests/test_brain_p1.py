# -*- coding: utf-8 -*-
"""P1 坑位黑名单接入 WORLD_BOSS 的集成测试（2026-09-01）。

验证：
  1) _filter_blacklisted 正确剔除拉黑坐标、放行未拉黑坐标、异常时放行；
  2) 黑名单"观察→拉黑→成功抵消→撤黑"闭环（BRAIN + 过滤联动）；
  3) 埋点调用不抛异常（无游戏进程也能跑——全程 mock）。
运行：E:\\py\\python.exe tests\\test_brain_p1.py
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


def mk_boss(name, gx, gy):
    return {"id": f"{name}{gx}{gy}", "name": name, "gx": gx, "gy": gy,
            "model": "", "src": "scan", "boss_pattern": name, "bsid": ""}


def test_filter_basic():
    print("\n[P1-1] _filter_blacklisted 过滤逻辑")
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    bm = BRAIN.BrainMemory(mem_file=path)
    live = [mk_boss("冥府头领", 15, 138), mk_boss("避世头领", 60, 60),
            mk_boss("知了王", 100, 100)]
    # 未拉黑 → 全放行
    out = W._filter_blacklisted(live, bm, "长寿村")
    check("初始全放行 (3/3)", len(out) == 3)
    # 15,138 失败 3 次 → 拉黑
    for i in range(3):
        bm.black_add("长寿村", 15, 138, "no_battle_option")
    out = W._filter_blacklisted(live, bm, "长寿村")
    names = [x["name"] for x in out]
    check("拉黑坐标被剔除 (2/3)", len(out) == 2 and "冥府头领" not in names)
    check("其余坐标保留", "避世头领" in names and "知了王" in names)
    # 另一地图同名坐标不受影响
    out2 = W._filter_blacklisted(live, bm, "傲来国")
    check("他图同名坐标放行", len(out2) == 3)
    os.unlink(path)


def test_filter_quiet_and_robust():
    print("\n[P1-2] 过滤静默与容错")
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    bm = BRAIN.BrainMemory(mem_file=path)
    live = [mk_boss("x", 1, 1), mk_boss("y", 2, 2)]
    # brain=None → 原样返回
    check("brain=None 放行", W._filter_blacklisted(live, None, "图") == live)
    # live 为空 → 空
    check("live 空 → 空", W._filter_blacklisted([], bm, "图") == [])
    # 拉黑后同名坐标（不同图）仍放行
    bm.black_add("图A", 1, 1)
    bm.black_add("图A", 1, 1)
    bm.black_add("图A", 1, 1)
    check("图A 拉黑", len(W._filter_blacklisted(live, bm, "图A", verbose=False)) == 1)
    check("图B 全放行", len(W._filter_blacklisted(live, bm, "图B")) == 2)
    os.unlink(path)


def test_black_closed_loop():
    print("\n[P1-3] 观察→拉黑→击杀抵消→撤黑 闭环")
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    bm = BRAIN.BrainMemory(mem_file=path)
    pos = (300, 85)
    # 失败 1 次（未拉黑，还能试）→ 过滤后应保留（放行）
    bm.black_add("大唐国境", *pos, "no_battle_option")
    check("失败1次未拉黑→放行", len(W._filter_blacklisted([mk_boss("b", *pos)], bm, "大唐国境")) == 1)
    # 连续失败到 3 次 → 拉黑（过滤后为空 = 不放行）
    bm.black_add("大唐国境", *pos, "no_battle_option")
    bm.black_add("大唐国境", *pos, "no_battle_option")
    check("失败3次拉黑→剔除", len(W._filter_blacklisted([mk_boss("b", *pos)], bm, "大唐国境")) == 0)
    # 之后成功 1 次 → fail 3-2=1 → 撤黑放行
    bm.black_success("大唐国境", *pos)
    check("成功1次撤黑", bool(W._filter_blacklisted([mk_boss("b", *pos)], bm, "大唐国境")))
    # 失败到阈值后，持续成功会彻底清空
    bm.black_add("大唐国境", *pos, "no_battle_option")
    bm.black_add("大唐国境", *pos, "no_battle_option")
    bm.black_add("大唐国境", *pos, "no_battle_option")
    bm.black_success("大唐国境", *pos)
    bm.black_success("大唐国境", *pos)
    check("连续成功彻底撤黑（fail 归零清除）",
          bool(W._filter_blacklisted([mk_boss("b", *pos)], bm, "大唐国境")))
    os.unlink(path)


def test_hot_recording():
    print("\n[P1-4] 热点/耗时埋点数据正确（P2 顺带验证）")
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    bm = BRAIN.BrainMemory(mem_file=path)
    bm.hot_kill("长寿村", 10.0, cross=True)
    bm.hot_kill("长寿村", 12.0, cross=False)
    bm.hot_kill("长寿村", 8.0, cross=False)
    rank = bm.hot_map_rank(min_kills=3)
    check("热点3杀进榜", rank and rank[0]["kills"] == 3)
    check("平均耗时10.0", rank and rank[0]["avg_cost"] == 10.0)
    check("跨图计数1", rank and rank[0]["cross_ct"] == 1)
    bm.done()
    raw = open(path, encoding="utf-8").read()
    check("落盘 JSON 含 hot", '"hot"' in raw)
    os.unlink(path)


if __name__ == "__main__":
    test_filter_basic()
    test_filter_quiet_and_robust()
    test_black_closed_loop()
    test_hot_recording()
    print(f"\n=== P1 测试完成: 通过 {_PASS} / 失败 {_FAIL} ===")
    sys.exit(1 if _FAIL else 0)