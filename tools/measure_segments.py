# -*- coding: utf-8 -*-
"""测量坐标区图像的「字符列间隙」，为按列分字选择阈值。"""
import sys, os
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.glyph_recognizer import apply_color_mask, COORD_WHITE_RULE

IMG_DIR = r"E:\DS\梦幻西游脚本函数包\地图数据\字库图片"

# 期望字符数（地图名 + "[" + X数字 + "," + Y数字 + "]"）
EXPECTED = {
    "东海湾.png": 10,     # 东1海1湾1 +[+7093(4)+,+]
    "建邺城.png": 11,
    "建邺城1.png": 11,
    "江南野外.png": 12,
    "江南野外1.png": 11,
    "江南野外2.png": 12,
    "江南野外3.png": 12,
    "江南野外4.png": 12,
    "长安城.png": 12,
    "长安城1.png": 12,
}


def col_segment_count(mask, gap_threshold):
    col_has = mask.any(axis=0)
    ncols = mask.shape[1]
    segs = 0
    i = 0
    while i < ncols:
        if col_has[i]:
            last_ink = i
            k = i
            while k < ncols:
                if col_has[k]:
                    last_ink = k
                    k += 1
                else:
                    kk = k
                    while kk < ncols and not col_has[kk]:
                        kk += 1
                    if kk - k >= gap_threshold:
                        break
                    k = kk
            segs += 1
            i = last_ink + 1
        else:
            i += 1
    return segs


def main():
    coord_files = sorted(
        f for f in os.listdir(IMG_DIR) if f.endswith(".png") and "任务" not in f
    )
    print(f"{'file':14s} {'exp':>3s}  " + "  ".join(f"gap{g}" for g in (1, 2, 3, 4)))
    for fname in coord_files:
        img = Image.open(os.path.join(IMG_DIR, fname)).convert("RGBA")
        arr = np.array(img)
        if arr.shape[2] == 4:
            alpha = arr[:, :, 3:4].astype(float) / 255.0
            arr = (arr[:, :, :3] * alpha).astype(np.uint8)
        mask = apply_color_mask(arr, COORD_WHITE_RULE)
        counts = [col_segment_count(mask, g) for g in (1, 2, 3, 4)]
        exp = EXPECTED.get(fname, -1)
        print(f"{fname:14s} {exp:3d}   " + "  ".join(f"{c:4d}" for c in counts))


if __name__ == "__main__":
    main()
