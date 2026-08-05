# -*- coding: utf-8 -*-
"""单字模式解码验证：8 张坐标截图应读出 地图名[X,Y]，0 UNKNOWN。"""
from __future__ import annotations
import sys, os
import numpy as np
from PIL import Image
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.glyph_recognizer import (
    GlyphRecognizer, COORD_WHITE_RULE, apply_color_mask, segment_single_chars,
)

IMG_DIR = r"E:/DS/梦幻西游脚本函数包/地图数据/字库图片"
FILES = [
    "东海湾.png", "建邺城.png", "建邺城1.png",
    "江南野外.png", "江南野外1.png", "江南野外2.png",
    "江南野外3.png", "江南野外4.png",
]


def main():
    rec = GlyphRecognizer()
    print(f"字库大小: {rec.library.size}\n")
    all_ok = True
    for f in FILES:
        path = os.path.join(IMG_DIR, f)
        arr = np.asarray(Image.open(path).convert("RGBA"))[:, :, :3]
        mask = apply_color_mask(arr, COORD_WHITE_RULE)
        blobs = segment_single_chars(mask, sort_by="x_asc")
        glyphs = []
        unk = 0
        for (x, y, w, h, crop) in blobs:
            _b, hx = rec.library.normalize_and_hash(crop) if hasattr(
                rec.library, "normalize_and_hash") else (None, None)
            # 用 recognizer 的统一归一化
            from core.glyph_recognizer import normalize_bitmap
            _b2, hx2 = normalize_bitmap(crop, target_size=(32, 32))
            ch = rec.library.lookup(hx2)
            if ch is None:
                unk += 1
                ch = "?"
            glyphs.append(ch)
        text = "".join(glyphs)
        ok = unk == 0
        all_ok = all_ok and ok
        print(f"{f:12s} -> {text:18s}  UNKNOWN={unk}  {'OK' if ok else 'FAIL'}")
    print(f"\n全部 0 UNKNOWN: {all_ok}")


if __name__ == "__main__":
    main()
