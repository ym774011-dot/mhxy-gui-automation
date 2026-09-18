# -*- coding: utf-8 -*-
"""副本（独立方案 2026-09-16；PP GUI 方案"打副本"队长脚本）。

流程：
  快捷传送对话框（界面数据[8]）→ 点「快捷副本」(271,22,323,33)
  → 点「开始XX副本」（红字自动识别）→ 点「进入XX副本」（标定矩形）
  → 识别进入战斗 → 自动战斗 → 战斗中不 CALL。
★用户定案：只有乌鸡副本做了数据，其他副本一律不开启（FU_BEN.run() 默认只跑乌鸡）。

业务主链路由 tasks/library/FU_BEN.run() 完整承担。
队内成员沿用 member_sell_loop.py（纯出售/保活），跟随队长进副本。

用法：
  E:/py/python.exe run_fuben.py --role 二号美人
  （★2026-09-17：gateway 由角色名自动解析为 file:///pzxy_p<活PID>，无需手填）
"""
import argparse
import logging
import os
import random
import signal
import sys
import threading
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from tasks.library import ZGUI                      # noqa: E402
from tasks.library import FU_BEN                    # noqa: E402

_LOG = logging.getLogger("mhxy")

_STOP = threading.Event()


def _install_signal():
    def _h(signum, frame):
        global _STOP
        if _STOP.is_set():
            signal.signal(signal.SIGINT, signal.SIG_DFL)
            return
        _STOP.set()
        sys.stdout.write("\n[stop] 完成当前轮副本后优雅退出（再按 Ctrl+C 强制）\n")
        sys.stdout.flush()
    signal.signal(signal.SIGINT, _h)


def _wait_out_battle(gw, max_s=120.0):
    """等当前战斗结束（脚本被拉起时可能正在战斗）。"""
    t0 = time.time()
    while time.time() - t0 < max_s:
        try:
            if not ZGUI.zhuagui_in_battle(gw):
                return True
        except Exception:
            return True
        time.sleep(3.0)
    return False


def main(argv=None):
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="副本（PP GUI 方案：打副本）")
    ap.add_argument("--gateway", default="file://pzxy", help="网关/播种通道")
    ap.add_argument("--role", default="二号美人", help="角色名（多开钉窗）")
    ap.add_argument("--rounds", type=int, default=1,
                    help="跑几轮（一轮=一次 FU_BEN.run，内部最多 6 次副本；0=无限）")
    ap.add_argument("--min-interval", type=float, default=8.0)
    ap.add_argument("--max-interval", type=float, default=20.0)
    # ★与 run_chuangguan.py 同款：PP GUI 通传给队长脚本 --timeout/--wait-dialog，
    #   本脚本不使用，接受并忽略（防 argparse 报错退出）。
    ap.add_argument("--timeout", type=float, default=None, help="兼容 PP GUI 通用传参（本脚本不使用）")
    ap.add_argument("--wait-dialog", type=float, default=None, help="兼容 PP GUI 通用传参（本脚本不使用）")
    # ★2026-09-18：同上——PP GUI 看门狗补拉 / 补组重拉会带 --skip-team，必须接受，
    #   否则 argparse 报错退出 → 被判"脚本已死"→ 反复重拉，副本任务跑不起来。
    ap.add_argument("--skip-team", action="store_true",
                    help="兼容 PP GUI 跳过组队路径的拉起（本脚本不使用）")
    args = ap.parse_args(argv)
    random.seed()

    # ★2026-09-17：先按角色名解析活窗口 PID，用该实例专属 file 通道。
    #   历史事故：写死 file://pzxy_p9864（PID 9864 已死）→ 读地图恒空 →
    #   「一直点开启就是不进去」死循环。现改为自动发现，杜绝死通道。
    pw = None
    try:
        pw = ZGUI._find_role_window(args.role)
    except Exception:
        pw = None
    if pw:
        gw = "file://pzxy_p%d" % pw[0]
        try:
            ZGUI.set_target_hwnd(pw[1])
        except Exception:
            pass
        print("活窗口自动发现：%s → pid=%d hwnd=%d gw=%s" % (args.role, pw[0], pw[1], gw))
    else:
        gw = args.gateway
        print("警告：未按角色名定位到活窗口（%s），沿用 --gateway=%s" % (args.role, gw))
    hwnd = pw[1] if pw else ZGUI.get_hwnd()
    if not hwnd:
        print("未找到游戏窗口。")
        return 2
    # ★2026-09-17 任务感知：无乌鸡国任务才允许新开；有则只进已有副本。
    try:
        if FU_BEN._wuji_task_exists(gw):
            print("任务栏已有「乌鸡国」任务 → 本次只进入已有副本，不新开。")
        else:
            print("任务栏无「乌鸡国」任务 → 允许新开一个乌鸡副本。")
    except Exception:
        pass
    _install_signal()

    if not _wait_out_battle(gw):
        print("开跑前等待脱战超时，仍继续（撞战斗由下一轮裁决）")

    print("=" * 60)
    print("副本 | role=%s gw=%s" % (args.role, gw))
    print("  每轮 = 点快捷副本 → 红字识别开始XX副本 → 点进入XX副本 → 自动战斗")
    print("  只跑乌鸡副本（用户定案：其他副本无数据不开启，一天两次/副本）")
    print("=" * 60)

    i = 0
    total = 0
    err_n = 0
    while True:
        i += 1
        if _STOP.is_set():
            break
        if args.rounds and i > args.rounds:
            break
        # 多开下窗口手柄可能变化，每轮重新钉窗
        try:
            pw2 = ZGUI._find_role_window(args.role)
            if pw2:
                ZGUI.set_target_hwnd(pw2[1]); hwnd = pw2[1]
        except Exception:
            pass
        n = 0
        try:
            n = FU_BEN.run(gateway=gw, hwnd=hwnd, verbose=True) or 0
        except Exception:
            import traceback
            err_n += 1
            print("[%03d] 异常: %s\n%s" % (i, sys.exc_info()[1],
                                            traceback.format_exc(limit=4)))
            time.sleep(10.0)
            continue
        total += n
        print("[%03d] 本轮完成 %d 次副本 累计 %d 次 异常 %d 次" % (i, n, total, err_n))
        sys.stdout.flush()
        if _STOP.is_set() or (args.rounds and i >= args.rounds):
            break
        time.sleep(max(1.0, random.uniform(args.min_interval, args.max_interval)))

    print("=" * 60)
    print("结束 | 共 %d 轮 完成 %d 次副本 异常 %d 次" % (i, total, err_n))
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
