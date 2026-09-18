# -*- coding: utf-8 -*-
"""门派闯关（独立方案 2026-09-14；PP GUI 方案"门派闯关"队长脚本）。

与"抓鬼+闯关+顺手打"（run_unlimited_test.py 随机插入）互不影响：
本脚本**只做门派闯关**——连续报名/续跑考验战斗，做完一场再自动接下一场，
不掺入抓鬼、不扫怪。业务主链路由 tasks/library/CHUANGGUAN.run() 完整承担
（含摄妖香、传门派、CALL 护法、放马过来、自动战斗、任务追踪裁决）。

队内成员沿用 member_sell_loop.py（纯出售/保活），跟随队长进考验战斗。

用法：
  E:/py/python.exe run_chuangguan.py --gateway file://pzxy_p<pid> --role 二号美人
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
from tasks.library import CHUANGGUAN                # noqa: E402

_LOG = logging.getLogger("mhxy")

_STOP = threading.Event()


def _install_signal():
    def _h(signum, frame):
        global _STOP
        if _STOP.is_set():
            signal.signal(signal.SIGINT, signal.SIG_DFL)
            return
        _STOP.set()
        sys.stdout.write("\n[stop] 完成当前轮闯关后优雅退出（再按 Ctrl+C 强制）\n")
        sys.stdout.flush()
    signal.signal(signal.SIGINT, _h)


def _wait_out_battle(gw, max_s=60.0):
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
    ap = argparse.ArgumentParser(description="门派闯关（PP GUI 方案：门派闯关）")
    ap.add_argument("--gateway", default="file://pzxy", help="网关/播种通道")
    ap.add_argument("--role", default="二号美人", help="角色名（多开钉窗）")
    ap.add_argument("--rounds", type=int, default=0, help="跑几轮（0=无限，一轮=接一次闯关做到完成）")
    ap.add_argument("--min-interval", type=float, default=8.0)
    ap.add_argument("--max-interval", type=float, default=20.0)
    # ★2026-09-14：PP GUI 通传给队长脚本 --timeout/--wait-dialog（抓鬼方案用），
    #   本脚本不识别曾致 argparse 报错退出，接受忽略（与 run_unlimited_hunt 同款）。
    ap.add_argument("--timeout", type=float, default=None, help="兼容 PP GUI 通用传参（本脚本不使用）")
    ap.add_argument("--wait-dialog", type=float, default=None, help="兼容 PP GUI 通用传参（本脚本不使用）")
    # ★2026-09-18：PP GUI 的看门狗补拉 / 补组重拉会带 --skip-team（"跳过组队路径"拉起的标记）。
    #   本脚本不涉及该语义 → 接受并忽略。否则 argparse 报错退出 → 被当成"脚本已死" →
    #   看门狗每 ~46s 反复重拉（2026-09-18 14:26~14:41 pp_gui.log 实锤），任务永远跑不起来。
    ap.add_argument("--skip-team", action="store_true",
                    help="兼容 PP GUI 跳过组队路径的拉起（本脚本不使用）")
    args = ap.parse_args(argv)
    random.seed()

    gw = args.gateway
    pw = None
    try:
        pw = ZGUI._find_role_window(args.role)
        if pw:
            ZGUI.set_target_hwnd(pw[1])
    except Exception:
        pass
    hwnd = pw[1] if pw else ZGUI.get_hwnd()
    if not hwnd:
        print("未找到游戏窗口。")
        return 2
    _install_signal()

    if not _wait_out_battle(gw):
        print("开跑前等待脱战超时，仍继续（撞战斗由下一轮裁决）")

    print("=" * 60)
    print("门派闯关 | role=%s gw=%s" % (args.role, gw))
    print("  每轮 = 报名（无进行中任务时）→ 逐门派考验至完成 → 自动再报名")
    print("=" * 60)

    i = 0
    total_won = 0
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
        won = 0
        try:
            won = 1 if CHUANGGUAN.run(gateway=gw, hwnd=hwnd, verbose=True) else 0
        except Exception:
            import traceback
            err_n += 1
            print("[%03d] 异常: %s\n%s" % (i, sys.exc_info()[1],
                                            traceback.format_exc(limit=4)))
            time.sleep(10.0)
            continue
        total_won += won
        print("[%03d] 闯关%s 本场赢 %d 场 累计 %d 场 异常 %d 次"
              % (i, "完成 ✓" if won else "失败/中止", won, total_won, err_n))
        sys.stdout.flush()
        if _STOP.is_set() or (args.rounds and i >= args.rounds):
            break
        time.sleep(max(1.0, random.uniform(args.min_interval, args.max_interval)))

    print("=" * 60)
    print("结束 | 共 %d 轮 赢 %d 场 异常 %d 次" % (i, total_won, err_n))
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())