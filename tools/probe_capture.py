# -*- coding: utf-8 -*-
"""
Step 1 — 截屏通道探测。

目标：验证能否从游戏窗口截到左上角那行 #FFFF00 黄色文字。
这是字模指纹方案的前提，不通则整条路线作废。

三条通道逐级降级：
    1. mss        —— 桌面合成截图（最快，但被遮挡会截到别的窗口）
    2. PrintWindow(PW_RENDERFULLCONTENT) —— 直接向窗口要图，可后台截
    3. BitBlt     —— 传统 GDI 拷贝（对 DX 自绘常黑屏，兜底）

每条通道都会：
    - 保存整幅客户区 PNG
    - 保存左上角 ROI PNG（放大 4 倍便于肉眼看）
    - 统计接近 #FFFF00 的像素数量与包围盒

用法：
    python tools/probe_capture.py [pid]
"""
import ctypes
import ctypes.wintypes as wt
import os
import sys

import numpy as np
from PIL import Image

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "debug_capture")
OUT_DIR = os.path.abspath(OUT_DIR)

# 左上角 ROI：宽松一点，宁可多截也别切掉字
# ocr_coord_reader 里的 COORD_REGION 是 (9, 21, 129, 21)，这里放大范围先看全貌
ROI = (0, 0, 320, 80)  # x, y, w, h（客户区相对坐标）

TARGET_RGB = (0xFF, 0xFF, 0x00)

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

user32.GetWindowThreadProcessId.restype = wt.DWORD
user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]


# ----------------------------------------------------------------------
# 窗口定位
# ----------------------------------------------------------------------
def find_game_window(pid=None):
    """按 PID 或标题关键字找游戏主窗口，返回 (hwnd, pid, title, cw, ch)。"""
    found = []

    def cb(hwnd, lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        if n <= 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        title = buf.value
        wpid = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))

        hit = False
        if pid is not None:
            hit = (wpid.value == pid)
        else:
            hit = any(k in title for k in ("鲜衣怒马", "梦幻", "怀旧"))

        if hit:
            rect = wt.RECT()
            user32.GetClientRect(hwnd, ctypes.byref(rect))
            if rect.right > 200 and rect.bottom > 200:  # 排除小的辅助窗口
                found.append((hwnd, wpid.value, title, rect.right, rect.bottom))
        return True

    CB = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    user32.EnumWindows(CB(cb), 0)
    if not found:
        return None
    # 同一 PID 下可能有「聊天窗口」等辅助窗口，取客户区面积最大的作为主窗口
    found.sort(key=lambda t: t[3] * t[4], reverse=True)
    return found[0]


def client_to_screen(hwnd):
    """客户区左上角在屏幕上的坐标。"""
    pt = wt.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    return pt.x, pt.y


# ----------------------------------------------------------------------
# 通道 1：mss
# ----------------------------------------------------------------------
def grab_mss(hwnd, cw, ch):
    try:
        import mss
    except ImportError:
        return None, "mss 未安装"
    try:
        sx, sy = client_to_screen(hwnd)
        with mss.mss() as sct:
            raw = sct.grab({"left": sx, "top": sy, "width": cw, "height": ch})
        arr = np.asarray(raw)  # BGRA
        return arr[:, :, [2, 1, 0]].copy(), None  # -> RGB
    except Exception as e:
        return None, str(e)


# ----------------------------------------------------------------------
# 通道 2：PrintWindow + PW_RENDERFULLCONTENT
# ----------------------------------------------------------------------
PW_RENDERFULLCONTENT = 0x00000002


def grab_printwindow(hwnd, cw, ch, flags=PW_RENDERFULLCONTENT):
    """向窗口索要一份自渲染位图。DWM 下对多数 DX 窗口有效，且可后台截。"""
    hdc_win = user32.GetDC(hwnd)
    if not hdc_win:
        return None, "GetDC 失败"
    hdc_mem = gdi32.CreateCompatibleDC(hdc_win)
    hbmp = gdi32.CreateCompatibleBitmap(hdc_win, cw, ch)
    old = gdi32.SelectObject(hdc_mem, hbmp)
    try:
        ok = user32.PrintWindow(hwnd, hdc_mem, flags)
        if not ok:
            return None, f"PrintWindow 返回 {ok}"
        return _bitmap_to_array(hdc_mem, hbmp, cw, ch), None
    except Exception as e:
        return None, str(e)
    finally:
        gdi32.SelectObject(hdc_mem, old)
        gdi32.DeleteObject(hbmp)
        gdi32.DeleteDC(hdc_mem)
        user32.ReleaseDC(hwnd, hdc_win)


# ----------------------------------------------------------------------
# 通道 3：BitBlt
# ----------------------------------------------------------------------
SRCCOPY = 0x00CC0020


def grab_bitblt(hwnd, cw, ch):
    hdc_win = user32.GetDC(hwnd)
    if not hdc_win:
        return None, "GetDC 失败"
    hdc_mem = gdi32.CreateCompatibleDC(hdc_win)
    hbmp = gdi32.CreateCompatibleBitmap(hdc_win, cw, ch)
    old = gdi32.SelectObject(hdc_mem, hbmp)
    try:
        ok = gdi32.BitBlt(hdc_mem, 0, 0, cw, ch, hdc_win, 0, 0, SRCCOPY)
        if not ok:
            return None, "BitBlt 失败"
        return _bitmap_to_array(hdc_mem, hbmp, cw, ch), None
    except Exception as e:
        return None, str(e)
    finally:
        gdi32.SelectObject(hdc_mem, old)
        gdi32.DeleteObject(hbmp)
        gdi32.DeleteDC(hdc_mem)
        user32.ReleaseDC(hwnd, hdc_win)


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
        ("biPlanes", wt.WORD), ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
        ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", wt.LONG),
        ("biYPelsPerMeter", wt.LONG), ("biClrUsed", wt.DWORD),
        ("biClrImportant", wt.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wt.DWORD * 3)]


def _bitmap_to_array(hdc_mem, hbmp, cw, ch):
    """GDI 位图 -> RGB numpy 数组。"""
    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = cw
    bmi.bmiHeader.biHeight = -ch  # 负数 = 自顶向下，省去翻转
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bmi.bmiHeader.biCompression = 0  # BI_RGB

    buf = ctypes.create_string_buffer(cw * ch * 4)
    gdi32.GetDIBits(hdc_mem, hbmp, 0, ch, buf, ctypes.byref(bmi), 0)
    arr = np.frombuffer(buf.raw, dtype=np.uint8).reshape(ch, cw, 4)
    return arr[:, :, [2, 1, 0]].copy()  # BGRA -> RGB


# ----------------------------------------------------------------------
# 分析
# ----------------------------------------------------------------------
def analyze_yellow(rgb, tag, tol=40):
    """统计接近 #FFFF00 的像素，返回 (数量, 包围盒, 掩码)。"""
    r = rgb[:, :, 0].astype(np.int16)
    g = rgb[:, :, 1].astype(np.int16)
    b = rgb[:, :, 2].astype(np.int16)
    mask = (
        (np.abs(r - TARGET_RGB[0]) <= tol)
        & (np.abs(g - TARGET_RGB[1]) <= tol)
        & (np.abs(b - TARGET_RGB[2]) <= tol)
    )
    cnt = int(mask.sum())
    bbox = None
    if cnt > 0:
        ys, xs = np.nonzero(mask)
        bbox = (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))
    return cnt, bbox, mask


def probe(name, grabber, hwnd, cw, ch):
    print(f"\n{'=' * 62}")
    print(f"通道: {name}")
    print("=" * 62)
    rgb, err = grabber(hwnd, cw, ch)
    if rgb is None:
        print(f"  [失败] {err}")
        return None

    # 全黑判定（DX 窗口 BitBlt 常见现象）
    nonzero = int((rgb.sum(axis=2) > 12).sum())
    ratio = nonzero / (cw * ch)
    print(f"  截图尺寸: {rgb.shape[1]}x{rgb.shape[0]}, 非黑像素占比: {ratio:.1%}")
    if ratio < 0.01:
        print("  [失败] 几乎全黑，该通道拿不到 DX 渲染内容")
        return None

    Image.fromarray(rgb).save(os.path.join(OUT_DIR, f"{name}_full.png"))

    # ROI
    x, y, w, h = ROI
    w = min(w, cw - x)
    h = min(h, ch - y)
    roi = rgb[y:y + h, x:x + w]
    Image.fromarray(roi).resize((w * 4, h * 4), Image.NEAREST).save(
        os.path.join(OUT_DIR, f"{name}_roi_x4.png")
    )

    # 严格匹配（tol=0）
    cnt0, bbox0, _ = analyze_yellow(roi, name, tol=0)
    # 宽松匹配（tol=40，抗抗锯齿边缘）
    cnt40, bbox40, mask40 = analyze_yellow(roi, name, tol=40)

    print(f"  ROI {ROI}:")
    print(f"    纯 #FFFF00 (tol=0) : {cnt0} px, bbox={bbox0}")
    print(f"    近似黄  (tol=40)   : {cnt40} px, bbox={bbox40}")

    if cnt0 > 20:
        print("    [OK] 存在大量纯 #FFFF00 像素 —— 字模方案可行")
    elif cnt40 > 20:
        print("    [注意] 只有近似黄，纯色像素少，需放宽掩码阈值")
    else:
        print("    [失败] ROI 内没有黄色文字，可能 ROI 位置不对或该通道拿不到 UI 层")

    # 掩码可视化
    if cnt40 > 0:
        vis = np.zeros((h, w), dtype=np.uint8)
        vis[mask40] = 255
        Image.fromarray(vis).resize((w * 4, h * 4), Image.NEAREST).save(
            os.path.join(OUT_DIR, f"{name}_mask_x4.png")
        )

    # 全图黄色分布——万一 ROI 框错了，可以看到真实位置
    cntf, bboxf, _ = analyze_yellow(rgb, name, tol=20)
    print(f"  全客户区近似黄像素: {cntf} px, bbox={bboxf}")

    return {"name": name, "cnt0": cnt0, "cnt40": cnt40, "bbox": bbox40, "full_bbox": bboxf}


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    pid = int(sys.argv[1]) if len(sys.argv) > 1 else None

    win = find_game_window(pid)
    if not win:
        print("未找到游戏窗口")
        return 1
    hwnd, wpid, title, cw, ch = win
    print(f"窗口: hwnd=0x{hwnd:X} pid={wpid} 客户区={cw}x{ch}")
    print(f"标题: {title}")
    print(f"输出目录: {OUT_DIR}")

    results = []
    for name, fn in (
        ("mss", grab_mss),
        ("printwindow", grab_printwindow),
        ("bitblt", grab_bitblt),
    ):
        r = probe(name, fn, hwnd, cw, ch)
        if r:
            results.append(r)

    print(f"\n{'=' * 62}")
    print("结论")
    print("=" * 62)
    usable = [r for r in results if r["cnt0"] > 20 or r["cnt40"] > 20]
    if usable:
        best = max(usable, key=lambda r: r["cnt0"])
        print(f"  推荐通道: {best['name']}  (纯黄 {best['cnt0']}px / 近似黄 {best['cnt40']}px)")
        print(f"  ROI 内黄字包围盒: {best['bbox']}")
        print(f"  全客户区黄字包围盒: {best['full_bbox']}")
    else:
        print("  三条通道都拿不到黄字，需要改用 Windows Graphics Capture 或 DXGI")
    print(f"\n请打开 {OUT_DIR} 肉眼确认 *_roi_x4.png 与 *_mask_x4.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
