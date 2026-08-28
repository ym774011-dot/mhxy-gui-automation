# -*- coding: utf-8 -*-
"""大图锚定采样：同图瞬移到多个坐标 → Tab 截大图 → 记录 (游戏坐标, 截图文件)。

用法: python tools/debug_bigmap_sample.py
输出: debug_walk_map_s<N>.png + stdout 采样表
"""
import json
import sys
import time
import urllib.request

sys.path.insert(0, r'E:\DS\mhxy-gui-automation')
sys.path.insert(0, r'E:\DS\mhxy-gui-automation\tools')
from core.window_manager import WindowManager  # noqa: E402
import debug_bigmap_shot as d  # noqa: E402

GW = "http://127.0.0.1:18082"

SAMPLES = [(60, 60), (300, 80), (80, 260), (300, 260)]


def teleport(x, y):
    req = urllib.request.Request(
        GW + "/api/act/teleport", b'{"x":%d,"y":%d}' % (x, y),
        {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=8) as r:
        return json_ok(r)


def json_ok(r):
    return json.loads(r.read().decode("utf-8", "replace")).get("ok")


def wait_battle(max_s=60):
    t0 = time.time()
    while time.time() - t0 < max_s:
        if d.expr("tostring(tp.战斗中)") != "true":
            return True
        time.sleep(1.5)
    return False


def main():
    wm = WindowManager()
    wm.bind(pid=4172)
    rows = []
    for i, (x, y) in enumerate(SAMPLES):
        if not wait_battle():
            print(f"!! 样本{i} 等战斗超时，跳过")
            continue
        ok = teleport(x, y)
        time.sleep(1.2)  # 落地步进
        gx, gy = d.role_grid()
        path = rf'E:\DS\mhxy-gui-automation\debug_walk_map_s{i}.png'
        d.press_tab(wm.hwnd)
        w, h = d.bitblt_window(wm.hwnd, path)
        d.press_tab(wm.hwnd)
        rows.append((i, x, y, gx, gy, path))
        print(f"s{i}: 目标({x},{y}) 实读({gx:.1f},{gy:.1f}) -> {path} {w}x{h}")
        time.sleep(0.5)


if __name__ == "__main__":
    main()
