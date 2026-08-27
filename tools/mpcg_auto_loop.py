# -*- coding: utf-8 -*-
"""门派闯关自动循环：整轮自动，直接调用 MPCG.MPCG_auto_round 全链路。

内部编排（均在 MPCG_auto_round 内）: 状态轮询→验证码优先暂停避让→三态分发
（战斗/弹窗/空闲）→识别下一门派→瞬移→CALL护法→请出招吧开战→循环至完成弹窗
→回城长安(193,125)→(rounds>1)自动接下一轮。龙宫走特殊分支，内置 seq_identity 安全闸。

本脚本仅做参数解析 + 网关自愈确认 + 结果打印。
用法: python mpcg_auto_loop.py [--timeout 900] [--max-steps 15] [--rounds 1]
"""
import json, urllib.request, time, argparse, os, sys

GW = "http://127.0.0.1:18083"
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(ROOT))
from library.map_packs import MPCG as M


def ensure_gateway(gw: str):
    """网关自愈确认：不可用则尝试拉起，仍不可用返回 False。"""
    try:
        d = json.loads(urllib.request.urlopen(gw + "/api/status", timeout=10)
                       .read().decode("utf-8", "replace"))
        if (d.get("result") or {}).get("pid"):
            return True
    except Exception:
        pass
    try:
        from core.gateway_guard import ensure_gateway as gw_up
        ok, info = gw_up(gw)
        if ok:
            print("网关自愈拉起成功:", info, flush=True)
            return True
        print("网关自愈失败:", info, flush=True)
    except Exception as e:
        print("网关自愈异常:", e, flush=True)
    return False


def main():
    ap = argparse.ArgumentParser(description="门派闯关整轮自动（直接调用 MPCG_auto_round）")
    ap.add_argument("--timeout", type=int, default=900, help="整轮最长等待秒数")
    ap.add_argument("--max-steps", type=int, default=15, help="每轮最大关卡数")
    ap.add_argument("--rounds", type=int, default=1, help="连续自动跑几轮（完成后自动回城接下一轮）")
    ap.add_argument("--gateway", type=str, default=GW, help="网关地址")
    ap.add_argument("--start-delay", type=int, default=0, help="启动前等待秒数")
    args = ap.parse_args()

    if not ensure_gateway(args.gateway):
        print("网关不可用，无法运行自动循环", flush=True)
        sys.exit(1)

    if args.start_delay:
        time.sleep(args.start_delay)

    t0 = time.time()
    res = M.MPCG_auto_round(
        timeout=args.timeout,
        max_steps=args.max_steps,
        rounds=args.rounds,
        gateway=args.gateway,
        verbose=True,
    )
    print("=" * 50, flush=True)
    print("结果:", json.dumps(res, ensure_ascii=False, indent=1), flush=True)
    print(f"总耗时 {int(time.time()-t0)}s", flush=True)


if __name__ == "__main__":
    main()