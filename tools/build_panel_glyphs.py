"""
面板字模引导采集工具 —— 从已知文本位置对齐，自动补录黄/白通道缺失字模。

原理：
  字模库中的黄/白通道字是从「干净源图」采集的，与游戏面板渲染有像素级差异，
  导致识别时大量 UNKNOWN。本工具利用「已知文本」（从图片人工确认）做位置
  对齐标注：按 x 排序的 glyph 序列 = 已知字符串的字符序列，逐位赋值。
  一致性校验：同一 hash 在多张图中必须映射到同一字符（否则说明切分不准）。

用法：
    python tools/build_panel_glyphs.py          # 分析并输出待补录清单
    python tools/build_panel_glyphs.py --apply   # 自动写入 glyph_library.json
"""

import sys
import os
import json
import hashlib
import numpy as np
from PIL import Image
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.glyph_recognizer import (
    GlyphRecognizer,
    GlyphLibrary,
    JHRW_YELLOW_RULE,
    JHRW_WHITE_RULE,
    JHRW_RED_RULE,
    JHRW_GREEN_RULE,
    apply_color_mask,
    normalize_bitmap,
)
from core.glyph_coord_reader import (
    parse_coord_pair,
    parse_progress_text,
)

# ======================================================================
# Ground Truth —— 从图片人工确认的各通道文本
# ======================================================================

PANEL_GT = {
    # filename -> {channel: text_string}
    "东海湾任务.png": {
        "yellow": "东海湾",
        "white":  "前往东海湾(96,40)处查明",
        "red":    "初出江湖",
        "green":  "",
    },
    "建邺城任务.png": {
        "yellow": "建邺城",
        "white":  "前往建邺城(46,80)处查明山贼头目的身份",
        "red":    "初出江湖",
        "green":  "山贼头目",
    },
    "建邺城任务1.png": {
        "yellow": "建邺城",
        "white":  "前往建邺城(156,83)处查明蟊贼的身份",
        "red":    "初出江湖",
        "green":  "蟊贼",
    },
    "建邺城任务2.png": {
        "yellow": "建邺城",
        "white":  "前往建邺城(74,73)处查明",
        "red":    "初出江湖",
        "green":  "",
    },
    "江南野外任务.png": {
        "yellow": "江南野外",
        "white":  "前往江南野外(73,35)处查明江南大盗的身份",
        "red":    "初出江湖",
        "green":  "江南大盗",
    },
    "江南野外任务1.png": {
        "yellow": "江南野外",
        "white":  "前往江南野外(134,6)处查明江南大盗的身份",
        "red":    "初出江湖",
        "green":  "江南大盗",
    },
    "江南野外任务2.png": {
        "yellow": "江南野外",
        "white":  "前往江南野外(63,55)处查明",
        "red":    "初出江湖",
        "green":  "",
    },
}

IMAGE_DIR = r"E:\DS\梦幻西游脚本函数包\地图数据\字库图片"
LIB_PATH = os.path.join(
    os.path.dirname(__file__), "..", "data", "glyph_library.json"
)


def extract_glyph_hashes(image_rgb, rule, segmentation="single"):
    """用 recognize() 管线提取每个 glyph 的归一化 hash 和 bbox。"""
    rec = GlyphRecognizer()
    result = rec.recognize(image_rgb, rule=rule, segmentation=segmentation)
    hashes = []
    for g in result.glyphs:
        hashes.append({
            "hash": g.normalized_hash,
            "char": g.char,
            "bbox": g.bbox,
            "x": g.bbox[0],
            "w": g.bbox[2],
            "h": g.bbox[3],
        })
    return hashes, result


def align_and_label(hashes, known_text):
    """
    位置对齐：将 x 排序的 glyph 序列映射到已知字符串。

    :return: {hash: char} 映射表，以及未对齐的 hash 列表
    """
    sorted_h = sorted(hashes, key=lambda h: h["x"])
    mapping = {}
    unmatched = []

    n_glyphs = len(sorted_h)
    n_chars = len(known_text)

    if n_glyphs != n_chars:
        # 尝试宽松匹配：跳过过小的碎片（可能是噪声）
        filtered = [h for h in sorted_h if h["w"] >= 4 and h["h"] >= 8]
        if len(filtered) == n_chars:
            sorted_h = filtered
            n_glyphs = len(filtered)

    if n_glyphs == n_chars:
        for i, h in enumerate(sorted_h):
            mapping[h["hash"]] = known_text[i]
    else:
        # 无法精确对齐，返回所有为未匹配
        for h in sorted_h:
            unmatched.append(h)

    return mapping, unmatched


def main():
    apply_mode = "--apply" in sys.argv

    rec = GlyphRecognizer()
    lib = rec.library

    # 收集所有候选映射（跨图一致性检查）
    # {channel: {hash: set_of_chars_seen}}
    candidate_maps = defaultdict(lambda: defaultdict(set))
    # {channel: {hash: best_char}}  最终确定的新条目
    new_entries = {}

    print("=" * 70)
    print("面板字模引导采集工具")
    print("=" * 70)

    for fname, gt in PANEL_GT.items():
        fpath = os.path.join(IMAGE_DIR, fname)
        if not os.path.exists(fpath):
            print(f"[SKIP] {fname} 不存在")
            continue

        arr = np.asarray(Image.open(fpath).convert("RGBA"))[:, :, :3]

        print(f"\n--- {fname} ({arr.shape[1]}x{arr.shape[0]}) ---")

        for channel in ["yellow", "white"]:
            gt_text = gt.get(channel, "").strip()
            if not gt_text:
                continue

            rule_map = {
                "yellow": JHRW_YELLOW_RULE,
                "white": JHRW_WHITE_RULE,
                "red": JHRW_RED_RULE,
                "green": JHRW_GREEN_RULE,
            }
            rule = rule_map[channel]

            # 测试多种切分模式，选最接近已知文本长度的
            best_seg = None
            best_diff = 999
            best_hashes = None
            best_result = None

            for seg in ["single", "columns", "blobs"]:
                try:
                    hashes, result = extract_glyph_hashes(arr, rule, seg)
                    n_known = len(gt_text)
                    diff = abs(len(hashes) - n_known)
                    if diff < best_diff:
                        best_diff = diff
                        best_seg = seg
                        best_hashes = hashes
                        best_result = result
                except Exception as e:
                    continue

            if best_hashes is None:
                print(f"  [{channel}] 所有模式均失败")
                continue

            mapping, unmatched = align_and_label(best_hashes, gt_text)

            # 统计
            n_matched = sum(1 for h in best_hashes if h["hash"] in mapping)
            n_unknown = sum(1 for h in best_hashes if h["char"] == "UNKNOWN")

            print(
                f"  [{channel}] seg={best_seg:8s} "
                f"glyphs={len(best_hashes):2d} "
                f"known={len(gt_text):2d} "
                f"aligned={n_matched:2d} "
                f"unknown={n_unknown:2d}"
            )

            # 记录候选映射
            for hsh, ch in mapping.items():
                candidate_maps[channel][hsh].add(ch)

            # 显示未匹配详情
            if unmatched:
                print(f"    [!] 未对齐 {len(unmatched)} 个 glyph:")
                for h in unmatched[:5]:
                    print(
                        f"      x={h['x']:3d} w={h['w']:2d} h={h['h']:2d} "
                        f"hash={h['hash'][:12]}.. cur={h['char']!r}"
                    )

            # 显示已匹配但库中缺失的
            missing_from_lib = [
                (hsh, ch)
                for hsh, ch in mapping.items()
                if lib.lookup(hsh) is None
            ]
            if missing_from_lib:
                print(f"    [*] 库中缺失 {len(missing_from_lib)} 条:")
                for hsh, ch in missing_from_lib:
                    print(f"       {hsh[:16]} -> {ch!r}")

    # ==================================================================
    # 一致性检查 & 确定新条目
    # ==================================================================
    print("\n" + "=" * 70)
    print("一致性检查 & 新条目汇总")
    print("=" * 70)

    total_new = 0
    conflicts = []

    for channel in ["yellow", "white"]:
        cmap = candidate_maps[channel]
        if not cmap:
            continue

        print(f"\n[{channel}] 候选 {len(cmap)} 个唯一 hash:")

        for hss, chars_set in cmap.items():
            existing = lib.lookup(hss)
            if existing:
                # 已在库中，验证一致性
                if existing not in chars_set:
                    print(
                        f"  CONFLICT: {hss[:16]} 库中={existing!r} "
                        f"但本次标注为 {chars_set}"
                    )
                    conflicts.append((channel, hss, existing, chars_set))
                continue

            if len(chars_set) == 1:
                ch = next(iter(chars_set))
                new_entries[hss] = ch
                total_new += 1
                print(f"  NEW     {hss[:16]} -> {ch!r}")
            else:
                print(
                    f"  AMBIGUOUS {hss[:16]} -> {chars_set} "
                    f"(同一 hash 在不同图中被标为不同字符)"
                )
                conflicts.append(("ambiguous", hss, None, chars_set))

    # ==================================================================
    # 应用或报告
    # ==================================================================
    print(f"\n{'='*70}")
    print(f"总计可新增 {total_new} 条字模，冲突 {len(conflicts)} 处")
    print(f"{'='*70}")

    if conflicts:
        print("\n⚠️ 冲突列表（需手动处理）：")
        for c in conflicts:
            print(f"  {c}")

    if apply_mode and new_entries:
        # 批量写入（逐条 add，最后统一 save）
        for hss, ch in new_entries.items():
            lib.add(hss, ch, autosave=False)
        lib.save()
        print(f"\n✅ 已写入 {len(new_entries)} 条新字模到 {LIB_PATH}")
        print(f"   当前字库共 {lib.size} 条")
    elif not apply_mode and new_entries:
        print(f"\n💡 提示: 加 --apply 参数可将以上 {total_new} 条写入字库")


if __name__ == "__main__":
    main()
