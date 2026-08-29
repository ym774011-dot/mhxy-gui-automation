# -*- coding: utf-8 -*-
"""WORLD_BOSS_auto_farm 实测跑批入口（2026-08-29，Diagnose 诊断轮）。

绑定：PID 15232 / 网关 http://127.0.0.1:18082
纪律：绝不触碰其他实例的网关（18083 等）。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

GAME_PID = 15232
GATEWAY = "http://127.0.0.1:18082"

from core.window_manager import window_manager

if not window_manager.find_by_pid(GAME_PID):
    print(f"[FATAL] PID={GAME_PID} 绑定失败（进程不存在或无可见窗口），退出", flush=True)
    sys.exit(1)

print(f"[bind] pid={window_manager.pid} hwnd=0x{getattr(window_manager,'hwnd',0):X}", flush=True)

from tasks.library.WORLD_BOSS import WORLD_BOSS_auto_farm

if __name__ == "__main__":
    r = WORLD_BOSS_auto_farm(max_runtime=1800, verbose=True, gateway=GATEWAY)
    print("=== RESULT ===", flush=True)
    print(r, flush=True)
