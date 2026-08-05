# -*- coding: utf-8 -*-
"""
把坐标区所有字模聚类，并将每个聚类的代表字形以 ASCII 网格打印到文件，
供人工标注（Read 工具无法直接显示图片，故用 ASCII 文本替代）。

输出：
    debug_clusters/cluster_report.txt   （完整报告，含 ASCII 网格）
    stdout 仅打印统计摘要。
"""
import sys
import os
import hashlib
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.glyph_recognizer import (
    apply_color_mask,
    COORD_WHITE_RULE,
    segment_characters,
    normalize_bitmap,
)

IMG_DIR = r"E:\DS\梦幻西游脚本函数包\地图数据\字库图片"
OUT_TXT = r"E:\DS\mhxy-gui-automation\debug_clusters\cluster_report.txt"

# 期望文本（用于核对；地图名 = 文件名去掉末尾数字与扩展名）
EXPECTED = {
    "东海湾.png": "东海湾[70,93]",
    "建邺城.png": "建邺城[65,112]",
    "建邺城1.png": "建邺城[153,82]",
    "江南野外.png": "江南野外[109,20]",
    "江南野外1.png": "江南野外[97,23]",
    "江南野外2.png": "江南野外[116,18]",
    "江南野外3.png": "江南野外[123,24]",
    "江南野外4.png": "江南野外[135,16]",
    "长安城.png": "长安城[508,275]",
    "长安城1.png": "长安城[241,101]",
}


def ascii_art(bitmap, target_h=22):
    """把二值位图缩放为 ASCII 网格（'#'=白, '.'=黑）。"""
    bm = bitmap.astype(np.uint8)
    h, w = bm.shape
    if h == 0 or w == 0:
        return "(empty)"
    scale = target_h / h
    new_w = max(1, int(round(w * scale)))
    new_h = target_h
    ys = np.clip((np.arange(new_h) / scale).astype(int), 0, h - 1)
    xs = np.clip((np.arange(new_w) / scale).astype(int), 0, w - 1)
    scaled = bm[np.ix_(ys, xs)]
    lines = []
    for row in scaled:
        lines.append("".join("#" if v else "." for v in row))
    return "\n".join(lines)


def main():
    coord_files = sorted(
        f for f in os.listdir(IMG_DIR) if f.endswith(".png") and "任务" not in f
    )

    all_glyphs = []
    for fname in coord_files:
        img = Image.open(os.path.join(IMG_DIR, fname)).convert("RGBA")
        arr = np.array(img)
        if arr.shape[2] == 4:
            alpha = arr[:, :, 3:4].astype(float) / 255.0
            arr = (arr[:, :, :3] * alpha).astype(np.uint8)
        mask = apply_color_mask(arr, COORD_WHITE_RULE)
        blobs = segment_characters(mask, gap_threshold=2)
        iw = arr.shape[1]
        for x, y, w, h, crop in blobs:
            _bmp, norm_hash = normalize_bitmap(crop, target_size=(32, 32))
            # 原生精确 hash（仅用于诊断）
            padded = np.zeros((crop.shape[0] + 2, crop.shape[1] + 2), dtype=np.uint8)
            padded[1:-1, 1:-1] = crop.astype(np.uint8)
            exact_hash = hashlib.md5(padded.tobytes()).hexdigest()
            all_glyphs.append(
                {
                    "norm_hash": norm_hash,
                    "exact_hash": exact_hash,
                    "bitmap": crop,
                    "bbox": (x, y, w, h),
                    "x_frac": (x + w / 2) / iw,
                    "source": fname,
                }
            )

    clusters = {}
    for g in all_glyphs:
        clusters.setdefault(g["norm_hash"], []).append(g)

    # 按平均 x 位置（左→右）排序，便于按字符位置推断
    def sort_key(item):
        nh, members = item
        avg_x = sum(m["x_frac"] for m in members) / len(members)
        return avg_x

    ordered = sorted(clusters.items(), key=sort_key)

    lines = []
    lines.append(f"总字模: {len(all_glyphs)} | 聚类: {len(clusters)}")
    lines.append("排序: 按平均 x 位置（左→右）")
    lines.append("=" * 70)

    for i, (nh, members) in enumerate(ordered):
        sources = sorted(set(m["source"] for m in members))
        # bbox 尺寸统计
        ws = [m["bbox"][2] for m in members]
        hs = [m["bbox"][3] for m in members]
        avg_x = sum(m["x_frac"] for m in members) / len(members)
        wstats = f"w[{min(ws)}~{int(sum(ws)/len(ws))}~{max(ws)}]"
        hstats = f"h[{min(hs)}~{int(sum(hs)/len(hs))}~{max(hs)}]"
        rep = members[0]["bitmap"]
        lines.append("")
        lines.append(f"### cluster[{i:02d}]  n={len(members)}  x_frac={avg_x:.3f}")
        lines.append(f"  norm_hash: {nh}")
        lines.append(f"  sizes: {wstats} {hstats}")
        lines.append(f"  sources({len(sources)}): {', '.join(sources)}")
        lines.append("  ASCII (rep, ~22 tall):")
        for al in ascii_art(rep, target_h=22).split("\n"):
            lines.append("    " + al)

    os.makedirs(os.path.dirname(OUT_TXT), exist_ok=True)
    with open(OUT_TXT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"总字模: {len(all_glyphs)} | 聚类: {len(clusters)}")
    print(f"报告已写入: {OUT_TXT}")


if __name__ == "__main__":
    main()
