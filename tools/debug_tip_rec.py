# -*- coding: utf-8 -*-
import sys
sys.path.insert(0, r'E:\DS\mhxy-gui-automation')
sys.path.insert(0, r'E:\DS\mhxy-gui-automation\tools')
import numpy as np
from PIL import Image
import calibrate_bigmap_v7 as v
from core.glyph_recognizer import apply_color_mask, get_glyph_recognizer


def dbg(img, mx, my, show_rec=False):
    rec = get_glyph_recognizer()
    a = np.asarray(img.convert('RGB')).astype(int)
    wx0, wy0 = mx + 18, max(0, my - 2)
    reg = a[wy0:my + 58, wx0:mx + 150]
    mask = apply_color_mask(reg, v.TIP_RULE)
    rows = mask.sum(axis=1)
    ri = np.where(rows >= 2)[0]
    bands, start = [], ri[0]
    for i in range(1, len(ri)):
        if ri[i] - ri[i - 1] > 1:
            bands.append((start, ri[i - 1]))
            start = ri[i]
    bands.append((start, ri[-1]))
    bands.sort(key=lambda b: rows[b[0]:b[1] + 1].sum(), reverse=True)
    r0, r1 = bands[0]
    band = mask[r0:r1 + 1]
    cols = band.sum(axis=0)
    ci = np.where(cols > 0)[0]
    cells, start = [], ci[0]
    for i in range(1, len(ci)):
        if ci[i] - ci[i - 1] > 1:
            cells.append((start, ci[i - 1]))
            start = ci[i]
    cells.append((start, ci[-1]))
    toks = []
    for c0, c1 in cells:
        sub = band[:, c0:c1 + 1]
        ys = np.where(sub.any(axis=1))[0]
        h = ys[-1] - ys[0] + 1
        w = c1 - c0 + 1
        if w * h <= 2:
            cls = 'skip'
        elif 8 <= h <= 16 and w <= 14:
            cls = 'D'
        elif w <= 5 and h <= 7 and ys[-1] >= (r1 - r0) - 3:
            cls = ','
        else:
            cls = 'X'
        toks.append(cls)
    print(mx, my, 'toks', toks)
    if show_rec:
        crop = reg[r0:r1 + 1, ci[0]:ci[-1] + 1]
        res = rec.recognize(crop, rule=v.TIP_RULE, segmentation='columns')
        print('   recognize raw:', repr(res.raw_text), 'conf:', getattr(res, 'confidence', None))
        print('   chars:', [(ch, round(getattr(cf, 'distance', 0), 3) if hasattr(cf, 'distance') else None) for ch, cf in (res.chars if hasattr(res, 'chars') else [])][:8])


dbg(Image.open(r'cal7_江南野外_3.png'), 590, 250, True)
dbg(Image.open(r'cal7_建邺城_3.png'), 590, 250, True)
dbg(Image.open(r'cal7_江南野外_4.png'), 400, 400, True)
