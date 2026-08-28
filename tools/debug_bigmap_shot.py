# -*- coding: utf-8 -*-
"""诊断 2：等战斗间隙 → Tab 开大图 → BitBlt 截图落盘（不点击）→ Tab 关。

看大图实际缩放/锚定，验证校准数据为什么两个采样点互相矛盾。
"""
import ctypes
import ctypes.wintypes as wt
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, r'E:\DS\mhxy-gui-automation')
from library.common.win_utils import locate_game_window  # noqa: E402

GW = "http://127.0.0.1:18082"
OUT = r'E:\DS\mhxy-gui-automation\debug_walk_map.png'
user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32


def expr(e, timeout=8):
    req = urllib.request.Request(
        GW + "/api/lua/expr", json.dumps({"expr": e}).encode("utf-8"),
        {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read().decode("utf-8", "replace"))
    if not d.get("ok"):
        raise RuntimeError(d.get("error"))
    return (d.get("result") or {}).get("value") or ""


def role_grid():
    v = expr('tostring(tp.角色坐标.x)..","..tostring(tp.角色坐标.y)')
    xs, ys = v.split(",", 1)
    return float(xs) / 20.0, float(ys) / 20.0


SRCCOPY = 0x00CC0020
CAPTUREBLT = 0x40000000


def bitblt_window(hwnd, path):
    rc = wt.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rc))
    w, h = rc.right, rc.bottom
    hdc_win = user32.GetWindowDC(hwnd)
    hdc_mem = gdi32.CreateCompatibleDC(hdc_win)
    hbmp = gdi32.CreateCompatibleBitmap(hdc_win, w, h)
    gdi32.SelectObject(hdc_mem, hbmp)
    gdi32.BitBlt(hdc_mem, 0, 0, w, h, hdc_win, 0, 0, SRCCOPY | CAPTUREBLT)
    # BMP 落盘
    class BMPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32),
                    ("biHeight", ctypes.c_int32), ("biPlanes", ctypes.c_uint16),
                    ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
                    ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_int32),
                    ("biYPelsPerMeter", ctypes.c_int32), ("biClrUsed", ctypes.c_uint32),
                    ("biClrImportant", ctypes.c_uint32)]
    bmi = BMPINFOHEADER(ctypes.sizeof(BMPINFOHEADER), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(hdc_mem, hbmp, 0, h, buf, ctypes.byref(bmi), 0)
    from PIL import Image
    img = Image.frombytes("RGBX", (w, h), buf.raw, "raw", "BGRX").convert("RGB")
    img.save(path)
    gdi32.DeleteObject(hbmp)
    gdi32.DeleteDC(hdc_mem)
    user32.ReleaseDC(hwnd, hdc_win)
    return w, h


VK_TAB = 0x09
WM_KEYDOWN, WM_KEYUP = 0x0100, 0x0101


def press_tab(hwnd):
    user32.PostMessageW(hwnd, WM_KEYDOWN, VK_TAB, 0)
    time.sleep(0.05)
    user32.PostMessageW(hwnd, WM_KEYUP, VK_TAB, 0)
    time.sleep(0.8)


def main():
    pid = int(expr("tostring(tonumber(_G.__pid) or 0)") or 0) or 19744
    hwnd, title = locate_game_window(pid, verbose=True)
    if not hwnd:
        print("!! 未找到窗口, 退回枚举")
        return
    print(f"hwnd=0x{hwnd:X} title={title}")

    # 1) 等战斗结束（最多 150s）
    print("等待战斗结束…")
    t0 = time.time()
    while time.time() - t0 < 150:
        if expr("tostring(tp.战斗中)") != "true":
            break
        time.sleep(2.0)
    g1 = role_grid()
    print(f"战斗外, 角色网格 = ({g1[0]:.1f},{g1[1]:.1f})")

    # 2) Tab 开大图 → 截图 → Tab 关
    press_tab(hwnd)
    w, h = bitblt_window(hwnd, OUT)
    press_tab(hwnd)
    print(f"截图 {OUT}  尺寸 {w}x{h}  截后角色 = {role_grid()}")


if __name__ == "__main__":
    main()
