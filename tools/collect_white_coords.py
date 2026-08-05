"""定向采集白通道坐标字模 —— 宽度模式匹配定位 (x,y) 区域。"""
import sys, os, re
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.glyph_recognizer import GlyphRecognizer, JHRW_WHITE_RULE

D = r"E:\DS\梦幻西游脚本函数包\地图数据\字库图片"
rec = GlyphRecognizer()
lib = rec.library

COORD_GT = {
    "东海湾任务.png":     (96, 40),
    "建邺城任务.png":     (46, 80),
    "建邺城任务1.png":   (156, 83),
    "建邺城任务2.png":    (74, 73),
    "江南野外任务.png":   (73, 35),
    "江南野外任务1.png":  (134, 6),
    "江南野外任务2.png":   (63, 55),
}


def find_coord_pattern(glyphs, expected_coord):
    """通过宽度特征 '(N,N)' 定位坐标 blob 区域。"""
    sorted_g = sorted(glyphs, key=lambda g: g.bbox[0])
    n = len(sorted_g)
    expected_str = f"({expected_coord[0]},{expected_coord[1]})"
    pat_len = len(expected_str)

    best_idx = -1
    best_score = 0

    for start in range(n):
        region = sorted_g[start : start + pat_len]
        if len(region) < pat_len:
            continue

        widths = [g.bbox[2] for g in region]

        score = 0
        if widths[0] <= 5:
            score += 2  # '(' 窄
        if widths[-1] <= 5:
            score += 2  # ')' 窄
        has_comma = any(w <= 3 for w in widths[1:-1])
        if has_comma:
            score += 3  # ',' 很窄
        digit_like = sum(1 for w in widths[1:-1] if 4 <= w <= 10)
        score += digit_like

        if score > best_score:
            best_score = score
            best_idx = start

    if best_score < 6:
        return None, None

    return sorted_g[best_idx : best_idx + pat_len], expected_str


def main():
    print("=== 宽度模式匹配采集坐标字模 ===")
    all_new = {}

    for f, (ex, ey) in COORD_GT.items():
        fpath = os.path.join(D, f)
        if not os.path.exists(fpath):
            continue
        arr = np.asarray(Image.open(fpath).convert("RGBA"))[:, :, :3]
        r = rec.recognize(arr, rule=JHRW_WHITE_RULE, segmentation="single")

        region, expected_str = find_coord_pattern(r.glyphs, (ex, ey))

        new_ent = {}
        if region:
            for i, g in enumerate(region):
                h = g.normalized_hash
                ch = expected_str[i]
                if lib.lookup(h) is None:
                    new_ent[h] = ch
                    all_new[h] = ch

        raw = r.raw_text.strip()
        m = re.search(r"(\d+)\s*[,，]\s*(\d+)", raw)
        coord = f"({m.group(1)},{m.group(2)})" if m else "FAIL"
        found = "FOUND" if region else "MISS"
        print(f"{f:22s} {found:4s} new={len(new_ent):2d} raw_coord={coord:12s}")

    # 一致性检查 & 写入
    print("\n新条目:")
    final = {}
    for h, ch in all_new.items():
        if lib.lookup(h) is not None:
            continue
        final[h] = ch
        tag = " [COORD]" if ch in "0123456789()," else ""
        print(f"  {h[:20]}.. -> {ch!r}{tag}")

    if final:
        for h, ch in final.items():
            lib.add(h, ch, autosave=False)
        lib.save()
        digits = set(v for v in final.values() if v in "0123456789")
        print(f"\nWrote {len(final)} glyphs (digits: {sorted(digits)}). Library: {lib.size}")
    else:
        print("\nNo new glyphs to add.")


if __name__ == "__main__":
    main()
