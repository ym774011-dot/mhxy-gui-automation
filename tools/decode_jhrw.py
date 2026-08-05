# -*- coding: utf-8 -*-
"""
解码每张 JHRW 任务栏截图，按颜色通道打印识别序列；
对 UNKNOWN 字块同时打印 ASCII，便于人工对照模板定标签。
"""
import sys, os
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.glyph_recognizer import (
    apply_color_mask, segment_characters, normalize_bitmap, GlyphLibrary,
    JHRW_YELLOW_RULE, JHRW_RED_RULE, JHRW_WHITE_RULE, JHRW_GREEN_RULE,
)

IMG_DIR = r"E:\DS\梦幻西游脚本函数包\地图数据\字库图片"
RULES = {
    "yellow": JHRW_YELLOW_RULE,
    "red": JHRW_RED_RULE,
    "white": JHRW_WHITE_RULE,
    "green": JHRW_GREEN_RULE,
}


def segment_multiline(mask, line_gap=2, char_gap=2):
    h, w = mask.shape
    row_has = mask.any(axis=1)
    out = []
    i = 0
    while i < h:
        if row_has[i]:
            last = i
            k = i
            while k < h:
                if row_has[k]:
                    last = k
                    k += 1
                else:
                    kk = k
                    while kk < h and not row_has[kk]:
                        kk += 1
                    if kk - k >= line_gap:
                        break
                    k = kk
            sub = mask[i:last + 1, :]
            for (x, y, cw, ch, crop) in segment_characters(sub, gap_threshold=char_gap):
                out.append((x, y + i, cw, ch, crop))
            i = last + 1
        else:
            i += 1
    return out


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
    lib = GlyphLibrary()
    files = sorted(f for f in os.listdir(IMG_DIR) if f.endswith(".png") and "任务" in f)
    for fname in files:
        print("\n" + "#" * 70)
        print(f"# 图片: {fname}")
        print("#" * 70)
        img = Image.open(os.path.join(IMG_DIR, fname)).convert("RGBA")
        arr = np.array(img)
        if arr.shape[2] == 4:
            alpha = arr[:, :, 3:4].astype(float) / 255.0
            arr = (arr[:, :, :3] * alpha).astype(np.uint8)
        for color, rule in RULES.items():
            mask = apply_color_mask(arr, rule)
            blobs = segment_multiline(mask)
            seq = []
            unknowns = []
            for (x, y, w, h, crop) in blobs:
                _bmp, nh = normalize_bitmap(crop, target_size=(32, 32))
                ch = lib.lookup(nh)
                if ch is None:
                    seq.append(f"[{nh[:6]}]")
                    unknowns.append((nh, crop, (x, y, w, h)))
                else:
                    seq.append(ch)
            print(f"\n--- {color} 序列 ({len(blobs)} 字块): {''.join(seq)}")
            for nh, crop, (x, y, w, h) in unknowns:
                print(f"  UNKNOWN hash={nh} @({x},{y},{w}x{h})")
                for al in ascii_art(crop, target_h=18).split("\n"):
                    print("    " + al)


if __name__ == "__main__":
    main()
