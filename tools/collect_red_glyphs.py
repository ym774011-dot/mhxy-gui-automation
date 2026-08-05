# -*- coding: utf-8 -*-
"""抽取 JHRW 任务截图「红通道」的单字，打印 ASCII 供人工标注。

红通道 (#FF0000) 内容：任务名「初出江湖」+ 进度「当前第N次)」。
目标：补录单字 初/出/湖/第（江/当/前/次/) 已在库，0-9 已在库）。
"""
from __future__ import annotations
import os, sys, json
from collections import defaultdict

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.glyph_recognizer import (
    GlyphRecognizer, GlyphLibrary, JHRW_RED_RULE,
    apply_color_mask, segment_single_chars, normalize_bitmap,
)

IMG_DIR = r"E:\DS\梦幻西游脚本函数包\地图数据\字库图片"
TASK_FILES = [f for f in os.listdir(IMG_DIR) if "任务" in f and f.endswith(".png")]

rec = GlyphRecognizer()
lib = rec.library


def ascii_art(crop: np.ndarray, th=0) -> str:
    h, w = crop.shape
    lines = []
    for y in range(h):
        row = ""
        for x in range(w):
            row += "#" if crop[y, x] > th else "."
        lines.append(row)
    return "\n".join(lines)


def main():
    seen = {}  # hash -> (label, crop, ascii)
    for f in sorted(TASK_FILES):
        path = os.path.join(IMG_DIR, f)
        arr = np.asarray(Image.open(path).convert("RGBA"))[:, :, :3]
        mask = apply_color_mask(arr, JHRW_RED_RULE)
        blobs = segment_single_chars(mask, sort_by="x_asc")
        for (x, y, w, h, crop) in blobs:
            if w < 2 or h < 3:
                continue
            _bmp, h32 = normalize_bitmap(crop, target_size=(32, 32))
            label = lib.lookup(h32)
            if h32 not in seen:
                seen[h32] = (label, crop, f)

    # 找出「库中没有」的未录入字
    unknowns = {h: v for h, v in seen.items() if v[0] is None}
    print(f"唯一字模 {len(seen)} 个，未录入 {len(unknowns)} 个\n")
    print("=" * 60)
    print("未录入红通道单字（请人工判定标签）：")
    print("=" * 60)
    idx = 0
    for h, (label, crop, src) in unknowns.items():
        idx += 1
        print(f"\n[{idx}] hash={h}  from={src}")
        print(ascii_art(crop))
    print("\n" + "=" * 60)
    print("已录入（仅供参考）：")
    for h, (label, crop, src) in seen.items():
        if label is not None:
            print(f"  {label!r} <- {h}")


if __name__ == "__main__":
    main()
