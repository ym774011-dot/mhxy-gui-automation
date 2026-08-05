# -*- coding: utf-8 -*-
"""
收集器：对全部 JHRW 任务截图(4 颜色通道) + 左上角坐标截图(白色通道)
做单字切分，统计每个唯一字模(hash) 的出现次数，并打印 ASCII 供人工标注。
只处理图片像素内容，绝不引用文件名中的数字。
"""
import sys, os
import numpy as np
from PIL import Image
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.glyph_recognizer import (
    apply_color_mask, segment_single_chars, normalize_bitmap,
    JHRW_YELLOW_RULE, JHRW_RED_RULE, JHRW_WHITE_RULE, JHRW_GREEN_RULE,
    COORD_WHITE_RULE,
)

IMG_DIR = r"E:\DS\梦幻西游脚本函数包\地图数据\字库图片"

CHANNELS = [
    ("jhrw_yellow", JHRW_YELLOW_RULE),
    ("jhrw_red", JHRW_RED_RULE),
    ("jhrw_white", JHRW_WHITE_RULE),
    ("jhrw_green", JHRW_GREEN_RULE),
]
COORD_RULE = COORD_WHITE_RULE


def ascii_art(bitmap, target_h=18):
    bm = bitmap.astype(np.uint8)
    hh, ww = bm.shape
    scale = target_h / hh
    new_w = max(1, int(round(ww * scale)))
    ys = np.clip((np.arange(target_h) / scale).astype(int), 0, hh - 1)
    xs = np.clip((np.arange(new_w) / scale).astype(int), 0, ww - 1)
    scaled = bm[np.ix_(ys, xs)]
    return "\n".join("".join("#" if v else "." for v in row) for row in scaled)


def load_arr(fname):
    img = Image.open(os.path.join(IMG_DIR, fname)).convert("RGBA")
    arr = np.array(img)
    if arr.shape[2] == 4:
        alpha = arr[:, :, 3:4].astype(float) / 255.0
        arr = (arr[:, :, :3] * alpha).astype(np.uint8)
    return arr


def collect():
    # hash -> dict(count, channels, ascii, sample_bbox)
    uniq = {}
    task_files = sorted(f for f in os.listdir(IMG_DIR)
                        if f.endswith(".png") and "任务" in f)
    coord_files = sorted(f for f in os.listdir(IMG_DIR)
                         if f.endswith(".png") and "任务" not in f)

    for fname in task_files:
        arr = load_arr(fname)
        for ch_name, rule in CHANNELS:
            mask = apply_color_mask(arr, rule)
            blobs = segment_single_chars(mask)
            for (x, y, w, h, crop) in blobs:
                _b, nh = normalize_bitmap(crop, target_size=(32, 32))
                rec = uniq.setdefault(nh, {"count": 0, "channels": set(),
                                           "ascii": ascii_art(crop, 18),
                                           "bbox": (x, y, w, h)})
                rec["count"] += 1
                rec["channels"].add(ch_name)

    for fname in coord_files:
        arr = load_arr(fname)
        mask = apply_color_mask(arr, COORD_RULE)
        blobs = segment_single_chars(mask)
        for (x, y, w, h, crop) in blobs:
            _b, nh = normalize_bitmap(crop, target_size=(32, 32))
            rec = uniq.setdefault(nh, {"count": 0, "channels": set(),
                                       "ascii": ascii_art(crop, 18),
                                       "bbox": (x, y, w, h)})
            rec["count"] += 1
            rec["channels"].add("coord_white")

    return uniq


def main():
    uniq = collect()
    print(f"唯一字模总数: {len(uniq)}")
    # 按出现次数降序，再按 hash
    items = sorted(uniq.items(), key=lambda kv: (-kv[1]["count"], kv[0]))
    lines = []
    lines.append(f"唯一字模总数: {len(uniq)}\n")
    for i, (nh, rec) in enumerate(items):
        lines.append(f"\n{'='*60}")
        lines.append(f"[{i:02d}] hash={nh}")
        lines.append(f"     出现次数={rec['count']}  通道={sorted(rec['channels'])}  bbox={rec['bbox']}")
        lines.append(f"     标注: ___")  # 人工填写
        for al in rec["ascii"].split("\n"):
            lines.append(f"     {al}")
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "glyph_label_sheet.txt")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"标注表已写入: {out_path}")
    # 同时打印统计
    print("\n各通道字模数:")
    ch_count = defaultdict(int)
    for nh, rec in uniq.items():
        for c in rec["channels"]:
            ch_count[c] += 1
    for c, n in sorted(ch_count.items()):
        print(f"  {c}: {n}")


if __name__ == "__main__":
    main()
