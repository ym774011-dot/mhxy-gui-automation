# -*- coding: utf-8 -*-
"""探针：JHRW 黄通道用 gap_threshold=1 切分，看中文是否过度拆分。"""
import sys, os
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.glyph_recognizer import (
    apply_color_mask, segment_characters, normalize_bitmap, GlyphLibrary,
    JHRW_YELLOW_RULE,
)

IMG_DIR = r"E:\DS\梦幻西游脚本函数包\地图数据\字库图片"
lib = GlyphLibrary()
files = ["建邺城任务.png", "江南野外任务.png", "东海湾任务.png"]


def decode(mask, gap):
    seq = []
    for (x, y, w, h, crop) in segment_characters(mask, gap_threshold=gap):
        _b, nh = normalize_bitmap(crop, target_size=(32, 32))
        ch = lib.lookup(nh)
        seq.append((ch if ch else "?", w))
    return seq


for f in files:
    img = Image.open(os.path.join(IMG_DIR, f)).convert("RGBA")
    arr = np.array(img)
    if arr.shape[2] == 4:
        alpha = arr[:, :, 3:4].astype(float) / 255.0
        arr = (arr[:, :, :3] * alpha).astype(np.uint8)
    mask = apply_color_mask(arr, JHRW_YELLOW_RULE)
    print(f"\n# {f}")
    for gap in (2, 1):
        seq = decode(mask, gap)
        txt = "".join(c for c, w in seq)
        print(f"  gap={gap}: {txt}  (blobs={len(seq)})")
        for c, w in seq:
            print(f"      '{c}' w={w}")
