# -*- coding: utf-8 -*-
"""大图 tooltip 探针：悬停已知像素 → 读"当前坐标"提示 → 解映射。零传送。"""
import ctypes
import sys
import time

sys.path.insert(0, r'E:\DS\mhxy-gui-automation')
sys.path.insert(0, r'E:\DS\mhxy-gui-automation\tools')
from core.window_manager import WindowManager  # noqa: E402
import debug_bigmap_shot as d  # noqa: E402

WM_MOUSEMOVE = 0x0200
PROBES = [(400, 260), (560, 360), (480, 310)]  # 面板内 3 点（冗余验证）


def hover(hwnd, x, y):
    lp = (y << 16) | (x & 0xFFFF)
    for _ in range(3):
        ctypes.windll.user32.PostMessageW(hwnd, WM_MOUSEMOVE, 0, lp)
        time.sleep(0.02)


def wait_battle(max_s=180):
    t0 = time.time()
    while time.time() - t0 < max_s:
        if d.expr("tostring(tp.战斗中)") != "true":
            return True
        time.sleep(2)
    return False


def main():
    wm = WindowManager()
    wm.bind(pid=4172)
    wait_battle()
    for i, (mx, my) in enumerate(PROBES):
        wait_battle()
        d.press_tab(wm.hwnd)
        time.sleep(1.2)
        hover(wm.hwnd, mx, my)
        time.sleep(0.8)
        path = rf'E:\DS\mhxy-gui-automation\tooltip_{i}.png'
        d.bitblt_window(wm.hwnd, path)
        # 裁剪提示框区域另存
        from PIL import Image
        img = Image.open(path)
        crop = img.crop((max(0, mx - 100), max(0, my - 40),
                         min(img.size[0], mx + 120), min(img.size[1], my + 50)))
        crop.save(rf'E:\DS\mhxy-gui-automation\tooltip_crop_{i}.png')
        d.press_tab(wm.hwnd)
        time.sleep(0.6)
        print(f"probe{i} hover=({mx},{my}) saved")
    print("done")


if __name__ == "__main__":
    main()
