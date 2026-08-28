# -*- coding: utf-8 -*-
"""WORLD_BOSS_auto_farm 实测跑批入口（未登记(2) 移除后验证，2026-08-28）。

绑定：PID 16840（然学701529）/ 网关 http://127.0.0.1:18082
纪律：绝不触碰网关 18083（另一组角色在跑）。
带插桩计数，与 test_after_fix.log（17:43 基线）同口径对比。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

GAME_PID = 16840
GATEWAY = "http://127.0.0.1:18082"

from core.window_manager import window_manager

if not window_manager.find_by_pid(GAME_PID):
    print(f"[FATAL] PID={GAME_PID} 绑定失败（进程不存在或无可见窗口），退出", flush=True)
    sys.exit(1)
print(f"[bind] window_manager 已绑定 pid={window_manager.pid}（走路通道可用）", flush=True)

import tasks.library.WORLD_BOSS as wb

# ---------- 插桩计数（与基线同口径） ----------
M = {"scan": 0, "recvall": 0, "in_battle": 0, "tab": 0, "cross_map": 0}

_orig_scan = wb.scan_scene_bosses
def _scan(*a, **k):
    M["scan"] += 1
    return _orig_scan(*a, **k)
wb.scan_scene_bosses = _scan

_orig_http = wb._http_json
def _http(gateway, path, data=None, timeout=10.0):
    if path == "/api/net/recvall":
        M["recvall"] += 1
    return _orig_http(gateway, path, data, timeout)
wb._http_json = _http

_orig_battle = wb._in_battle
def _battle(*a, **k):
    M["in_battle"] += 1
    return _orig_battle(*a, **k)
wb._in_battle = _battle

_orig_tab = wb._press_tab_if
def _tab(*a, **k):
    M["tab"] += 1
    return _orig_tab(*a, **k)
wb._press_tab_if = _tab

_orig_cm = wb._gw_cross_map
def _cm(*a, **k):
    M["cross_map"] += 1
    return _orig_cm(*a, **k)
wb._gw_cross_map = _cm

# ---------- 开跑 ----------
if __name__ == "__main__":
    r = wb.WORLD_BOSS_auto_farm(max_runtime=300, verbose=True, gateway=GATEWAY)
    print("=== farm 结果 ===", flush=True)
    print(f"ok: {r.get('ok')}", flush=True)
    print(f"farmed_total: {r.get('farmed_total')}", flush=True)
    print(f"elapsed: {r.get('elapsed')}", flush=True)
    print("=== 插桩指标（未登记(2)移除后）===", flush=True)
    print(f"总时长: {r.get('elapsed')}s", flush=True)
    print(f"场景全量扫描次数: {M['scan']}  (基线 13)", flush=True)
    print(f"recvall 全量 dump 次数: {M['recvall']}  (基线 10)", flush=True)
    print(f"_in_battle 查询次数: {M['in_battle']}  (基线 563)", flush=True)
    print(f"TAB 按键次数: {M['tab']}  (基线 8)", flush=True)
    print(f"cross_map 请求次数: {M['cross_map']}  (基线 1)", flush=True)
