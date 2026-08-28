# -*- coding: utf-8 -*-
"""大图标定 v7：零传送。Tab 开图 → 悬停探针 → 读黑框黄字 tooltip → 解线性映射。

pixel = origin + scale * game
每图 3 探针互验（残差<1.5px）+ 第 4 探针独立验证。
产出 data/bigmap_calibration.json
"""
import json
import ctypes
import sys
import time

sys.path.insert(0, r'E:\DS\mhxy-gui-automation')
sys.path.insert(0, r'E:\DS\mhxy-gui-automation\tools')
import numpy as np
from PIL import Image
from core.window_manager import WindowManager  # noqa: E402
from core.glyph_recognizer import (ColorMaskRule,  # noqa: E402
                                   apply_color_mask,
                                   get_glyph_recognizer)
import debug_bigmap_shot as d  # noqa: E402

WM_MOUSEMOVE = 0x0200
WM_KEYDOWN, WM_KEYUP = 0x0100, 0x0101
TIP_RULE = ColorMaskRule(name='tip_yellow', r_min=220, r_max=255,
                         g_min=200, g_max=255, b_min=0, b_max=110)
# 候选探针点（面板内，避开标题/右侧栏），失败依次换
PROBES = [(420, 270), (560, 380), (480, 320), (590, 250), (400, 400)]


def press_esc(hwnd):
    ctypes.windll.user32.PostMessageW(hwnd, WM_KEYDOWN, 0x1B, 0)
    time.sleep(0.05)
    ctypes.windll.user32.PostMessageW(hwnd, WM_KEYUP, 0x1B, 0)


def hover(hwnd, x, y):
    lp = (y << 16) | (x & 0xFFFF)
    for _ in range(3):
        ctypes.windll.user32.PostMessageW(hwnd, WM_MOUSEMOVE, 0, lp)
        time.sleep(0.02)


def wait_battle(max_s=240):
    t0 = time.time()
    while time.time() - t0 < max_s:
        if d.expr("tostring(tp.战斗中)") != "true":
            return True
        time.sleep(2)
    return False


def find_tooltip_box(img, mx, my):
    """在光标右下找深色圆角框，返回文字区 (x0,y0,x1,y1) 或 None。"""
    a = np.asarray(img.convert('RGB')).astype(int)
    x0, x1 = mx + 5, min(img.size[0], mx + 170)
    y0, y1 = my - 5, min(img.size[1], my + 60)
    reg = a[y0:y1, x0:x1]
    dark = (reg[:, :, 0] < 75) & (reg[:, :, 1] < 75) & (reg[:, :, 2] < 75)
    rows = dark.sum(axis=1)
    cols = dark.sum(axis=0)
    ri = np.where(rows >= 25)[0]
    if len(ri) < 12:
        return None
    r0, r1 = ri[0], ri[-1]
    band = dark[r0:r1 + 1]
    ci = np.where(band.sum(axis=0) >= (r1 - r0) * 0.55)[0]
    if len(ci) < 30:
        return None
    c0, c1 = ci[0], ci[-1]
    # 内缩 4px 取文字区
    tx0, ty0 = x0 + c0 + 4, y0 + r0 + 4
    tx1, ty1 = x0 + c1 - 3, y0 + r1 - 3
    if tx1 - tx0 < 20 or ty1 - ty0 < 10:
        return None
    return tx0, ty0, tx1, ty1


def read_tooltip(img, mx, my, rec):
    """固定窗口内纯黄字模切分：数字(高9~16) + 低位小逗号(宽<=5高<=6)。"""
    a = np.asarray(img.convert('RGB')).astype(int)
    wx0, wy0 = mx + 18, max(0, my - 2)
    wx1, wy1 = min(img.size[0], mx + 150), min(img.size[1], my + 58)
    reg = a[wy0:wy1, wx0:wx1]
    mask = apply_color_mask(reg, TIP_RULE)
    rows = mask.sum(axis=1)
    if rows.sum() < 25:
        return None
    ri = np.where(rows >= 2)[0]  # 剔除孤立噪点行，正文行每行≥2px
    if len(ri) < 7:
        return None
    bands, start = [], ri[0]
    for i in range(1, len(ri)):
        if ri[i] - ri[i - 1] > 1:  # 差=1 是相邻行，>1 才是空隙
            bands.append((start, ri[i - 1]))
            start = ri[i]
    bands.append((start, ri[-1]))
    bands.sort(key=lambda b: rows[b[0]:b[1] + 1].sum(), reverse=True)
    r0, r1 = bands[0]
    if not (7 <= r1 - r0 <= 17):
        return None
    band = mask[r0:r1 + 1]
    cols = band.sum(axis=0)
    ci = np.where(cols > 0)[0]
    ci = ci[ci <= ci[0] + 80]  # 提示框文字区最宽 ~70px，右侧是场景黄噪点
    cells, start = [], ci[0]
    for i in range(1, len(ci)):
        if ci[i] - ci[i - 1] > 1:
            cells.append((start, ci[i - 1]))
            start = ci[i]
    cells.append((start, ci[-1]))
    # 逐 cell 分类 + 单字模识别（绕开整串切分器的并块问题）
    out = ''
    for c0, c1 in cells:
        sub = band[:, c0:c1 + 1]
        ys = np.where(sub.any(axis=1))[0]
        h = ys[-1] - ys[0] + 1
        w = c1 - c0 + 1
        if w * h <= 2:
            continue  # 1~2px 场景噪点
        if 8 <= h <= 16 and w <= 14:
            crop = reg[r0 + ys[0]:r0 + ys[-1] + 1, c0:c1 + 1]
            res = rec.recognize(crop, rule=TIP_RULE, return_unknowns=True)
            out += res.raw_text if res.raw_text else '?'
        elif w <= 5 and h <= 7 and ys[-1] >= (r1 - r0) - 3:
            out += ','
        else:
            break  # 异形块=文字已结束，后面是场景噪点
    if out.count(',') != 1:
        return None
    parts = out.split(',')
    if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit() \
            and len(parts[0]) <= 3 and len(parts[1]) <= 3:
        return int(parts[0]), int(parts[1]), out
    return None


def map_open(wm):
    """检测大地图面板标题栏（深蓝 41,48,90 条带）。"""
    path = r'E:\DS\mhxy-gui-automation\cal7_check.png'
    d.bitblt_window(wm.hwnd, path)
    a = np.asarray(Image.open(path).convert('RGB')).astype(int)
    strip = a[158:178, 440:720]
    m = ((strip[:, :, 0] >= 28) & (strip[:, :, 0] <= 62) &
         (strip[:, :, 1] >= 36) & (strip[:, :, 1] <= 72) &
         (strip[:, :, 2] >= 76) & (strip[:, :, 2] <= 118)).sum()
    return m >= 150


def ensure_open(wm, tries=3):
    for i in range(tries):
        if map_open(wm):
            return True
        d.press_tab(wm.hwnd)
        time.sleep(1.2)
    return map_open(wm)


def probe(wm, rec, mx, my, tag):
    hover(wm.hwnd, mx, my)
    time.sleep(0.7)
    path = rf'E:\DS\mhxy-gui-automation\cal7_{tag}.png'
    d.bitblt_window(wm.hwnd, path)
    img = Image.open(path)
    r = read_tooltip(img, mx, my, rec)
    if r:
        print(f"  probe({mx},{my}) -> game({r[0]},{r[1]}) raw='{r[2]}'")
    else:
        # 区分：图没开 → 补开重试一次；图开着无提示 → ESC 换探针
        if not map_open(wm):
            print(f"  probe({mx},{my}) 地图未开，补开重试")
            press_esc(wm.hwnd)  # 清掉悬停弹出的菜单
            time.sleep(0.3)
            if ensure_open(wm):
                hover(wm.hwnd, mx, my)
                time.sleep(0.7)
                d.bitblt_window(wm.hwnd, path)
                r = read_tooltip(Image.open(path), mx, my, rec)
                if r:
                    print(f"  retry({mx},{my}) -> game({r[0]},{r[1]}) raw='{r[2]}'")
                    return r
        print(f"  probe({mx},{my}) -> 无有效tooltip，ESC重试")
        press_esc(wm.hwnd)
        time.sleep(0.3)
    return r


def calibrate_map(wm, rec, map_name, need=3):
    wait_battle()
    d.press_tab(wm.hwnd)  # 单次开图（若残留开图则被关闭，ensure_open 会兜底）
    time.sleep(1.3)
    if not ensure_open(wm):
        print(f"!! [{map_name}] 地图打不开")
        return None
    pts = []
    for i, (mx, my) in enumerate(PROBES):
        if len(pts) >= need:
            break
        wait_battle(30)
        if d.expr("tostring(tp.战斗中)") == "true":
            d.press_tab(wm.hwnd)
            wait_battle()
            d.press_tab(wm.hwnd)
            time.sleep(1.2)
        r = probe(wm, rec, mx, my, f"{map_name}_{i}")
        if r:
            # 探针点 = 提示框对应游戏坐标（框内文字跟随光标）
            pts.append(((mx, my), (r[0], r[1])))
    d.press_tab(wm.hwnd)  # 关图
    time.sleep(0.5)
    if len(pts) < need:
        print(f"!! [{map_name}] 有效探针 {len(pts)}/{need} 不足")
        return None
    # 线性拟合 pixel = o + s*game（两个方向独立）
    gx = np.array([p[1][0] for p in pts], float)
    gy = np.array([p[1][1] for p in pts], float)
    px = np.array([p[0][0] for p in pts], float)
    py = np.array([p[0][1] for p in pts], float)
    sx, ox = np.polyfit(gx, px, 1)
    sy, oy = np.polyfit(gy, py, 1)
    res_x = np.abs(ox + sx * gx - px).max()
    res_y = np.abs(oy + sy * gy - py).max()
    span_x = gx.max() - gx.min()
    span_y = gy.max() - gy.min()
    print(f"[{map_name}] scale=({sx:.4f},{sy:.4f}) origin=({ox:.1f},{oy:.1f}) "
          f"residual=({res_x:.2f},{res_y:.2f}) span=({span_x:.0f},{span_y:.0f})")
    if span_x < 25 or span_y < 25:
        print(f"!! [{map_name}] 探针游戏坐标跨度不足，拟合不稳")
        return None
    if res_x > 2.0 or res_y > 2.0:
        print(f"!! [{map_name}] 残差过大，探针数据可疑")
        return None
    # 独立验证：用剩余探针（或重取一点）
    ok = False
    for mx, my in PROBES:
        if any((mx, my) == p[0] for p in pts):
            continue
        wait_battle(30)
        d.press_tab(wm.hwnd)
        time.sleep(1.2)
        r = probe(wm, rec, mx, my, f"{map_name}_v")
        d.press_tab(wm.hwnd)
        time.sleep(0.4)
        if r:
            pred_x = ox + sx * r[0]
            pred_y = oy + sy * r[1]
            err = ((pred_x - mx) ** 2 + (pred_y - my) ** 2) ** 0.5
            print(f"  验证: game({r[0]},{r[1]}) 预测pixel({pred_x:.1f},{pred_y:.1f}) "
                  f"实际({mx},{my}) err={err:.1f}px")
            ok = err < 3.0
            break
    if not ok:
        print(f"!! [{map_name}] 独立验证失败")
        return None
    return {"origin": [round(ox, 2), round(oy, 2)],
            "scale": [round(sx, 5), round(sy, 5)],
            "residual": [round(res_x, 2), round(res_y, 2)],
            "verified": True}


CHAINS = [
    ("江南野外", ["长安传送江南野外"]),
    ("建邺城", ["江南野外传送建邺城"]),
    ("大唐国境", ["长安传送大唐国境"]),
]


def find_game_hwnd(pid):
    """按标题找游戏主窗口（主窗口可能最小化，client=0 会输给聊天窗口）。"""
    import ctypes.wintypes as wt
    result = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def cb(hwnd, _):
        wpid = wt.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
        if wpid.value != pid or not ctypes.windll.user32.IsWindowVisible(hwnd):
            return True
        n = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, n + 1)
        if '怀旧江南版' in buf.value:
            result.append(hwnd)
        return True

    ctypes.windll.user32.EnumWindows(cb, 0)
    return result[0] if result else None


def main():
    wm = WindowManager()
    if not wm.bind(pid=4172) or '怀旧江南版' not in (wm.window_title or ''):
        hwnd = find_game_hwnd(4172)
        if not hwnd:
            print('!! 找不到游戏主窗口')
            return
        wm._bind_hwnd(hwnd)
    rec = get_glyph_recognizer()
    out = {}
    path_json = r'E:\DS\mhxy-gui-automation\data\bigmap_calibration.json'
    try:
        with open(path_json, encoding='utf-8') as f:
            out = json.load(f)
    except Exception:
        pass
    import urllib.request
    for map_name, chain in CHAINS:
        print(f"==== {map_name} ====")
        for attempt in range(2):
            wait_battle()
            for desc in chain:
                req = urllib.request.Request(
                    "http://127.0.0.1:18082/api/act/cross_map",
                    json.dumps({"desc": desc, "x": 100, "y": 100}).encode(),
                    {"Content-Type": "application/json"})
                urllib.request.urlopen(req, timeout=15).read()
                time.sleep(1.6)
            time.sleep(1.0)
            r = calibrate_map(wm, rec, map_name)
            if r:
                out[map_name] = r
                break
            print(f"  [{map_name}] 第{attempt + 1}次失败，重试")
        with open(path_json, 'w', encoding='utf-8') as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
