# -*- coding: utf-8 -*-
"""
地图 UI 矩形校准工具 —— 鼠标悬停角点按回车，自动记录客户区矩形。

用法:
    E:/py/python.exe tools/calibrate_ui_blocks.py [地图名] [PID]

流程（按提示操作）:
    1. 把鼠标移到「大地图」左上角 → 回车
    2. 把鼠标移到「大地图」右下角 → 回车
    3. 把鼠标移到「任务追踪面板」左上角 → 回车
    4. 把鼠标移到「任务追踪面板」右下角 → 回车
    5. 自动写入 data/map_ui_blocks.json（可反复校准覆盖）

说明:
    - 屏幕坐标 → 客户区坐标（ScreenToClient）
    - origin/scale 从地图函数包模块读取（JNYW 等），写进 JSON
    - 矩形建议「宁大勿小」：多盖一点 UI 边缘，避免漏掉点击失效区
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/..")

import json
import win32api
import win32gui

# 地图函数包目录（模块 → origin/scale 校准）
MAP_LIB_DIR = r"E:/DS/梦幻西游脚本函数包/地图数据"
# 地图名 → 模块名（与 core/map_no_go.py 的 MODULE_MAP_NAME 对应）
MAP_MODULE = {
    "江南野外": "JNYW",
    "建邺城": "JYC",
    "东海湾": "DHW",
    "长安城": "CAC",
    "傲来国": "ALG",
    "宝象国": "BXG",
    "长寿村": "CSC",
    "西凉女国": "XLNR",
    "朱紫国": "ZZG",
}

UI_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "data", "map_ui_blocks.json"
)


def read_map_calibration(map_name: str):
    """从地图函数模块读 MAP_ORIGIN_PIXEL / MAP_SCALE。"""
    module_name = MAP_MODULE.get(map_name)
    if not module_name:
        return None
    path = os.path.join(MAP_LIB_DIR, f"{module_name}.py")
    if not os.path.exists(path):
        return None
    ns = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            src = f.read()
        # 只提取两个常量（避免执行整个模块产生副作用）
        import re
        for key in ("MAP_ORIGIN_PIXEL", "MAP_SCALE"):
            m = re.search(
                rf"^{key}\s*=\s*\(([^)]+)\)", src, re.MULTILINE
            )
            if m:
                nums = [float(x.strip()) for x in m.group(1).split(",") if x.strip()]
                ns[key] = nums
    except Exception as e:
        print(f"读取校准失败: {e}")
        return None
    if "MAP_ORIGIN_PIXEL" not in ns or "MAP_SCALE" not in ns:
        print(f"警告: {module_name}.py 未找到 MAP_ORIGIN_PIXEL/MAP_SCALE")
        return None
    return (ns["MAP_ORIGIN_PIXEL"], ns["MAP_SCALE"])


def wait_point(prompt: str, hwnd: int) -> tuple:
    """提示用户把鼠标移到目标位置后按回车，返回客户区坐标。"""
    input(f"\n{prompt}\n  移动鼠标到目标位置后按回车…")
    sx, sy = win32api.GetCursorPos()
    return win32gui.ScreenToClient(hwnd, (sx, sy))


def main():
    map_name = sys.argv[1] if len(sys.argv) > 1 else "江南野外"
    print(f"=== 校准 {map_name} 的 UI 矩形 ===\n")

    calib = read_map_calibration(map_name)
    if calib is None:
        print(f"❌ 无法读取 {map_name} 的地图校准（MAP_ORIGIN_PIXEL/MAP_SCALE）")
        return
    origin, scale = calib
    print(f"校准: origin={origin} scale={scale}")

    # 找游戏窗口并绑定（优先前台游戏窗口）
    from core.window_manager import window_manager
    from core.screen_capture import screen_capture

    pid = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    if pid and window_manager.find_by_pid(pid):
        window_manager.bind(window_manager.hwnd, pid=pid)
    else:
        # 枚举游戏窗口，取面积最大/前台
        wins = window_manager.list_game_windows()
        cands = [w for w in wins if "鲜衣怒马" in w[1]]
        if not cands:
            print("❌ 未找到游戏窗口")
            return
        cands.sort(key=lambda w: w[3], reverse=True)
        hwnd, title, gpid, _ = cands[0]
        window_manager.bind(hwnd, pid=gpid)
        print(f"已绑定: {title[:40]} pid={gpid}")

    if not window_manager.is_valid():
        print("❌ 窗口无效")
        return
    cw, ch = window_manager.get_client_size()
    print(f"客户区: {cw}x{ch}")
    hwnd = window_manager.hwnd

    print("\n说明: 依次把鼠标移到每个矩形的角点（注意别碰到游戏窗口边缘）")
    input("准备好了按回车开始（游戏窗口保持在屏幕上可见）…")

    rects = {}
    # 大地图
    p1 = wait_point("【大地图/小地图】左上角", hwnd)
    p2 = wait_point("【大地图/小地图】右下角", hwnd)
    # 任务追踪
    p3 = wait_point("【任务追踪面板】左上角（若当前被大地图盖住，先关大地图再校准）", hwnd)
    p4 = wait_point("【任务追踪面板】右下角", hwnd)

    # 已是客户区坐标
    cpts = [p1, p2, p3, p4]
    (x1a, y1a), (x2a, y2a), (x1b, y1b), (x2b, y2b) = cpts

    def norm(x1, y1, x2, y2):
        return (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))

    a1, a2, a3, a4 = norm(x1a, y1a, x2a, y2a)
    b1, b2, b3, b4 = norm(x1b, y1b, x2b, y2b)
    blocks = [
        {"name": "大地图", "x1": a1, "y1": a2, "x2": a3, "y2": a4},
        {"name": "任务追踪面板", "x1": b1, "y1": b2, "x2": b3, "y2": b4},
    ]
    print("\n=== 测量结果（客户区像素）===")
    for blk in blocks:
        print(f"  {blk['name']}: ({blk['x1']},{blk['y1']})-({blk['x2']},{blk['y2']})")

    # 写入 JSON（合并已有数据）
    data = {}
    if os.path.exists(UI_PATH):
        with open(UI_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    data[map_name] = {
        "origin": [float(origin[0]), float(origin[1])],
        "scale": [float(scale[0]), float(scale[1])],
        "blocks": blocks,
    }
    with open(UI_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 已保存到 {UI_PATH}")
    print("提示: 校准结果「宁大勿小」，若跑任务发现偏移点仍失效，把矩形外扩几个像素重跑本工具。")


if __name__ == "__main__":
    main()
