# -*- coding: utf-8 -*-
"""诊断：在 RGB 约定下测量用户面板各颜色通道的真实像素分布，用于校正 ColorMaskRule。"""
import sys
import os
import cv2
import numpy as np

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from core.glyph_recognizer import (
    apply_color_mask,
    JHRW_YELLOW_RULE, JHRW_RED_RULE, JHRW_WHITE_RULE, JHRW_GREEN_RULE,
)

YELLOW_CAND = ColorMaskRange = None  # placeholder

def stats_of(image_rgb, mask):
    if not mask.any():
        return None
    px = image_rgb[mask]
    return {
        "count": int(mask.sum()),
        "r": (int(px[:,0].min()), int(px[:,0].max()), int(px[:,0].mean())),
        "g": (int(px[:,1].min()), int(px[:,1].max()), int(px[:,1].mean())),
        "b": (int(px[:,2].min()), int(px[:,2].max()), int(px[:,2].mean())),
    }

def main():
    img_path = sys.argv[1] if len(sys.argv) > 1 else (
        r"C:\Users\Administrator\.workbuddy\clipboard-images"
        r"\clipboard-2026-08-03T13-20-02-591Z-79f5de34.png"
    )
    img = cv2.imread(img_path)
    if img is None:
        print("FAIL read", img_path); return 1
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    print(f"[INFO] size {img.shape[1]}x{img.shape[0]} (WxH), RGB convention")
    for name, rule in [
        ("yellow", JHRW_YELLOW_RULE),
        ("red", JHRW_RED_RULE),
        ("white", JHRW_WHITE_RULE),
        ("green", JHRW_GREEN_RULE),
    ]:
        mask = apply_color_mask(img, rule)
        s = stats_of(img, mask)
        print(f"  [{name}] rule={rule.exact_rgb if rule.exact_rgb else 'range r{rule.r_min}-{rule.r_max}'} "
              f"-> {s if s else 'NO PIXELS'}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
