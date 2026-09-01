# -*- coding: utf-8 -*-
"""WORLD_BOSS farm 整夜守护（2026-08-31 00:30 用户定案：测到 07:00）。

- 每轮 WORLD_BOSS_auto_farm(3600s)，到点自动开下一轮（farm 内部 max_runtime 到
  期正常结束 → 无缝续跑）；
- 意外异常（游戏崩溃/网关断）→ 短暂等待自愈（gateway_guard 会自动重绑新 PID）
  后重试，不中断整夜测量；
- 到 07:00（或 stop 标志文件存在）退出。全程 stdout 打点。
"""
import os
import sys
import time
import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

STOP_FLAG = r"E:\DS\STOP_OVERNIGHT.flag"
END_HOUR, END_MINUTE = 7, 0
GATEWAY = "http://127.0.0.1:18082"

from core.window_manager import window_manager
from tasks.library.WORLD_BOSS import WORLD_BOSS_auto_farm, _ensure_walker_bound


def _end_time_reached() -> bool:
    now = datetime.datetime.now()
    target = now.replace(hour=END_HOUR, minute=END_MINUTE, second=0, microsecond=0)
    if now.hour >= END_HOUR:
        return now >= target
    return False


def _stale_game_pid() -> int:
    """找当前组（然学 701529）最新游戏 PID；找不到返回 0。"""
    try:
        from core.gateway_guard import _bound_pid
        pid = _bound_pid()
        return int(pid or 0)
    except Exception:
        return 0


def main():
    rounds = 0
    total_kills = 0
    print(f"=== 整夜守护开始 {datetime.datetime.now().strftime('%H:%M:%S')} → 目标 07:00 ===", flush=True)
    while not _end_time_reached():
        if os.path.exists(STOP_FLAG):
            print("[守护] 检测到停止标志文件，退出", flush=True)
            os.remove(STOP_FLAG)
            break
        pid = _stale_game_pid()
        if pid <= 0:
            print("[守护] 无可用游戏 PID，等待 5s 自动重绑...", flush=True)
            time.sleep(5)
            continue
        if not window_manager.find_by_pid(pid):
            print(f"[守护] find_by_pid({pid}) 失败，等待自愈...", flush=True)
            time.sleep(5)
            continue
        rounds += 1
        print(f"\n=== 第 {rounds} 轮 farm 开始 "
              f"{datetime.datetime.now().strftime('%H:%M:%S')} pid={window_manager.pid} ===", flush=True)
        try:
            r = WORLD_BOSS_auto_farm(max_runtime=3600, verbose=True, gateway=GATEWAY)
            total_kills += int(r.get("farmed_total") or 0)
            print(f"=== 第 {rounds} 轮结束：{r} ===", flush=True)
        except Exception as e:
            print(f"=== 第 {rounds} 轮异常（游戏可能已崩，等待自愈）: {e} ===", flush=True)
            time.sleep(10)
    print(f"=== 整夜守护结束 {datetime.datetime.now().strftime('%H:%M:%S')} "
          f"轮数={rounds} 累计击杀={total_kills} ===", flush=True)


if __name__ == "__main__":
    main()