# -*- coding: utf-8 -*-
import sys
sys.path.insert(0, r'E:\DS\mhxy-gui-automation')
sys.path.insert(0, r'E:\DS\mhxy-gui-automation\tools')
import numpy as np
from PIL import Image
import calibrate_bigmap_v7 as v
from core.glyph_recognizer import apply_color_mask


def dbg(img, mx, my):
    a = np.asarray(img.convert('RGB')).astype(int)
    wx0, wy0 = mx + 18, max(0, my - 2)
    wx1, wy1 = min(img.size[0], mx + 150), min(img.size[1], my + 58)
    print('window', wx0, wy0, wx1, wy1)
    reg = a[wy0:wy1, wx0:wx1]
    mask = apply_color_mask(reg, v.TIP_RULE)
    rows = mask.sum(axis=1)
    print('total', int(rows.sum()))
    ri = np.where(rows >= 2)[0]
    print('ri', list(map(int, ri)))
    bands, start = [], ri[0]
    for i in range(1, len(ri)):
        if ri[i] - ri[i - 1] > 1:
            bands.append((start, ri[i - 1]))
            start = ri[i]
    bands.append((start, ri[-1]))
    print('bands', bands)
    bands.sort(key=lambda b: rows[b[0]:b[1] + 1].sum(), reverse=True)
    r0, r1 = bands[0]
    print('chosen', r0, r1, 'h', r1 - r0)
    band = mask[r0:r1 + 1]
    cols = band.sum(axis=0)
    ci = np.where(cols > 0)[0]
    cells, start = [], ci[0]
    for i in range(1, len(ci)):
        if ci[i] - ci[i - 1] > 1:
            cells.append((start, ci[i - 1]))
            start = ci[i]
    cells.append((start, ci[-1]))
    for c0, c1 in cells:
        sub = band[:, c0:c1 + 1]
        ys = np.where(sub.any(axis=1))[0]
        h = ys[-1] - ys[0] + 1
        w = c1 - c0 + 1
        cls = 'skip' if w * h <= 2 else ('D' if 8 <= h <= 16 and w <= 14 else (',' if w <= 5 and h <= 7 and ys[-1] >= (r1 - r0) - 3 else 'X'))
        print('  cell', c0, c1, 'w', w, 'h', h, 'ybot', int(ys[-1]), cls)


dbg(Image.open(r'cal7_江南野外_0.png'), 420, 270)
dbg(Image.open(r'cal7_江南野外_3.png'), 590, 250)
dbg(Image.open(r'cal7_江南野外_4.png'), 400, 400)
dbg(Image.open(r'cal7_建邺城_0.png'), 420, 270)
dbg(Image.open(r'cal7_建邺城_3.png'), 590, 250)
dbg(Image.open(r'cal7_建邺城_4.png'), 400, 400)
