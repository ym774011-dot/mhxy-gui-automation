# -*- coding: utf-8 -*-
"""diag_squad.py — 诊断 5 开小队当前状态：state 文件 + 全部 worker 心跳 + 队员日志。只读。"""
import glob
import json
import os
import sys
import time

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT)
from library.pzxy_ipc import PzxyWorker  # noqa: E402


def main():
    p = os.path.join(ROOT, "test_data", "squad_state.json")
    print("=== squad_state.json ===")
    if os.path.exists(p):
        print(open(p, encoding="utf-8").read())
    else:
        print("(不存在 —— 编排器没走到分配阶段，或窗口当时未登录)")

    print("=== worker 心跳 ===")
    now = time.time()
    for hb in sorted(glob.glob(r"E:\DS\tmp\pzxy_*_hb.txt")):
        base = os.path.basename(hb)
        name = base[len("pzxy_"):-len("_hb.txt")]
        w = PzxyWorker(name=name)
        fr, ts = w.heartbeat()
        age = (now - ts) if ts else -1
        print("  %-12s frame=%-9s age=%6.0fs alive=%s" % (name or "(默认)", fr, age, w.is_alive()))

    print("=== 队员日志（test_data/member_p*.log 尾部） ===")
    for lp in sorted(glob.glob(os.path.join(ROOT, "test_data", "member_p*.log"))):
        print("-- " + os.path.basename(lp))
        try:
            lines = open(lp, encoding="utf-8", errors="replace").read().splitlines()
            for line in lines[-5:]:
                print("   " + line)
        except OSError as e:
            print("   读取失败:", e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
