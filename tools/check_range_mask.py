import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cv2
import numpy as np
from PIL import Image
from core.glyph_recognizer import apply_color_mask, ColorMaskRule

JHRW_WHITE_RANGE = ColorMaskRule(
    name="jhrw_white_range",
    r_min=200, r_max=255,
    g_min=200, g_max=255,
    b_min=180, b_max=255,
)

p = r"C:\Users\Administrator\.workbuddy\clipboard-images\clipboard-2026-08-03T13-20-02-591Z-79f5de34.png"
img_bgr = cv2.imread(p)
img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)

mask = apply_color_mask(img_rgb, JHRW_WHITE_RANGE)
print("mask sum", int(mask.sum()))

# Check coord pixels
for y in range(70, 78):
    for x in range(105, 155):
        r, g, b = img_rgb[y, x]
        in_mask = mask[y, x]
        if r > 180 or g > 180 or b > 180:
            print(f"({x},{y}) RGB=({r},{g},{b}) in_mask={in_mask}")
