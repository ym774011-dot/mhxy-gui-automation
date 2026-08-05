# -*- coding: utf-8 -*-
"""Dump full-line ASCII + column projection for a given channel, to understand
character spacing / cell width of the fixed bitmap font."""
import sys, os
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.glyph_recognizer import (
    apply_color_mask, JHRW_YELLOW_RULE, JHRW_RED_RULE,
    JHRW_WHITE_RULE, JHRW_GREEN_RULE,
)

IMG_DIR = r"E:\DS\梦幻西游脚本函数包\地图数据\字库图片"
RULES = {
    "yellow": JHRW_YELLOW_RULE, "red": JHRW_RED_RULE,
    "white": JHRW_WHITE_RULE, "green": JHRW_GREEN_RULE,
}


def main():
    kw = sys.argv[1] if len(sys.argv) > 1 else "建邺城任务"
    color = sys.argv[2] if len(sys.argv) > 2 else "yellow"
    files = sorted(f for f in os.listdir(IMG_DIR) if f.endswith(".png") and kw in f)
    fname = files[0]
    img = Image.open(os.path.join(IMG_DIR, fname)).convert("RGBA")
    arr = np.array(img)
    if arr.shape[2] == 4:
        alpha = arr[:, :, 3:4].astype(float) / 255.0
        arr = (arr[:, :, :3] * alpha).astype(np.uint8)
    rule = RULES[color]
    mask = apply_color_mask(arr, rule)
    col_has = mask.any(axis=0)
    # column projection: print run-length of blank/ink columns
    print(f"=== {fname} / {color} ===")
    print("cols:", mask.shape[1], "rows:", mask.shape[0])
    # find ink columns
    ink_cols = np.where(col_has)[0]
    if len(ink_cols) == 0:
        print("(no ink)")
        return
    x0, x1 = int(ink_cols[0]), int(ink_cols[-1])
    print(f"ink x-range: {x0}..{x1} (width {x1-x0+1})")
    # blank-column gaps (character separators)
    gaps = []
    i = x0
    runs = []
    prev_state = col_has[x0]
    start = x0
    for x in range(x0, x1 + 1):
        s = col_has[x]
        if s != prev_state:
            runs.append((prev_state, start, x - 1))
            start = x
            prev_state = s
    runs.append((prev_state, start, x1))
    print("runs (ink?, x0, x1):")
    for ink, a, b in runs:
        print(f"  {'INK' if ink else 'gap':3} {a:3}..{b:3} w={b-a+1}")
    # blank-only columns inside ink range (potential char boundaries if width>=2)
    print("\nblank columns (width>=2) between chars:")
    for ink, a, b in runs:
        if not ink and (b - a + 1) >= 2:
            print(f"  gap {a}..{b} w={b-a+1}")
    # ASCII of the whole ink region
    print("\nASCII (ink region):")
    sub = mask[:, x0:x1 + 1]
    # downscale rows to ~20 for readability
    hh, ww = sub.shape
    th = 20
    scale = th / hh
    new_w = max(1, int(round(ww * scale)))
    ys = np.clip((np.arange(th) / scale).astype(int), 0, hh - 1)
    xs = np.clip((np.arange(new_w) / scale).astype(int), 0, ww - 1)
    scaled = sub[np.ix_(ys, xs)]
    for row in scaled:
        print("".join("#" if v else "." for v in row))


if __name__ == "__main__":
    main()
