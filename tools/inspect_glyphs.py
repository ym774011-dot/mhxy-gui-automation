# -*- coding: utf-8 -*-
"""逐字打印某张坐标截图的 字模hash + 当前标签 + ASCII，用于核实括号等标签。"""
from __future__ import annotations
import sys, os
import numpy as np
from PIL import Image
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.glyph_recognizer import (
    GlyphRecognizer, COORD_WHITE_RULE, apply_color_mask, segment_single_chars,
    normalize_bitmap,
)

IMG = sys.argv[1] if len(sys.argv) > 1 else r"E:/DS/梦幻西游脚本函数包/地图数据/字库图片/东海湾.png"

def main():
    rec = GlyphRecognizer()
    arr = np.asarray(Image.open(IMG).convert("RGBA"))[:, :, :3]
    mask = apply_color_mask(arr, COORD_WHITE_RULE)
    blobs = segment_single_chars(mask, sort_by="x_asc")
    print(f"文件: {os.path.basename(IMG)}  字模数: {len(blobs)}\n")
    for i, (x, y, w, h, crop) in enumerate(blobs):
        _b, hx = normalize_bitmap(crop, target_size=(32, 32))
        ch = rec.library.lookup(hx)
        art = "\n".join("".join("#" if crop[yy, xx] else "." for xx in range(w)) for yy in range(h))
        print(f"[{i}] hash={hx}  label={ch!r}  bbox=({x},{y},{w},{h})")
        print(art)
        print()

if __name__ == "__main__":
    main()
