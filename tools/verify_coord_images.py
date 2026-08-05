# -*- coding: utf-8 -*-
"""用新建字模库解码 10 张坐标图，与已知正确值比对。"""
import sys, os
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.glyph_recognizer import apply_color_mask, COORD_WHITE_RULE, segment_characters, normalize_bitmap, GlyphRecognizer
from core.glyph_coord_reader import parse_location_text

IMG_DIR = r"E:\DS\梦幻西游脚本函数包\地图数据\字库图片"

EXPECTED = {
    "东海湾.png": ("东海湾", 70, 93),
    "建邺城.png": ("建邺城", 65, 112),
    "建邺城1.png": ("建邺城", 153, 82),
    "江南野外.png": ("江南野外", 109, 20),
    "江南野外1.png": ("江南野外", 97, 23),
    "江南野外2.png": ("江南野外", 116, 18),
    "江南野外3.png": ("江南野外", 123, 24),
    "江南野外4.png": ("江南野外", 135, 16),
    "长安城.png": ("长安城", 508, 275),
    "长安城1.png": ("长安城", 241, 101),
}


def main():
    rec = GlyphRecognizer()
    print(f"字模库大小: {rec.library.size}\n")
    ok = 0
    for fname in sorted(EXPECTED):
        img = Image.open(os.path.join(IMG_DIR, fname)).convert("RGBA")
        arr = np.array(img)
        if arr.shape[2] == 4:
            alpha = arr[:, :, 3:4].astype(float) / 255.0
            arr = (arr[:, :, :3] * alpha).astype(np.uint8)
        mask = apply_color_mask(arr, COORD_WHITE_RULE)
        blobs = segment_characters(mask, gap_threshold=2)
        chars = []
        unknowns = []
        for x, y, w, h, crop in blobs:
            _bmp, nh = normalize_bitmap(crop, target_size=(32, 32))
            ch = rec.library.lookup(nh)
            if ch:
                chars.append(ch)
            else:
                chars.append("?")
                unknowns.append(nh[:8])
        raw = "".join(chars)
        loc = parse_location_text(raw)
        exp_map, exp_x, exp_y = EXPECTED[fname]
        if loc and loc.get("map") == exp_map and loc.get("x") == exp_x and loc.get("y") == exp_y:
            status = "✅ PASS"
            ok += 1
            detail = f"→ {loc['map']}[{loc['x']},{loc['y']}]"
        else:
            status = "❌ FAIL"
            got = f"{loc}" if loc else "None"
            detail = f"期望 {exp_map}[{exp_x},{exp_y}] | 实得 {got}"
        print(f"{status} {fname:14s} raw='{raw}' {detail}")
        if unknowns:
            print(f"       unknown hashes: {unknowns}")
    print(f"\n结果: {ok}/{len(EXPECTED)} 通过")


if __name__ == "__main__":
    main()
