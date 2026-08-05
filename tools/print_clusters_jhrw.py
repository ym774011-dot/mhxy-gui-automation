# -*- coding: utf-8 -*-
"""
JHRW 任务栏字模聚类报告（多行：先按空行分行，再列分字）。
对 4 种颜色分别聚类，标出哪些 hash 已在坐标库（已知），哪些是新字（需标注）。
输出到 debug_clusters/jhrw_<color>_report.txt
"""
import sys, os
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.glyph_recognizer import (
    apply_color_mask, segment_characters, normalize_bitmap,
    JHRW_YELLOW_RULE, JHRW_RED_RULE, JHRW_WHITE_RULE, JHRW_GREEN_RULE,
    GlyphLibrary,
)

IMG_DIR = r"E:\DS\梦幻西游脚本函数包\地图数据\字库图片"
OUT_DIR = r"E:\DS\mhxy-gui-automation\debug_clusters"
RULES = {
    "yellow": JHRW_YELLOW_RULE,
    "red": JHRW_RED_RULE,
    "white": JHRW_WHITE_RULE,
    "green": JHRW_GREEN_RULE,
}


def segment_multiline(mask, line_gap=2, char_gap=2):
    """先按空行切分多行，再对每行列分字。"""
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
            sub = mask[i : last + 1, :]
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
    jhrw_files = sorted(
        f for f in os.listdir(IMG_DIR) if f.endswith(".png") and "任务" in f
    )
    for color, rule in RULES.items():
        clusters = {}
        for fname in jhrw_files:
            img = Image.open(os.path.join(IMG_DIR, fname)).convert("RGBA")
            arr = np.array(img)
            if arr.shape[2] == 4:
                alpha = arr[:, :, 3:4].astype(float) / 255.0
                arr = (arr[:, :, :3] * alpha).astype(np.uint8)
            mask = apply_color_mask(arr, rule)
            for x, y, w, h, crop in segment_multiline(mask):
                _bmp, nh = normalize_bitmap(crop, target_size=(32, 32))
                clusters.setdefault(nh, {"sources": set(), "rep": crop, "n": 0})
                clusters[nh]["sources"].add(fname)
                clusters[nh]["n"] += 1

        # 排序：按代表字形平均 x（无跨图信息，用代表自身宽度近似，这里直接按 n 降序）
        ordered = sorted(clusters.items(), key=lambda kv: -kv[1]["n"])
        known_count = 0
        for v in clusters.values():
            if v["rep"] is not None:
                _b, rh = normalize_bitmap(v["rep"], target_size=(32, 32))
                if lib.lookup(rh) is not None:
                    known_count += 1
        lines = [f"颜色: {color} | 聚类数: {len(clusters)} | 已知: {known_count}"]
        lines.append("=" * 60)
        for idx, (nh, info) in enumerate(ordered):
            rep = info["rep"]
            _b, rh = normalize_bitmap(rep, target_size=(32, 32))
            known = lib.lookup(rh)
            tag = f"已知={known}" if known else "新字"
            lines.append(f"\n### [{color}][{idx:02d}] n={info['n']} {tag}")
            lines.append(f"  hash: {nh}")
            lines.append(f"  sources: {', '.join(sorted(info['sources']))}")
            for al in ascii_art(rep, target_h=18).split("\n"):
                lines.append("    " + al)

        os.makedirs(OUT_DIR, exist_ok=True)
        outp = os.path.join(OUT_DIR, f"jhrw_{color}_report.txt")
        with open(outp, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        print(f"{color}: 聚类 {len(clusters)} -> {outp}")


if __name__ == "__main__":
    main()
