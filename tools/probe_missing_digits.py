# -*- coding: utf-8 -*-
"""从 3 个地图的 JHRW 任务截图中，补采尚未收录的字模（主要找缺失的数字 3）。
只打印在已有 coord_glyph_collection.json 中不存在的 hash，减少人工标注量。
"""
from __future__ import annotations
import sys, os, json
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.glyph_recognizer import (
    JHRW_YELLOW_RULE, JHRW_WHITE_RULE, apply_color_mask,
    segment_single_chars, normalize_bitmap,
)

IMG_DIR = r"E:/DS/梦幻西游脚本函数包/地图数据/字库图片"
COLL = os.path.join(os.path.dirname(__file__), "coord_glyph_collection.json")

# 仅 3 个地图的 JHRW 任务图（黄色=地图名+坐标, 白色=指令含坐标数字）
TASK_FILES = [
    "东海湾任务.png",
    "建邺城任务.png", "建邺城任务1.png", "建邺城任务2.png",
    "江南野外任务.png", "江南野外任务1.png", "江南野外任务2.png",
]


def load_rgb(path):
    im = Image.open(path).convert("RGBA")
    arr = np.asarray(im)
    return arr[:, :, :3]


def ascii_art(crop):
    h, w = crop.shape
    return "\n".join("".join("#" if crop[y, x] else "." for x in range(w)) for y in range(h))


def main():
    known = set(json.load(open(COLL, encoding="utf-8")).keys())
    rules = {"yellow": JHRW_YELLOW_RULE, "white": JHRW_WHITE_RULE}
    new = {}
    for fname in TASK_FILES:
        path = os.path.join(IMG_DIR, fname)
        if not os.path.exists(path):
            continue
        arr = load_rgb(path)
        for rname, rule in rules.items():
            mask = apply_color_mask(arr, rule)
            for (x, y, bw, bh, crop) in segment_single_chars(mask, sort_by="x_asc"):
                _b, hx = normalize_bitmap(crop, target_size=(32, 32))
                if hx not in known and hx not in new:
                    new[hx] = (crop, fname, rname)
    print(f"新字模数(不在 coord 库): {len(new)}")
    for i, (hx, (crop, fname, rname)) in enumerate(new.items()):
        print(f"\n=== NEW[{i}] hash={hx}  src={fname}/{rname}")
        print(ascii_art(crop))


if __name__ == "__main__":
    main()
