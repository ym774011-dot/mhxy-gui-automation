# -*- coding: utf-8 -*-
"""
验证点取色标定工具（2026-08-18）。

点击验证（click_verified）需要验证点"点击后颜色会持久变化"。本工具
在游戏运行、窗口已绑定时，读取指定客户区坐标的颜色，用于标定验证点：

用法：
  python tools/pick_color.py 163 278                # 取单个点颜色
  python tools/pick_color.py 163 278 300 400        # 取多个点
  python tools/pick_color.py 163 278 --watch 0.5    # 每 0.5s 打印一次（切换界面观察变化）

标定流程（以"打开背包"为例）：
  1. 游戏停在"背包未打开"状态，运行本工具看 (163,278) 的颜色 A
  2. 手动打开背包，再看同一坐标颜色 B
  3. A != B → 该点可用作"打开背包"的验证点
  4. A == B → 换点（背包界面没覆盖这里），直到找到必变的点
"""
import sys
import time

sys.path.insert(0, r"E:\DS\mhxy-gui-automation")

from core.window_manager import window_manager  # noqa: E402
from core.screen_capture import screen_capture  # noqa: E402


def pick(x: int, y: int):
    """读取客户区 (x,y) 颜色，返回 RGB tuple 或 None。"""
    img = screen_capture.capture_region(x, y, 1, 1)
    if img is None or img.size == 0:
        return None
    b, g, r = img[0][0]
    return (int(r), int(g), int(b))


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    watch = 0.0
    if "--watch" in sys.argv:
        try:
            watch = float(sys.argv[sys.argv.index("--watch") + 1])
        except (IndexError, ValueError):
            watch = 0.5

    if len(args) < 2 or len(args) % 2 != 0:
        print("用法: python tools/pick_color.py X Y [X2 Y2 ...] [--watch 秒]")
        return

    if not window_manager.hwnd or not window_manager.is_valid():
        print("[err] 未绑定有效窗口。请先启动 GUI 并绑定游戏窗口，或用 GUI 绑定后运行。")
        return

    pts = [(int(args[i]), int(args[i + 1])) for i in range(0, len(args), 2)]

    if watch <= 0:
        for x, y in pts:
            c = pick(x, y)
            print(f"({x},{y}) RGB={c if c else '取色失败'}")
        return

    # watch 模式：循环打印，Ctrl+C 退出
    print(f"[watch] 每 {watch}s 打印一次，Ctrl+C 退出")
    try:
        while True:
            parts = []
            for x, y in pts:
                c = pick(x, y)
                parts.append(f"({x},{y})={c if c else '?'}")
            print(f"{time.strftime('%H:%M:%S')} " + "  ".join(parts), flush=True)
            time.sleep(max(0.1, watch))
    except KeyboardInterrupt:
        print("\n[exit]")


if __name__ == "__main__":
    main()
