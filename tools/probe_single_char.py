# -*- coding: utf-8 -*-
"""
单字切分探针：对每张 JHRW 截图按 4 颜色通道做单字切分，
打印每个独立字符的归一化 hash + ASCII，便于人工逐字标注。
只标注来自图片像素的内容，绝不引用文件名数字。
"""
import sys, os
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.glyph_recognizer import (
    apply_color_mask, segment_single_chars, normalize_bitmap, GlyphLibrary,
    JHRW_YELLOW_RULE, JHRW_RED_RULE, JHRW_WHITE_RULE, JHRW_GREEN_RULE,
)

IMG_DIR = r"E:\DS\梦幻西游脚本函数包\地图数据\字库图片"
RULES = {
    "yellow": JHRW_YELLOW_RULE,
    "red": JHRW_RED_RULE,
    "white": JHRW_WHITE_RULE,
    "green": JHRW_GREEN_RULE,
}


def ascii_art(bitmap, target_h=18):
    bm = bitmap.astype(np.uint8)
    hh, ww = bm.shape
    scale = target_h / hh
    new_w = max(1, int(round(ww * scale)))
    ys = np.clip((np.arange(target_h) / scale).astype(int), 0, hh - 1)
    xs = np.clip((np.arange(new_w) / scale).astype(int), 0, ww - 1)
    scaled = bm[np.ix_(ys, xs)]
    return "\n".join("".join("#" if v else "." for v in row) for row in scaled)


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    only_color = sys.argv[2] if len(sys.argv) > 2 else None
    files = sorted(f for f in os.listdir(IMG_DIR) if f.endswith(".png") and "任务" in f)
    for fname in files:
        if only and only not in fname:
            continue
        print("\n" + "#" * 70)
        print(f"# 图片: {fname}")
        print("#" * 70)
        img = Image.open(os.path.join(IMG_DIR, fname)).convert("RGBA")
        arr = np.array(img)
        if arr.shape[2] == 4:
            alpha = arr[:, :, 3:4].astype(float) / 255.0
            arr = (arr[:, :, :3] * alpha).astype(np.uint8)
        for color, rule in RULES.items():
            if only_color and color != only_color:
                continue
            mask = apply_color_mask(arr, rule)
            blobs = segment_single_chars(mask)
            print(f"\n--- {color} 通道: {len(blobs)} 个单字 ---")
            for i, (x, y, w, h, crop) in enumerate(blobs):
                _b, nh = normalize_bitmap(crop, target_size=(32, 32))
                print(f"\n[{i}] @({x},{y}) {w}x{h}  hash={nh}")
                for al in ascii_art(crop, target_h=18).split("\n"):
                    print("   " + al)


if __name__ == "__main__":
    main()
