# -*- coding: utf-8 -*-
"""
双区域颜色采样探测
  区域 A: 左上角 信息面板（地图名 + 坐标），用户称 #FFFFFF
  区域 B: JHRW 任务追踪栏 (837,120)-(996,236)，用户称 #FFFF00

输出：
  - 各区域的颜色直方图 TOP N
  - 各区域按用户指定颜色做精确掩码后的效果图
  - 放大图供肉眼确认
"""
import sys
import os
import ctypes
import ctypes.wintypes as wt
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from PIL import Image

user32 = ctypes.windll.user32
user32.GetWindowThreadProcessId.restype = wt.DWORD
user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'debug_capture')
os.makedirs(OUT, exist_ok=True)

REGION_A = (15, 19, 147, 43)        # 左上角当前地图名+坐标（用户给定，#FFFFFF）
REGION_B = (837, 120, 996, 236)     # JHRW 任务追踪栏（用户给定，#FFFF00）


def find_main_window(pid):
    found = []

    def cb(hwnd, lp):
        if not user32.IsWindowVisible(hwnd):
            return True
        wpid = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
        if wpid.value != pid:
            return True
        r = wt.RECT()
        user32.GetClientRect(hwnd, ctypes.byref(r))
        n = user32.GetWindowTextLengthW(hwnd)
        b = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, b, n + 1)
        found.append((hwnd, b.value, r.right, r.bottom))
        return True

    CB = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    user32.EnumWindows(CB(cb), 0)
    if not found:
        return None
    # 选面积最大的
    found.sort(key=lambda t: t[2] * t[3], reverse=True)
    return found[0]


def capture_client(hwnd, w, h):
    """mss 截客户区"""
    import mss
    pt = wt.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    with mss.mss() as sct:
        shot = sct.grab({'left': pt.x, 'top': pt.y, 'width': w, 'height': h})
        img = Image.frombytes('RGB', shot.size, shot.bgra, 'raw', 'BGRX')
    return img


def analyze(arr, name, region, target_rgb):
    x1, y1, x2, y2 = region
    x2 = min(x2, arr.shape[1])
    y2 = min(y2, arr.shape[0])
    sub = arr[y1:y2, x1:x2]
    print(f"\n{'=' * 62}")
    print(f"  区域 {name}: ({x1},{y1})-({x2},{y2})  尺寸 {x2-x1}x{y2-y1}")
    print(f"{'=' * 62}")

    flat = sub.reshape(-1, 3)
    cnt = Counter(map(tuple, flat))
    total = len(flat)
    print(f"  唯一颜色数: {len(cnt)}   像素总数: {total}")
    print(f"  --- TOP 15 颜色 ---")
    for rgb, c in cnt.most_common(15):
        pct = c / total * 100
        tag = ''
        r, g, b = rgb
        if r > 200 and g > 200 and b > 200:
            tag = '  <= 近白'
        elif r > 200 and g > 200 and b < 120:
            tag = '  <= 近黄'
        print(f"    RGB{rgb}  x{c:<7} {pct:5.2f}%{tag}")

    # 精确目标色统计
    tr, tg, tb = target_rgb
    exact = ((sub[:, :, 0] == tr) & (sub[:, :, 1] == tg) & (sub[:, :, 2] == tb))
    ne = int(exact.sum())
    print(f"\n  精确 RGB{target_rgb} 命中: {ne} px")
    if ne:
        ys, xs = np.nonzero(exact)
        print(f"    包围盒(相对): x=[{xs.min()},{xs.max()}] y=[{ys.min()},{ys.max()}]")
        print(f"    包围盒(绝对): x=[{xs.min()+x1},{xs.max()+x1}] y=[{ys.min()+y1},{ys.max()+y1}]")

    # 容差目标色统计
    tol = 24
    near = (np.abs(sub[:, :, 0].astype(int) - tr) <= tol) & \
           (np.abs(sub[:, :, 1].astype(int) - tg) <= tol) & \
           (np.abs(sub[:, :, 2].astype(int) - tb) <= tol)
    nn = int(near.sum())
    print(f"  容差±{tol} RGB{target_rgb} 命中: {nn} px")
    if nn:
        ys, xs = np.nonzero(near)
        print(f"    包围盒(绝对): x=[{xs.min()+x1},{xs.max()+x1}] y=[{ys.min()+y1},{ys.max()+y1}]")
        # 行分布
        rows = {}
        for yy in np.unique(ys):
            rows[int(yy)] = int((ys == yy).sum())
        # 找文字行段
        print(f"    文字行段(绝对y : 像素数):")
        seg_start = None
        prev = None
        for yy in sorted(rows):
            if seg_start is None:
                seg_start = yy
            elif prev is not None and yy - prev > 2:
                print(f"      y {seg_start + y1} ~ {prev + y1}")
                seg_start = yy
            prev = yy
        if seg_start is not None:
            print(f"      y {seg_start + y1} ~ {prev + y1}")

    # 保存放大图 + 掩码图
    scale = 4
    sub_img = Image.fromarray(sub)
    sub_img.resize(((x2 - x1) * scale, (y2 - y1) * scale), Image.NEAREST).save(
        os.path.join(OUT, f'region_{name}_x{scale}.png'))

    mask_img = Image.fromarray((near * 255).astype(np.uint8))
    mask_img.resize(((x2 - x1) * scale, (y2 - y1) * scale), Image.NEAREST).save(
        os.path.join(OUT, f'region_{name}_mask_x{scale}.png'))
    print(f"  已保存 region_{name}_x{scale}.png / region_{name}_mask_x{scale}.png")

    return cnt


def main():
    pid = int(sys.argv[1]) if len(sys.argv) > 1 else 23332
    win = find_main_window(pid)
    if not win:
        print(f"未找到 PID {pid} 的窗口")
        return
    hwnd, title, w, h = win
    print(f"窗口 hwnd=0x{hwnd:X}  客户区 {w}x{h}")
    print(f"标题 {title}")

    img = capture_client(hwnd, w, h)
    img.save(os.path.join(OUT, 'probe2_full.png'))
    arr = np.array(img)
    print(f"截图尺寸 {arr.shape[1]}x{arr.shape[0]}  已保存 probe2_full.png")

    analyze(arr, 'A_topleft', REGION_A, (255, 255, 255))
    analyze(arr, 'B_jhrw', REGION_B, (255, 255, 0))


if __name__ == '__main__':
    main()
