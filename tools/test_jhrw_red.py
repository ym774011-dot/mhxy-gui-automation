# -*- coding: utf-8 -*-
"""直接对 JHRW 任务截图裁剪 ROI 后跑识别，验证红通道单字化效果。"""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from PIL import Image

from core.glyph_coord_reader import JHRWGlyphReader, JHRW_ROI
from core.glyph_coord_reader import parse_coord_pair, parse_progress_text
from core.glyph_recognizer import (
    GlyphRecognizer, JHRW_YELLOW_RULE, JHRW_RED_RULE,
    JHRW_WHITE_RULE, JHRW_GREEN_RULE,
)

D = r"E:\DS\梦幻西游脚本函数包\地图数据\字库图片"
rec = GlyphRecognizer()


def rec_channel(arr, rule, seg):
    return rec.recognize(arr, rule=rule, segmentation=seg).raw_text.strip()


def main():
    for f in sorted(os.listdir(D)):
        if "任务" not in f or not f.endswith(".png"):
            continue
        arr = np.asarray(Image.open(os.path.join(D, f)).convert("RGBA"))[:, :, :3]
        crop = arr  # 字库图片已是面板裁剪图，直接用整图
        yellow = rec_channel(crop, JHRW_YELLOW_RULE, "blobs")
        red = rec_channel(crop, JHRW_RED_RULE, "single")
        white = rec_channel(crop, JHRW_WHITE_RULE, "blobs")
        green = rec_channel(crop, JHRW_GREEN_RULE, "blobs")
        quest = "初出江湖" if ("初" in red and "出" in red) else ""
        prog = parse_progress_text(red)
        coord = parse_coord_pair(white)
        # 统计 red 通道 unknown
        rres = rec.recognize(crop, rule=JHRW_RED_RULE, segmentation="single")
        print(f"{f:16} quest={quest!r} loc={yellow!r} coord={coord} "
              f"progress={prog} red_unk={rres.unknown_count}")
        print(f"    red='{red}'")


if __name__ == "__main__":
    main()
