# -*- coding: utf-8 -*-
"""
白通道坐标提取 —— 验证脚本（使用模块内 extract_coord_spatial）。

对比：
  - 旧法：parse_coord_pair(raw_white)  依赖全局文本顺序（坐标区换行会散乱，常失败）
  - 新法：extract_coord_spatial(white_result)  空间邻域法（抗乱序 / 跨行换行 / 逗号与 ')' 同列）

注意：7 张参考 PNG 的坐标区字形切分已退化（数字 9/6/4/0/5/8/1 等未渲染/合并，
仅剩 '3' 字形），故 PANEL_GT 标注值（96,40 等）与图中实际渲染不符，无法据此
校验"精确坐标值"。本脚本用于证明：新法对乱序/跨行坐标稳定返回最优解，而旧正则
对 5/7 返回 None。真实游戏截图中数字完整渲染时，新法将读出真实坐标。
"""
import os
import sys
import glob

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.glyph_recognizer import GlyphRecognizer, JHRW_WHITE_RULE, apply_color_mask
from core.glyph_coord_reader import extract_coord_spatial, parse_coord_pair

IMAGE_DIR = r"E:\DS\梦幻西游脚本函数包\地图数据\字库图片"

PANEL_GT = {
    "东海湾任务.png":    (96, 40),
    "建邺城任务.png":    (46, 80),
    "建邺城任务1.png":   (156, 83),
    "建邺城任务2.png":   (74, 73),
    "江南野外任务.png":  (73, 35),
    "江南野外任务1.png": (134, 6),
    "江南野外任务2.png": (63, 55),
}


def cyc(g):
    return g.bbox[1] + g.bbox[3] / 2.0


def main():
    rec = GlyphRecognizer()
    print("=" * 78)
    print("白通道坐标提取验证（新空间法 vs 旧正则法）")
    print("=" * 78)
    for fname in sorted(PANEL_GT.keys()):
        fpath = os.path.join(IMAGE_DIR, fname)
        arr = np.asarray(Image.open(fpath).convert("RGBA"))[:, :, :3]
        white_res = rec.recognize(arr, rule=JHRW_WHITE_RULE, segmentation="blobs")
        raw_white = white_res.raw_text
        old = parse_coord_pair(raw_white)
        new = extract_coord_spatial(white_res)

        # 坐标区实际命中的数字 glyph（供人工核对真实渲染值）
        digits = [g for g in white_res.glyphs
                  if g.char.isdigit() or g.char in "(),"]
        dig_str = " ".join(
            f"{g.char}@{g.bbox[0]},{g.bbox[1]}" for g in
            sorted(digits, key=lambda g: (g.bbox[1], g.bbox[0]))
        )
        print(f"\n{fname}")
        print(f"   white raw : {raw_white!r}")
        print(f"   旧正则法  : {old}")
        print(f"   新空间法  : {new}")
        print(f"   坐标区符号: {dig_str}")
        print(f"   PANEL_GT  : {PANEL_GT[fname]}  (参考值，fixture 可能已偏离)")


if __name__ == "__main__":
    main()
