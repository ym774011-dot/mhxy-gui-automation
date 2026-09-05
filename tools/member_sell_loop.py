# -*- coding: utf-8 -*-
"""member_sell_loop.py — 队员挂机循环：不接任务不打鬼，只定期出售背包垃圾装备。

适用形态（2026-09-06 用户定义）：5 开小队里后登录的 4 个号是队员，
在队伍里跟着队长即可，唯一需要自动化的就是清背包（抓鬼奖励的垃圾装备
很快塞满 20 格）。出售走背包自带"出售"绑定，任意地图可用，不依赖商店。

用法（由 zhuagui_squad.py 自动拉起，也可手动）:
    E:/py/python.exe tools/member_sell_loop.py --pid 12345
        --gateway file://pzxy_p12345
"""
import argparse
import logging
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, ROOT)

import importlib.util  # noqa: E402

spec = importlib.util.spec_from_file_location(
    "ZGUI", os.path.join(ROOT, "tasks", "library", "ZGUI.py"))
ZGUI = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ZGUI)


def find_hwnd_by_pid(pid):
    """按 PID 找该实例的主窗口（带标题的可见顶层窗口）。找不到返回 0。"""
    try:
        import win32gui
        hits = []

        def cb(h, _):
            try:
                if win32gui.IsWindowVisible(h) and win32gui.GetWindowText(h):
                    if win32gui.GetWindowThreadProcessId(h)[1] == pid:
                        hits.append(h)
            except Exception:
                pass
            return True

        win32gui.EnumWindows(cb, None)
        return hits[0] if hits else 0
    except Exception:
        return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--gateway", default=None,
                    help="缺省 file://pzxy_p<pid>（与播种名一致）")
    ap.add_argument("--min-count", type=int, default=ZGUI._SELL_MIN_BAG_COUNT,
                    help="背包占用达到该格数才出售（默认 12）")
    ap.add_argument("--interval", type=float, default=90.0,
                    help="巡检间隔秒（默认 90，带随机抖动）")
    args = ap.parse_args()
    gw = args.gateway or ("file://pzxy_p%d" % args.pid)

    log_dir = os.path.join(ROOT, "test_data")
    if not os.path.isdir(log_dir):
        os.makedirs(log_dir)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[logging.FileHandler(
            os.path.join(log_dir, "member_p%d.log" % args.pid),
            encoding="utf-8")])
    log = logging.getLogger("member")

    log.info("队员出售循环启动 pid=%d gw=%s min_count=%d interval=%.0fs"
             % (args.pid, gw, args.min_count, args.interval))
    # 开跑先钉一次目标窗口（member 自己的窗口），防 ZGUI 内部 get_hwnd 串号
    hwnd = find_hwnd_by_pid(args.pid)
    if hwnd:
        ZGUI.set_target_hwnd(hwnd)
    while True:
        try:
            hwnd = find_hwnd_by_pid(args.pid) or hwnd
            if not hwnd:
                time.sleep(10)
                continue
            ZGUI.set_target_hwnd(hwnd)
            cnt = ZGUI._bag_used_count(gw)
            if cnt >= args.min_count:
                log.info("背包占用 %d 格 >= %d，开始出售..." % (cnt, args.min_count))
                n = ZGUI.zhuagui_sell_junk(gw, hwnd=hwnd)
                log.info("本次卖出 %d 件" % n)
        except Exception as e:
            log.warning("巡检异常（继续）: %s" % e)
        time.sleep(random.uniform(args.interval * 0.8, args.interval * 1.3))


if __name__ == "__main__":
    main()
