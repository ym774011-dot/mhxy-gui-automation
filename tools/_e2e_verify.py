# -*- coding: utf-8 -*-
"""端到端验证：新 hop 链路 + 长寿郊外校准走路。"""
import sys, time
sys.path.insert(0, r"E:\DS\mhxy-gui-automation")
from tasks.library.WORLD_BOSS import _http_json, _gw_cross_map, _walk_to
from core.window_manager import window_manager

# 绑定 gateway 18082 对应的游戏进程（/api/status 的 pid）
window_manager.bind(pid=13924)
print("[0] window_manager bound:", window_manager.bound, "pid=", window_manager.pid)

GW = "http://127.0.0.1:18082"


def cur_map():
    d = _http_json(GW, "/api/lua/expr", {"expr": "tostring(tp.当前地图)"})
    return d.get("result", {}).get("value")


def pos():
    d = _http_json(GW, "/api/lua/expr",
                   {"expr": "tostring(math.floor((tp.角色坐标.x or 0)/20))..\",\"..tostring(math.floor((tp.角色坐标.y or 0)/20))"})
    return d.get("result", {}).get("value")


def dist(a, b):
    try:
        ax, ay = [int(v) for v in a.split(",")]
        bx, by = [int(v) for v in b.split(",")]
        return ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5
    except Exception:
        return -1


# 1) 模块级新链路：进长寿郊外
r = _gw_cross_map(GW, "长寿郊外")
time.sleep(2.5)
print("[1] _gw_cross_map(长寿郊外) ok=", r.get("ok"), "| 地图:", cur_map(), "pos:", pos())

# 2) 校准走路：往右下走 12,8 格
p0 = pos()
target = None
try:
    x0, y0 = p0.split(",")
    target = (int(x0) + 14, int(y0) + 9)
except Exception:
    print("!! 无法解析起点坐标", p0)
if target:
    w = _walk_to("长寿郊外", target[0], target[1], background=True, verbose=True)
    print("[2] 走路指令:", w.get("ok"), "|", w.get("message"))
    time.sleep(10)
    p1 = pos()
    d0, d1 = dist(p0, f"{target[0]},{target[1]}"), dist(p1, f"{target[0]},{target[1]}")
    print(f"[3] 起点 {p0} -> 现在 {p1} -> 目标 {target}")
    print(f"    距离: {d0:.1f} -> {d1:.1f}  ({'✓ 在接近目标' if d1 < d0 else '✗ 未移动/偏移'})")

# 3) 模块级验证花果山链路
r = _gw_cross_map(GW, "花果山")
time.sleep(2.5)
print("[4] _gw_cross_map(花果山) ok=", r.get("ok"), "| 地图:", cur_map(), "pos:", pos())
