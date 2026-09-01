# -*- coding: utf-8 -*-
"""BRAIN.py P0 骨架单元测试（2026-09-01）。

覆盖：加载/保存/原子写、置信度衰减、坑位黑名单进出规则、
热点图统计、参数自适应、断点恢复 — 全部不碰游戏，纯逻辑验证。
运行：E:\\py\\python.exe tests\\test_brain_p0.py
"""
import os
import sys
import json
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from tasks.library import BRAIN  # noqa: E402

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


def fresh_brain():
    """临时文件承载的独立 BrainMemory（不污染真 data/）。"""
    fd, path = tempfile.mkstemp(suffix=".json", prefix="brain_p0_")
    os.close(fd)
    b = BRAIN.BrainMemory(mem_file=path)
    return b, path


def test_base_save_load():
    print("\n[P0-1] 保存/加载/原子写")
    b, path = fresh_brain()
    b.black_add("长寿村", 15, 138, reason="首次失败")
    b.done(force=True)
    check("写盘文件存在", os.path.exists(path))
    raw = open(path, encoding="utf-8").read()
    check("JSON 可解析", bool(json.loads(raw)))
    check("无 .tmp 残留（原子替换）", not os.path.exists(path + ".tmp"))
    b2 = BRAIN.BrainMemory(mem_file=path)
    d = b2.dump()
    check("重载后数据一致", d["black"].get("长寿村", {}).get("15,138", {}).get("fail") == 1)
    os.unlink(path)


def test_blacklist_threshold():
    print("\n[P0-2] 坑位黑名单阈值（fail>=3 拉黑，含 success 抵消）")
    b, path = fresh_brain()
    check("初始未拉黑", not b.black_blacklisted("长寿村", 15, 138))
    b.black_add("长寿村", 15, 138, "a")
    b.black_add("长寿村", 15, 138, "b")
    check("2 次仍未拉黑（阈值3）", not b.black_blacklisted("长寿村", 15, 138))
    b.black_add("长寿村", 15, 138, "c")
    check("3 次已拉黑", b.black_blacklisted("长寿村", 15, 138))
    # 成功后抵消：fail3 - success2次offset => fail 降至 1 → 撤黑
    b.black_success("长寿村", 15, 138)
    check("失败3次+成功1次后 fail 降到 1 → 未拉黑",
          not b.black_blacklisted("长寿村", 15, 138))
    # 另一坐标互不影响
    check("另一坐标不拉黑", not b.black_blacklisted("长寿村", 16, 138))
    b.done(force=True)
    os.unlink(path)


def test_decay():
    print("\n[P0-3] 置信度衰减（超 TTL 后 fail 衰减，成熟经验自动化）")
    b, path = fresh_brain()
    old = time.time() - (BRAIN._DEFAULT_TTL + 100)
    b.black_add("傲来国", 1, 2, reason="老坑", now=old)
    # 直接构造一个 fail=3 的过期条目（多次调用会累加，先手动置老化基数）
    m = b.dump()["black"]
    e = m["傲来国"]["1,2"]
    e["fail"] = 10   # 模拟累计到 10 次
    e["ts"] = old
    b._decay(e, now=time.time())
    check("过期后 fail 衰减 (10→5)", e["fail"] == 5)
    # 衰减到 <阈值 则不再拉黑
    e["fail"] = 2
    check("fail<3 后不再拉黑", not b.black_blacklisted("傲来国", 1, 2))
    os.unlink(path)


def test_hot_rank():
    print("\n[P0-4] 热点图效率榜（平均耗时升序 + 样本门限）")
    b, path = fresh_brain()
    # 长寿村：3 杀，均耗 10s
    for i in range(3):
        b.hot_kill("长寿村", 10, cross=(i == 0))
    # 傲来国：2 杀（不足 min_kills=3 不进榜），均耗 6s
    for i in range(2):
        b.hot_kill("傲来国", 6)
    rank = b.hot_map_rank(min_kills=3)
    check("仅长寿村进榜（样本门限）", [r["map"] for r in rank] == ["长寿村"])
    check("平均耗时正确 10.0", rank and rank[0]["avg_cost"] == 10.0)
    check("跨图计数=1", rank and rank[0]["cross_ct"] == 1)
    # 再补满傲来国 5 杀均耗 6 → 应排到长寿村前面
    for i in range(3):
        b.hot_kill("傲来国", 6)
    rank2 = b.hot_map_rank(min_kills=3)
    check("敖来国(6s)排在长寿村(10s)前", [r["map"] for r in rank2] == ["傲来国", "长寿村"])
    os.unlink(path)


def test_param_adapt():
    print("\n[P0-5] 参数自适应观测/均值/最优")
    b, path = fresh_brain()
    check("空参数返回 None", b.param_current("call_skip_dist")[0] is None)
    b.param_observe("call_skip_dist", 15.0, metric=11.0)   # 取值15 绩效11
    b.param_observe("call_skip_dist", 13.0, metric=9.5)    # 取值13 绩效9.5（更优）
    b.param_observe("call_skip_dist", 13.0, metric=12.0)
    avg, n = b.param_current("call_skip_dist")
    check("均值=13.67", abs(avg - (15 + 13 + 13) / 3.0) < 1e-6)
    check("样本 n=3", n == 3)
    check("最优取值为 13（绩效9.5那次）", b.param_best("call_skip_dist") == 13.0)
    os.unlink(path)


def test_session():
    print("\n[P0-6] 会话断点恢复/重置")
    b, path = fresh_brain()
    b.session_begin("长寿村", 15, 138, kills=42, reason="start")
    b.done(force=True)
    b2 = BRAIN.BrainMemory(mem_file=path)
    s = b2.session_resume()
    check("断点地图正确", s.get("cur_map") == "长寿村")
    check("断点击杀数正确", s.get("kills") == 42)
    check("断点坐标正确", s.get("cur_x") == 15 and s.get("cur_y") == 138)
    b2.session_reset()
    b2.done(force=True)
    b3 = BRAIN.BrainMemory(mem_file=path)
    check("重置后断点为空", b3.session_resume() == {})
    os.unlink(path)


def test_stats():
    print("\n[P0-7] 状态汇报")
    b, path = fresh_brain()
    b.black_add("长寿村", 1, 1, "x")
    b.hot_kill("长安", 5)
    b.param_observe("k", 1)
    st = b.stats()
    check("stats 含各字段", st.get("black_entries") == 1 and st.get("hot_maps") == 1
          and st.get("param_keys") == 1)
    os.unlink(path)


def test_robustness():
    print("\n[P0-8] 容错（坏文件不崩 farm）")
    fd, path = tempfile.mkstemp(suffix=".json", prefix="brain_p0_bad_")
    os.write(fd, b"{this is not valid json!!!")   # 坏 JSON
    os.close(fd)
    b = BRAIN.BrainMemory(mem_file=path)          # 应优雅回退空 dict
    d = b.dump()
    # 分区骨架在、但无任何经验数据
    check("坏文件加载不抛异常",
          set(d.keys()) == {"black", "hot", "param", "session"}
          and all(v == {} for v in d.values()))
    b.black_add("测试图", 9, 9, "still works")    # 写入仍正常
    check("坏文件下仍能记录", b.black_blacklisted("测试图", 9, 9) is False
          and "测试图" in b.dump().get("black", {}))
    os.unlink(path)


if __name__ == "__main__":
    test_base_save_load()
    test_blacklist_threshold()
    test_decay()
    test_hot_rank()
    test_param_adapt()
    test_session()
    test_stats()
    test_robustness()
    print(f"\n=== P0 测试完成: 通过 {_PASS} / 失败 {_FAIL} ===")
    sys.exit(1 if _FAIL else 0)