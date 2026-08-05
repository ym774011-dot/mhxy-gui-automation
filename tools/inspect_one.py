# -*- coding: utf-8 -*-
"""打印单张坐标图的字符切分序列（ASCII），用于核对异常 cluster。"""
import sys, os
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.glyph_recognizer import apply_color_mask, COORD_WHITE_RULE, segment_characters

IMG_DIR = r"E:\DS\梦幻西游脚本函数包\地图数据\字库图片"


def ascii_art(bitmap, target_h=16):
    bm = bitmap.astype(np.uint8)
    h, w = bm.shape
    scale = target_h / h
    new_w = max(1, int(round(w * scale)))
    ys = np.clip((np.arange(target_h) / scale).astype(int), 0, h - 1)
    xs = np.clip((np.arange(new_w) / scale).astype(int), 0, w - 1)
    scaled = bm[np.ix_(ys, xs)]
    return "\n".join("".join("#" if v else "." for v in row) for row in scaled)


def main():
    fname = sys.argv[1] if len(sys.argv) > 1 else "江南野外1.png"
    img = Image.open(os.path.join(IMG_DIR, fname)).convert("RGBA")
    arr = np.array(img)
    if arr.shape[2] == 4:
        alpha = arr[:, :, 3:4].astype(float) / 255.0
        arr = (arr[:, :, :3] * alpha).astype(np.uint8)
    mask = apply_color_mask(arr, COORD_WHITE_RULE)
    blobs = segment_characters(mask, gap_threshold=2)
    print(f"{fname}: {len(blobs)} 段")
    for i, (x, y, w, h, crop) in enumerate(blobs):
        print(f"\n--- seg[{i}] x={x} w={w} h={h} ---")
        for line in ascii_art(crop, target_h=16).split("\n"):
            print("  " + line)


if __name__ == "__main__":
    main()
