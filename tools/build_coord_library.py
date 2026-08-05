# -*- coding: utf-8 -*-
"""
用已标注的 28 个聚类（norm_hash -> 字符）重建坐标区字模库 glyph_library.json。

重建策略：重新对 10 张坐标图做「列分字 + 32x32 归一化」得到聚类，
再用本文件里的 LABEL 表把每个聚类的 norm_hash 映射到字符，写入字模库。
若某个聚类在 LABEL 中找不到，则报警（说明聚类结果与标注不一致）。
"""
import sys, os, json
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.glyph_recognizer import apply_color_mask, COORD_WHITE_RULE, segment_characters, normalize_bitmap
from core.glyph_recognizer import GlyphLibrary

IMG_DIR = r"E:\DS\梦幻西游脚本函数包\地图数据\字库图片"
LIB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "glyph_library.json")

# 标注结果（来自 cluster_report.txt 的逐字核对 + 已知坐标值交叉验证）
LABEL = {
    "fd0c28249705b929e18a3a3b5c347dba": "江",
    "6f45100a1bcdbba97a3f3987808a42c9": "东",
    "44d920538290a30f358bf9fed13fb10e": "长",
    "3a0b2cc15f97ef0e827a2eca122c1b7f": "建",
    "1b90a6bdab429ff7975653163b514e75": "南",
    "21996a0c0e003dde31f33b81a6c84f81": "安",
    "f0201c7159d23e8ed35a64384329ef76": "海",
    "275b9df559090a40676bb3996451b6af": "邺",
    "fe06c20923550af8c7831f4a914c727c": "野",
    "0119102f486f94cbb5883b6aeb5b060f": "城",
    "0cdcd0dfe8a436143c8124d2d06a52ae": "城",
    "f8733404368ec65072a672ec16f722a8": "湾",
    "79a3bdfbaab613bac67fd689eb95fa80": "外",
    "cbb8f95764aa2eb24bbd5e170c2ba730": "[",
    "a62df9c6a1798b968d91e2732896609d": "[",
    "da8455f596482070f141bb0839edd635": "[",
    "37cce802c6273aada6316ed878f16350": "5",
    "1c7c2ff47987ea60bfc747125b618c87": "1",
    "03e299bb8178e9f43080699c4ece10d3": "7",
    "7ef67c3fc4c5da2a3ec68aa60c618e87": "6",
    "b77bfd68a5d1790d61dfd6e4672f406a": "9",
    "ecfe0b253c927302d5ea1bd37f1fbbb7": "0",
    "3e993af197522ff3daa9469f523ae0ea": "4",
    "06eb740d3623ea4adb42948903839881": ",",
    "dab442bb635a6c82023490c659fe2add": "3",
    "8264608566e95ae84195635d9ff9d950": "2",
    "d2b76b22f41ba49d3d8acd72cf968529": "8",
    "9871d9bcb91067b6407e70498fd8dcfb": "]",
}


def main():
    coord_files = sorted(
        f for f in os.listdir(IMG_DIR) if f.endswith(".png") and "任务" not in f
    )
    clusters = {}
    for fname in coord_files:
        img = Image.open(os.path.join(IMG_DIR, fname)).convert("RGBA")
        arr = np.array(img)
        if arr.shape[2] == 4:
            alpha = arr[:, :, 3:4].astype(float) / 255.0
            arr = (arr[:, :, :3] * alpha).astype(np.uint8)
        mask = apply_color_mask(arr, COORD_WHITE_RULE)
        for x, y, w, h, crop in segment_characters(mask, gap_threshold=2):
            _bmp, nh = normalize_bitmap(crop, target_size=(32, 32))
            clusters.setdefault(nh, set()).add(fname)

    print(f"聚类总数: {len(clusters)} | LABEL 条目: {len(LABEL)}")

    entries = {}
    unlabeled = []
    for nh, sources in clusters.items():
        if nh in LABEL:
            entries[nh] = LABEL[nh]
        else:
            unlabeled.append((nh, sorted(sources)))

    if unlabeled:
        print(f"\n⚠️ 未标注聚类 {len(unlabeled)} 个（需补标）:")
        for nh, src in unlabeled:
            print(f"  {nh}  sources={src}")

    # 反向检查：LABEL 里有没有用不到的 key
    unused = set(LABEL) - set(clusters)
    if unused:
        print(f"\n⚠️ LABEL 中未被任何聚类命中的 key: {len(unused)}")
        for k in unused:
            print(f"  {k} -> {LABEL[k]}")

    if unlabeled or unused:
        print("\n存在不一致，已中止写入。请修正 LABEL 后重试。")
        sys.exit(1)

    # 写出字模库（覆盖式重建）
    lib = GlyphLibrary(LIB_PATH)
    # 清空旧条目
    lib._entries = {}
    lib._reverse = {}
    for nh, ch in entries.items():
        lib.add(nh, ch, autosave=False)
    lib.metadata = {
        "created": __import__("time").strftime("%Y-%m-%d %H:%M:%S"),
        "entry_count": len(entries),
        "note": "坐标区字模库：列分字 + 32x32 归一化；含多地图名/数字/标点",
    }
    lib.save()
    print(f"\n✅ 字模库已写入: {LIB_PATH}")
    print(f"   条目数: {len(entries)}")


if __name__ == "__main__":
    main()
