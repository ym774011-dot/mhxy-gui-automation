# -*- coding: utf-8 -*-
"""抓鬼实测 jsonl 汇总统计（可观测性配套，2026-09-03）。

从 run_unlimited_test.py 产出的 test_data/*.jsonl 汇总：
  * 总轮数、各 result 计数与占比、OK 率（含 Wilson 95% 置信区间）
  * fail_stage 失败环节分布
  * 耗时：平均 / 中位 / p90 / 最大
  * 按 (timeout, wait_dialog) 分组的 A/B 对比表
  * 战斗态事实汇总（待办 #4：真战斗中「参战单位」是否非空）
  * 任务栏刷新延迟（待办 #3：first_change_offset_s 分布 vs timeout）

用法::

    python tools/zhuagui_stats.py test_data/zhuagui_20260903_190000.jsonl
    python tools/zhuagui_stats.py test_data/*.jsonl            # 合并统计
    python tools/zhuagui_stats.py test_data/*_A_*.jsonl test_data/*_B_*.jsonl
    python tools/zhuagui_stats.py test_data/*.jsonl --by-config   # A/B 分组
    python tools/zhuagui_stats.py test_data/*.jsonl --json        # 机器可读
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import os
import sys
from collections import Counter, defaultdict

RESULTS = ("ok", "inbattle", "other", "error")


# ============================================================
# 读取
# ============================================================
def expand(patterns):
    paths = []
    for p in patterns:
        if os.path.isdir(p):
            paths.extend(sorted(glob.glob(os.path.join(p, "*.jsonl"))))
        elif any(ch in p for ch in "*?["):
            paths.extend(sorted(glob.glob(p)))
        else:
            paths.append(p)
    seen, out = set(), []
    for p in paths:
        ap = os.path.abspath(p)
        if ap not in seen and os.path.exists(ap):
            seen.add(ap)
            out.append(ap)
    return out


def load(paths):
    recs, bad = [], []
    for p in paths:
        with open(p, encoding="utf-8") as f:
            for i, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except json.JSONDecodeError as e:
                    bad.append("%s:%d %s" % (p, i, e))
                    continue
                r["_src"] = os.path.basename(p)
                recs.append(r)
    return recs, bad


# ============================================================
# 统计基元
# ============================================================
def pct(n, d):
    return (n / d * 100.0) if d else 0.0


def wilson_ci(k, n, z=1.96):
    """Wilson  score 95% 置信区间（小样本也稳，适合抓鬼这种 20~50 轮的 A/B）。"""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = (z / den) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (max(0.0, centre - half) * 100.0, min(1.0, centre + half) * 100.0)


def stats_numbers(vals):
    vals = sorted(v for v in vals if isinstance(v, (int, float)))
    if not vals:
        return {"n": 0, "avg": 0.0, "median": 0.0, "p90": 0.0, "min": 0.0, "max": 0.0}
    n = len(vals)

    def q(qv):
        idx = min(n - 1, max(0, int(round(qv * (n - 1)))))
        return float(vals[idx])

    return {"n": n, "avg": round(sum(vals) / n, 2), "median": round(q(0.5), 2),
            "p90": round(q(0.9), 2), "min": round(float(vals[0]), 2),
            "max": round(float(vals[-1]), 2)}


def summarize(recs, title="总体"):
    n = len(recs)
    cnt = Counter(r.get("result") for r in recs)
    ok = cnt.get("ok", 0)
    lo, hi = wilson_ci(ok, n)
    elapsed = stats_numbers([r.get("elapsed_s") for r in recs])
    ok_elapsed = stats_numbers([r.get("elapsed_s") for r in recs if r.get("result") == "ok"])
    stages = Counter(r.get("fail_stage", "未知") for r in recs if r.get("result") != "ok")

    # #3 尺子：任务栏首次变化延迟
    lags = [r["task"]["first_change_offset_s"] for r in recs
            if isinstance((r.get("task") or {}).get("first_change_offset_s"), (int, float))]
    lag = stats_numbers(lags)
    ok_missing_lag = sum(1 for r in recs
                         if r.get("result") == "ok"
                         and (r.get("task") or {}).get("first_change_offset_s") is None)
    # #4 尺子：战斗态与参战单位
    bt = [r.get("battle") or {} for r in recs]
    rounds_with_battle = sum(1 for b in bt if b.get("observed"))
    battle_samples = sum(b.get("samples") or 0 for b in bt)
    cz_nonempty_in_battle = sum(b.get("canzhan_nonempty_samples") or 0 for b in bt)
    cz_max_in_battle = max([b.get("canzhan_max_pairs") or 0 for b in bt] or [0])
    cz_ever = sum(1 for b in bt if b.get("canzhan_ever_nonempty"))
    enemy_max = max([b.get("enemy_max") or 0 for b in bt] or [0])
    inbattle_no_count_change = sum(
        1 for r in recs
        if r.get("result") == "inbattle" and not (r.get("task") or {}).get("changed"))

    return {
        "title": title, "rounds": n, "counts": dict(cnt),
        "ok_rate": round(pct(ok, n), 2), "ok_ci95": [round(lo, 2), round(hi, 2)],
        "elapsed": elapsed, "elapsed_ok": ok_elapsed,
        "stages": dict(stages),
        "lag": lag, "ok_missing_lag": ok_missing_lag,
        "battle": {"rounds_with_battle": rounds_with_battle,
                   "battle_samples": battle_samples,
                   "canzhan_nonempty_samples_in_battle": cz_nonempty_in_battle,
                   "canzhan_max_pairs_in_battle": cz_max_in_battle,
                   "rounds_canzhan_ever_nonempty": cz_ever,
                   "enemy_max": enemy_max},
        "inbattle_no_count_change": inbattle_no_count_change,
    }


# ============================================================
# 渲染
# ============================================================
def _bar(v, total, width=28):
    filled = int(round(width * v / total)) if total else 0
    return "#" * filled + "." * (width - filled)


def render(s, out=sys.stdout):
    w = out.write
    n = s["rounds"]
    w("=" * 72 + "\n")
    w("抓鬼实测统计  [%s]\n" % s["title"])
    w("=" * 72 + "\n")
    if n == 0:
        w("（无记录）\n")
        return
    w("总轮数: %d\n\n" % n)

    w("── 结果分布 ─────────────────────────────────────────────\n")
    for k in RESULTS:
        c = s["counts"].get(k, 0)
        w("  %-9s %4d  %5.1f%%  %s\n" % (k, c, pct(c, n), _bar(c, n)))
    w("  %-9s %4d  %5.1f%%  (95%%CI %.1f%% ~ %.1f%%)\n"
      % ("OK率", s["counts"].get("ok", 0), s["ok_rate"],
         s["ok_ci95"][0], s["ok_ci95"][1]))
    w("\n")

    w("── 失败环节分布（result != ok）─────────────────────────\n")
    stages = s["stages"]
    tot_fail = sum(stages.values())
    if not stages:
        w("  （无失败轮）\n")
    for k, c in sorted(stages.items(), key=lambda kv: -kv[1]):
        w("  %-10s %4d  %5.1f%%  %s\n" % (k, c, pct(c, tot_fail), _bar(c, tot_fail)))
    w("\n")

    e, eo = s["elapsed"], s["elapsed_ok"]
    w("── 单轮耗时（秒）───────────────────────────────────────\n")
    w("  全部   n=%-4d 平均 %-7s 中位 %-7s p90 %-7s 最大 %s\n"
      % (e["n"], e["avg"], e["median"], e["p90"], e["max"]))
    w("  仅OK  n=%-4d 平均 %-7s 中位 %-7s p90 %-7s 最大 %s\n"
      % (eo["n"], eo["avg"], eo["median"], eo["p90"], eo["max"]))
    w("\n")

    lag = s["lag"]
    w("── ★待办#3 任务栏刷新延迟（first_change_offset_s，秒）──\n")
    w("  样本 %d / %d 轮（OK 轮中未采到变化: %d）\n"
      % (lag["n"], n, s["ok_missing_lag"]))
    if lag["n"]:
        w("  平均 %-7s 中位 %-7s p90 %-7s 最大 %s\n"
          % (lag["avg"], lag["median"], lag["p90"], lag["max"]))
        w("  判读：若 p90 已接近或超过当轮 timeout，则 #3「超时误判」成立。\n")
    w("  inbattle 轮中任务次数最终也未变化: %d（这些是真失败，非刷新滞后）\n"
      % s["inbattle_no_count_change"])
    w("\n")

    b = s["battle"]
    w("── ★待办#4 战斗态 / 参战单位实测 ────────────────────────\n")
    w("  观测到 战斗中=true 的轮数: %d / %d\n" % (b["rounds_with_battle"], n))
    w("  战斗中采样点总数:         %d\n" % b["battle_samples"])
    w("  其中 参战单位pairs>0:     %d\n" % b["canzhan_nonempty_samples_in_battle"])
    w("  战斗中 参战单位 pairs 峰值: %d\n" % b["canzhan_max_pairs_in_battle"])
    w("  整轮中出现过非空参战单位的轮数: %d\n" % b["rounds_canzhan_ever_nonempty"])
    w("  敌方数量峰值:             %d\n" % b["enemy_max"])
    w("  判读：若「战斗中采样点>0」但「参战单位pairs>0 = 0」，\n"
      "        则 #4 命题成立——真战斗中参战单位仍为空，该判据不可用。\n")
    w("=" * 72 + "\n")


def render_ab(groups, out=sys.stdout):
    w = out.write
    w("\n" + "=" * 72 + "\n")
    w("A/B 分组对比（按 timeout / wait_dialog）\n")
    w("=" * 72 + "\n")
    w("  %-28s %6s %6s %8s %-16s %8s %8s\n"
      % ("配置", "轮数", "OK", "OK率", "95%CI", "中位耗时", "刷新p90"))
    w("  " + "-" * 82 + "\n")
    for key, s in sorted(groups.items()):
        w("  %-28s %6d %6d %7.1f%% %-16s %8s %8s\n"
          % (key, s["rounds"], s["counts"].get("ok", 0), s["ok_rate"],
             "%.1f~%.1f%%" % (s["ok_ci95"][0], s["ok_ci95"][1]),
             s["elapsed"]["median"], s["lag"]["p90"] if s["lag"]["n"] else "-"))
    w("  " + "-" * 82 + "\n")
    w("  注：样本量小时 CI 会重叠，需继续加跑直到 CI 分离。\n")
    w("=" * 72 + "\n")


def group_by_config(recs):
    g = defaultdict(list)
    for r in recs:
        g["timeout=%s wait_dialog=%s" % (r.get("timeout"), r.get("wait_dialog"))].append(r)
    return {k: summarize(v, title=k) for k, v in g.items()}


# ============================================================
def main(argv=None):
    ap = argparse.ArgumentParser(description="抓鬼实测 jsonl 统计")
    ap.add_argument("paths", nargs="+", help="jsonl 文件 / 目录 / 通配符")
    ap.add_argument("--by-config", action="store_true",
                    help="额外按 (timeout, wait_dialog) 输出 A/B 分组对比")
    ap.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    args = ap.parse_args(argv)

    paths = expand(args.paths)
    if not paths:
        print("未匹配到任何 jsonl：%s" % " ".join(args.paths), file=sys.stderr)
        return 2

    recs, bad = load(paths)
    if bad:
        print("[warn] %d 行解析失败：" % len(bad), file=sys.stderr)
        for b in bad[:10]:
            print("       " + b, file=sys.stderr)

    s = summarize(recs)
    if args.json:
        print(json.dumps({"files": [os.path.basename(p) for p in paths],
                          "summary": s,
                          "by_config": group_by_config(recs) if args.by_config else None},
                         ensure_ascii=False, indent=2))
        return 0

    print("数据源: %s" % ", ".join(os.path.basename(p) for p in paths))
    render(s)
    if args.by_config:
        render_ab(group_by_config(recs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
