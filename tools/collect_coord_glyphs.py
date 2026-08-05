# -*- coding: utf-8 -*-
"""
采集「左上角坐标区」单字字模（仅 东海湾/建邺城/江南野外 三张地图名 + 0-9 数字）。
每个独立汉字/数字/标点 = 一条；文件名数字只是图片区分，不进字库。
输出：tools/coord_glyph_sheet.txt (ASCII 标注表) + tools/coord_glyph_collection.json
"""
from __future__ import annotations
import sys, os
import json
from collections import defaultdict
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.glyph_recognizer import (
    COORD_WHITE_RULE, apply_color_mask, segment_single_chars, normalize_bitmap
)

IMG_DIR = r"E:/DS/梦幻西游脚本函数包/地图数据/字库图片"
SHEET = os.path.join(os.path.dirname(__file__), "coord_glyph_sheet.txt")
COLLECTION = os.path.join(os.path.dirname(__file__), "coord_glyph_collection.json")

# 仅取这 3 个地图的坐标截图（含文件名数字变体，只作不同坐标样本用）
TARGET_FILES = [
    "东海湾.png",
    "建邺城.png", "建邺城1.png",
    "江南野外.png", "江南野外1.png", "江南野外2.png",
    "江南野外3.png", "江南野外4.png",
]


def load_rgb(path: str) -> np.ndarray:
    im = Image.open(path).convert("RGBA")
    arr = np.asarray(im)
    if arr.shape[2] == 4:
        arr = arr[:, :, :3]
    return arr


def ascii_art(crop: np.ndarray, w: int = 40) -> str:
    h, cw = crop.shape
    lines = []
    for y in range(h):
        row = "".join("#" if crop[y, x] else "." for x in range(cw))
        lines.append(row)
    return "\n".join(lines)


def main():
    seen = {}                       # hash -> {"crop": first crop, "files": set, "count": n}
    order = []
    for fname in TARGET_FILES:
        path = os.path.join(IMG_DIR, fname)
        if not os.path.exists(path):
            print("MISSING", fname)
            continue
        arr = load_rgb(path)
        mask = apply_color_mask(arr, COORD_WHITE_RULE)
        blobs = segment_single_chars(mask, sort_by="x_asc")
        for (x, y, bw, bh, crop) in blobs:
            _bmp, hx = normalize_bitmap(crop, target_size=(32, 32))
            if hx in seen:
                seen[hx]["count"] += 1
                seen[hx]["files"].add(fname)
            else:
                seen[hx] = {"crop": crop, "files": {fname}, "count": 1}
                order.append(hx)

    print(f"唯一字模数: {len(order)}")
    with open(SHEET, "w", encoding="utf-8") as f:
        f.write(f"# 单字字模标注表 (共 {len(order)} 个唯一 hash)\n")
        f.write("# 标注方法: 在每段的 HASH 后写上 字符 (如 `HASH: 建`)\n\n")
        for i, hx in enumerate(order):
            info = seen[hx]
            f.write(f"=== [{i}] hash={hx}  count={info['count']}  files={sorted(info['files'])}\n")
            f.write(ascii_art(info["crop"]))
            f.write("\n\n")

    # 保存采集（不含 crop 数组，省空间；只存 hash+统计，标注后再合并）
    coll = {hx: {"count": seen[hx]["count"], "files": sorted(seen[hx]["files"])}
            for hx in order}
    json.dump(coll, open(COLLECTION, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"已写出: {SHEET}\n{COLLECTION}")


if __name__ == "__main__":
    main()
