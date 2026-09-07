# -*- coding: utf-8 -*-
"""member_sell_loop.py — 队员挂机循环：不接任务不打鬼，只定期出售背包垃圾装备。

适用形态（2026-09-06 用户定义）：5 开小队里后登录的 4 个号是队员，
在队伍里跟着队长即可，唯一需要自动化的就是清背包（抓鬼奖励的垃圾装备
很快塞满 20 格）。出售走背包自带"出售"绑定，任意地图可用，不依赖商店。

★2026-09-06 用户实测修正：背包面板一直开着 物品数据 不刷新（冻结）。
  循环改为：背包平时保持关闭；每 ~2 轮抓鬼（75s，可调）开包一次 →
  查可售列表（分类=武器/防具）→ 有则出售 → 查完关包。
  开包动作本身即强制重建物品数据，保证每次巡检看到的都是新背包。

用法（由 zhuagui_squad.py 自动拉起，也可手动）:
    E:/py/python.exe tools/member_sell_loop.py --pid 12345
        --gateway file://pzxy_p12345
"""
import argparse
import logging
import os
import random
import sys
import threading
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
    """按 PID 找该实例可点击的窗口句柄。找不到返回 0。

    ★2026-09-06 修复：多开器实例的带标题 Galaxy2DEngine 窗口是**子窗口**
    （顶层 WTWindow 属多开器进程且无标题），只枚举顶层会永远返回 0。
    与生产 get_hwnd（PowerShell MainWindowHandle=引擎子窗口）语义对齐：
    优先顶层带标题窗口，其次该进程的 Galaxy2DEngine 子窗口。
    """
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    top_hits = []
    engine_hits = []
    state = {"pid": pid}

    def classify(h):
        try:
            pidv = wintypes.DWORD()
            user32.GetWindowThreadProcessId(h, ctypes.byref(pidv))
            if pidv.value != state["pid"] or not user32.IsWindowVisible(h):
                return
            cls = ctypes.create_unicode_buffer(64)
            user32.GetClassNameW(h, cls, 64)
            n = user32.GetWindowTextLengthW(h)
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(h, buf, n + 1)
            if cls.value == "Galaxy2DEngine":
                engine_hits.append(h)
            if buf.value:
                top_hits.append(h)
        except Exception:
            pass

    ENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    def cb(h, _lp):
        classify(h)
        try:
            user32.EnumChildWindows(h, ENUMPROC(_child), 0)
        except Exception:
            pass
        return True

    def _child(h, _lp):
        classify(h)
        return True

    user32.EnumWindows(ENUMPROC(cb), 0)
    # ★引擎子窗口优先——游戏进程顶层还可能有 GGESUB 聊天窗口（历史坑：误中它点击全落聊天框）
    if engine_hits:
        return engine_hits[0]
    if top_hits:
        return top_hits[0]
    return 0


def _auto_battle_watchdog(pid, gw, log):
    """★2026-09-07 队员自动战斗看护线程（用户实测：只有队长会点「自动」，队员不会）。

    每 ~5s 用 Lua 状态判定（不依赖截屏，后台窗口可用）：
      战斗中 且「自动」按钮状态 ~= '取消'（未开启）→ 点击开启。
    与队长的 _battle_auto_kick（截屏模板）互不冲突：已开启时状态='取消'，
    两边都不会再点，杜绝"点两次=关掉自动"。
    """
    while True:
        try:
            hwnd = find_hwnd_by_pid(pid)
            if hwnd:
                ZGUI.zhuagui_ensure_auto_battle(hwnd, gw, log=log)
        except Exception as e:
            log.warning("自动战斗看护异常（忽略）: %s" % e)
        time.sleep(5.0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--gateway", default=None,
                    help="缺省 file://pzxy_p<pid>（与播种名一致）")
    ap.add_argument("--min-count", type=int, default=0,
                    help="(已废弃，保留兼容) 2026-09-06 起改为'有可售物品即卖'")
    ap.add_argument("--interval", type=float, default=75.0,
                    help="巡检间隔秒（默认 75≈2 轮抓鬼，带随机抖动）")
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

    log.info("队员出售循环启动 pid=%d gw=%s interval=%.0fs (有可售即卖,查完关包)"
             % (args.pid, gw, args.interval))
    # 开跑先钉一次目标窗口（member 自己的窗口），防 ZGUI 内部 get_hwnd 串号
    hwnd = find_hwnd_by_pid(args.pid)
    if hwnd:
        ZGUI.set_target_hwnd(hwnd)
    # ★2026-09-07 队员自动战斗看护（后台线程，5s 轮询，战斗中点开「自动」）
    threading.Thread(target=_auto_battle_watchdog,
                     args=(args.pid, gw, log), daemon=True).start()
    while True:
        try:
            hwnd = find_hwnd_by_pid(args.pid) or hwnd
            if not hwnd:
                time.sleep(10)
                continue
            ZGUI.set_target_hwnd(hwnd)
            # ★2026-09-06 重构（用户实测：背包一直开着 物品数据 不刷新，
            #   占用冻结在旧值、永远到不了阈值 → 永远不出售）：
            #   平时背包保持关闭；每轮巡检 开包(=强制重建物品数据) →
            #   查可售列表 → 有则卖 → finally 关包。
            if not ZGUI._bag_ensure_open(gw, hwnd):
                log.warning("背包打不开（窗口可能不在游戏界面），下轮重试")
                time.sleep(random.uniform(args.interval * 0.8, args.interval * 1.3))
                continue
            try:
                items = ZGUI._sellable_items(gw)
                log.info("巡检: 可售物品 %d 件" % len(items))
                if items:
                    log.info("开始出售...")
                    n = ZGUI.zhuagui_sell_junk(gw, hwnd=hwnd)
                    log.info("本次卖出 %d 件" % n)
            finally:
                ZGUI._bag_ensure_close(gw, hwnd)
        except Exception as e:
            log.warning("巡检异常（继续）: %s" % e)
        time.sleep(random.uniform(args.interval * 0.8, args.interval * 1.3))


if __name__ == "__main__":
    main()
