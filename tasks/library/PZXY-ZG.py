# -*- coding: utf-8 -*-
"""
PZXY-ZG.py - 胖子西游抓鬼一键整体流程（整体函数入口，可直接运行）
================================================================
把"接任务 → 回长安 → 天眼瞬移 → CALL 打鬼 → 完成判定 → 下一只"
封装为一个整体函数，队长/单开模式（组员模式已取消），无限循环直到
Ctrl+C，每轮记录 JSONL 并周期性输出汇总。

用法:
    python PZXY-ZG.py                       # 默认：二号美人 队长/单开
    python PZXY-ZG.py --role 二号美人 --timeout 25
    python PZXY-ZG.py --rounds 50           # 限轮数后自动退出

依赖: ZGUI.py（同目录）、mhxy-mcp-gateway 网关（默认 http://127.0.0.1:18082）
"""
import sys
import io
import os
import json
import time
import signal
import threading
import argparse
import datetime
import random

# 确保可独立运行也可被 GUI 任务库动态导入（同目录/项目库均可找到 ZGUI）
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

import ZGUI

# ============================================================
# 函数中文元信息（GUI 任务库下拉框显示用）
# ============================================================
__function_meta__ = {
    "zhuagui_run": {
        "title": "抓鬼整体流程：接任务→天眼→打鬼→回长安→下一只（队长/单开）",
        "args": {
            "role": "角色名（仅用于日志，默认 二号美人）",
            "gateway": "mhxy-mcp-gateway 地址（默认自动解析 18082）",
            "timeout": "点'送你回地府'后等待任务栏变化的超时秒数（默认20）",
            "wait_dialog": "CALL后等待对话框出现的秒数（默认1.2）",
            "rounds": "最多轮数（0=不限轮，直到手动停止；默认0，用户配置）",
            "summary_interval": "每N轮输出一次汇总（默认10）",
            "verbose": "是否打印过程日志",
        },
    },
    "main": {
        "title": "抓鬼整体流程（命令行入口，含参数解析）",
        "args": {
            "role": "角色名（默认 二号美人）",
            "gateway": "网关 URL（默认自动解析）",
            "timeout": "完成判定的超时秒数（默认20）",
            "wait_dialog": "等对话框秒数（默认1.2）",
            "rounds": "最多轮数，0=不限（默认0）",
            "verbose": "是否打印过程日志",
        },
    },
}

# ------------------------------------------------------------------
# 整体函数
# ------------------------------------------------------------------
def zhuagui_run(role="二号美人", gateway=None,
                timeout=20.0, wait_dialog=1.2, rounds=0,
                log_dir=None, summary_interval=10, verbose=False):
    """抓鬼整体循环：确保任务就绪 → 打鬼 → 完成判定 → 回长安 → 下一轮。

    Args:
        role:           角色名（仅用于日志/记录）
        gateway:        网关 URL；缺省按角色所在组端口解析（默认 18082）
        timeout:        点'送你回地府'后等待任务栏变化的超时（秒）
        wait_dialog:    CALL 后等待对话框出现的最长秒数
        rounds:         最多轮数（0=不限，直到 Ctrl+C）
        log_dir:        JSONL 日志目录（缺省 ./test_data）
        summary_interval: 每 N 轮输出一次进度汇总
        verbose:        是否打印过程日志

    Returns:
        dict: 汇总 {rounds, ok, fail_kinds, elapsed, log_path}
    """
    if gateway is None:
        gateway = ZGUI.DEFAULT_GATEWAY

    # ---- 日志初始化 ----
    d = log_dir or os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_data")
    os.makedirs(d, exist_ok=True)
    log_path = os.path.join(d, "zg_%s.jsonl" % datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
    logf = open(log_path, "a", encoding="utf-8")

    stop = {"flag": False}

    def _sigstop(sig, frm):
        stop["flag"] = True

    # ★2026-09-04 修复"signal only works in main thread"：
    # GUI 任务引擎在工作线程中调用本函数，signal.signal 只能主线程注册。
    # 非主线程（GUI/批处理）时跳过信号注册——停止交由 GUI 停止按钮/引擎
    # 的 should_stop / 异步异常注入打断；仅 CLI 主线程运行才注册 Ctrl+C。
    try:
        if threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGINT, _sigstop)
            signal.signal(signal.SIGTERM, _sigstop)
    except Exception:
        pass

    def _now():
        return datetime.datetime.now().isoformat(timespec="seconds")

    print("== 胖子西游抓鬼整体流程 ==", flush=True)
    print("  角色   :", role, flush=True)
    print("  网关   :", gateway, flush=True)
    print("  数据   :", log_path, flush=True)
    print("  操作   : Ctrl+C 停止并输出汇总", flush=True)

    round_no = 0
    ok_total = 0
    fail_kind_cnt = {}
    t_start = time.time()
    last_ok_count = ""

    def _random_pause(lo=1.2, hi=2.2):
        return random.uniform(lo, hi)

    def _summary(final=False):
        line = "=== %s 汇总：共%d轮，成功%d (%.1f%%)，耗时%.0fs%s ===" % (
            "结束" if final else "进度", round_no, ok_total,
            (100.0 * ok_total / round_no) if round_no else 0,
            time.time() - t_start,
            ("，失败类别: " + json.dumps(fail_kind_cnt, ensure_ascii=False))
            if fail_kind_cnt else "",
        )
        print(line, flush=True)

    while not stop["flag"]:
        if rounds and round_no >= rounds:
            break
        round_no += 1
        t0 = time.time()

        # --- 每轮开头确保背包打开（天眼/旗读取依赖背包面板） ---
        try:
            hwnd0 = ZGUI.get_hwnd()
            if hwnd0 and not ZGUI._bag_visible(gateway):
                ZGUI._bag_ensure_open(gateway, hwnd0, tries=2)
        except Exception:
            pass

        # --- 记录本轮开始状态 ---
        task0 = ZGUI.zhuagui_get_task(gateway) or {}
        try:
            raw_cnt0 = int((task0 or {}).get("count") or 0)
        except Exception:
            raw_cnt0 = -1

        try:
            ok, msg = ZGUI.zhuagui_do_round(gateway, wait_dialog=wait_dialog,
                                            timeout=timeout, verbose=verbose)
        except Exception as e:
            ok, msg = False, "异常:%s" % (e,)

        dur = round(time.time() - t0, 2)

        # --- 记录本轮结束状态 ---
        task = ZGUI.zhuagui_get_task(gateway) or {}
        target = (task or {}).get("name") or ""
        cnt = (task or {}).get("count") or ""
        c_map = ZGUI._lua_call(gateway,
                               r'''local m=tp.地图; __out=tostring(m and m.地图名称 or "")''') or "?"

        fail_kind = ""
        if not ok:
            if (target or "") == "" and (cnt or "") != "":
                fail_kind = "task"
            elif "天眼" in msg or "瞬移" in msg or "任务未就绪" in msg:
                fail_kind = "task"
            elif "目标" in msg or "野鬼" in msg or "找不到" in msg:
                fail_kind = "ghost"
            elif "超时" in msg or "战斗" in msg or "完成" in msg:
                fail_kind = "inbattle"
            else:
                fail_kind = "other"
            fail_kind_cnt[fail_kind] = fail_kind_cnt.get(fail_kind, 0) + 1
        else:
            ok_total += 1
            last_ok_count = cnt

        rec = {
            "ts": _now(), "round": round_no, "role": role,
            "target": target, "count": cnt, "map": c_map,
            "ok": ok, "msg": msg, "dur": dur, "fail_kind": fail_kind,
            "prev_count": raw_cnt0,
            "count_delta": (int(cnt) - raw_cnt0) if (str(cnt).isdigit() and str(raw_cnt0).isdigit()) else None,
        }
        logf.write(json.dumps(rec, ensure_ascii=False) + "\n")
        logf.flush()

        line = "[%s] round#%-4d %-8s 目标=%-16s 第%s次 地图=%-4s 结果=%s %s (%.1fs)%s" % (
            _now(), round_no, role, target[:16], cnt, c_map,
            "OK" if ok else "FAIL", msg[:40], dur,
            (" 类别=" + fail_kind) if fail_kind else "")
        print(line, flush=True)

        if round_no % max(1, summary_interval) == 0:
            _summary()

        # --- 轮间停顿（柔和化） ---
        if ok:
            time.sleep(_random_pause())
        else:
            try:
                ZGUI.zhuagui_go_back_changan(gateway)
            except Exception:
                pass
            time.sleep(_random_pause(2.5, 4.5))

    logf.flush()
    _summary(final=True)
    logf.close()
    return {
        "rounds": round_no, "ok": ok_total,
        "fail_kinds": fail_kind_cnt,
        "elapsed": round(time.time() - t_start, 1),
        "log_path": log_path,
    }


# ------------------------------------------------------------------
# 命令行入口
# ------------------------------------------------------------------
def main():
    # CLI 独立运行时才包装 stdout（任务库/GUI 动态导入时不包装，避免污染进程）
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(description="胖子西游抓鬼一键整体流程")
    p.add_argument("--role", default="二号美人", help="角色名（默认 二号美人）")
    p.add_argument("--gateway", default=None, help="网关 URL（默认自动解析）")
    p.add_argument("--timeout", type=float, default=20.0, help="完成判定的超时秒数（默认20）")
    p.add_argument("--wait-dialog", type=float, default=1.2, help="等对话框秒数（默认1.2）")
    p.add_argument("--rounds", type=int, default=0, help="最多轮数，0=不限（默认0）")
    p.add_argument("--summary", type=int, default=10, help="每N轮输出汇总（默认10）")
    p.add_argument("--verbose", action="store_true", help="打印过程日志")
    args = p.parse_args()

    result = zhuagui_run(
        role=args.role, gateway=args.gateway,
        timeout=args.timeout, wait_dialog=args.wait_dialog, rounds=args.rounds,
        summary_interval=args.summary, verbose=args.verbose,
    )
    print("运行结束:", json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()