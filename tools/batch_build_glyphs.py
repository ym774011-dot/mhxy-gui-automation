"""
批量字模库构建工具
===================
读取 字库图片/ 目录下所有截图，用字模引擎切字，收集未知字模，
导出位图供标注，支持交互式标注入库。

用法:
  python tools/batch_build_glyphs.py scan    # 扫描所有图片，导出未知字模
  python tools/batch_build_glyphs.py label    # 交互式标注（逐张图确认文本）
  python tools/batch_build_glyphs.py build    # 一键扫描+自动标注+入库
"""

import sys
import os
import json
import glob
import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
from PIL import Image

from core.glyph_recognizer import (
    GlyphRecognizer,
    GlyphLibrary,
    Glyph,
    RecognitionResult,
    COORD_WHITE_RULE,
    JHRW_YELLOW_RULE,
    JHRW_RED_RULE,
    JHRW_WHITE_RULE,
    JHRW_GREEN_RULE,
)

# =====================================================================
# 配置
# =====================================================================

GLYPH_IMAGE_DIR = Path(r"E:\DS\梦幻西游脚本函数包\地图数据\字库图片")
EXPORT_DIR = PROJECT_ROOT / "debug_batch_glyphs"
GLYPH_LIB_PATH = PROJECT_ROOT / "data" / "glyph_library.json"

# 坐标区图片特征：高度 <= 30，文件名不含"任务"
def is_coord_image(filename: str, img: Image.Image) -> bool:
    return img.height <= 30 and "任务" not in filename


# 每张图应用的规则列表
def get_rules_for_image(filename: str, img: Image.Image) -> List[Tuple[str, object]]:
    if is_coord_image(filename, img):
        return [("WHITE", COORD_WHITE_RULE)]
    else:
        return [
            ("YELLOW", JHRW_YELLOW_RULE),
            ("RED", JHRW_RED_RULE),
            ("WHITE", JHRW_WHITE_RULE),
            ("GREEN", JHRW_GREEN_RULE),
        ]


# =====================================================================
# 扫描：收集所有未知字模
# =====================================================================

@dataclass
class ImageScanResult:
    """单张图的扫描结果。"""
    filename: str
    image_path: str
    is_coord: bool
    size: Tuple[int, int]
    # color_name -> RecognitionResult
    results: Dict[str, RecognitionResult] = field(default_factory=dict)
    # 该图中所有未知字模（去重后）
    unknown_glyphs: List[Glyph] = field(default_factory=list)
    # 已识别出的文本（用于验证）
    recognized_text: Dict[str, str] = field(default_factory=dict)


def scan_all_images() -> List[ImageScanResult]:
    """扫描所有图片，返回每张图的详细结果。"""
    engine = GlyphRecognizer()
    all_results = []

    images = sorted(GLYPH_IMAGE_DIR.glob("*.png"))
    print(f"找到 {len(images)} 张图片\n")

    total_unknown = 0
    total_known = 0

    for img_path in images:
        img = Image.open(img_path).convert("RGBA")
        arr = np.array(img)

        # 转 RGB (去掉 alpha)
        if arr.shape[2] == 4:
            rgb = arr[:, :, :3].copy()
            # Alpha 混合到黑色背景（游戏窗口背景）
            alpha = arr[:, :, 3:4].astype(float) / 255.0
            rgb = (rgb * alpha + np.zeros_like(rgb) * (1 - alpha)).astype(np.uint8)
        else:
            rgb = arr

        rules = get_rules_for_image(img_path.name, img)
        isr = ImageScanResult(
            filename=img_path.name,
            image_path=str(img_path),
            is_coord=is_coord_image(img_path.name, img),
            size=(img.width, img.height),
        )

        for rule_name, rule in rules:
            result = engine.recognize(rgb, rule=rule)
            isr.results[rule_name] = result
            isr.recognized_text[rule_name] = result.raw_text

            # 收集未知字模
            for g in result.glyphs:
                if g.char == "UNKNOWN" and g.normalized_hash and g.bitmap is not None:
                    # 检查是否已在该图的未知列表中
                    if not any(ug.normalized_hash == g.normalized_hash for ug in isr.unknown_glyphs):
                        isr.unknown_glyphs.append(g)

            known_count = len(result.glyphs) - len([g for g in result.glyphs if g.char == "UNKNOWN"])
            total_known += known_count
            total_unknown += result.unknown_count

        all_results.append(isr)

        # 打印摘要
        coord_tag = "[坐标]" if isr.is_coord else "[JHRW]"
        print(f"  {img_path.name:24s} {coord_tag} {img.width}x{img.height}", end="")
        for rn, r in isr.results.items():
            print(f"  {rn}:{len(r.glyphs)}c/{r.unknown_count}u", end="")
        print(f"  => {sum(r.unknown_count for r in isr.results.values())} 新未知")

    print(f"\n总计: {total_known} 已识别, {total_unknown} 未知")
    return all_results


# =====================================================================
# 导出未知字模位图
# =====================================================================

def export_unknown_glyphs(scan_results: List[ImageScanResult]) -> str:
    """导出所有未知字模的位图图片。"""
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)

    seen_hashes = set()
    exported = 0

    for isr in scan_results:
        if not isr.unknown_glyphs:
            continue

        # 为该图创建子目录
        safe_name = isr.filename.replace(".png", "")
        img_dir = EXPORT_DIR / safe_name
        img_dir.mkdir(exist_ok=True)

        for i, g in enumerate(isr.unknown_glyphs):
            h = g.normalized_hash
            if h in seen_hashes:
                continue
            seen_hashes.add(h)

            if g.bitmap is None:
                continue

            bmp = Image.fromarray((g.bitmap * 255).astype(np.uint8))
            bmp = bmp.resize((bmp.width * 5, bmp.height * 5), Image.NEAREST)
            fname = f"{i:03d}_x{g.bbox[0]:03d}_{h[:10]}.png"
            bmp.save(img_dir / fname)
            exported += 1

    print(f"\n导出 {exported} 个唯一未知字模到 {EXPORT_DIR}/")
    return str(EXPORT_DIR)


# =====================================================================
# 标注：根据用户提供的正确文本自动映射
# =====================================================================

@dataclass
class LabelEntry:
    """单个标注条目。"""
    source_file: str       # 来源图片名
    color_rule: str        # 颜色规则名
    correct_text: str      # 正确文本
    auto_mapped: int = 0   # 自动匹配成功数
    manual_needed: list = field(default_factory=list)  # 需要手动标注的


def label_from_text(
    scan_results: List[ImageScanResult],
    labels: Dict[str, Dict[str, str]],
    # labels = {
    #   "长安城1.png": {"WHITE": "长安城[241,101]"},
    #   "江南野外任务1.png": {"YELLOW": "江南野外", "RED": "...", ...},
    # }
    engine: Optional[GlyphRecognizer] = None,
) -> Tuple[int, int]:
    """
    根据用户提供的正确文本，自动将字模映射到字符。
    
    策略：
    1. 对每个已知字符，从正确文本中按顺序取字符
    2. 跳过断笔碎片（_后缀）
    3. 将 hash → char 映射写入库
    
    返回 (新增数, 总数)
    """
    if engine is None:
        engine = GlyphRecognizer()

    total_added = 0
    total_skipped = 0

    for isr in scan_results:
        file_labels = labels.get(isr.filename)
        if file_labels is None:
            print(f"  ⚠️  {isr.filename}: 无标注，跳过")
            continue

        for rule_name, correct_text in file_labels.items():
            result = isr.results.get(rule_name)
            if result is None:
                continue

            # 从正确文本生成非碎片字符序列
            # 断笔碎片在正确文本中不存在，需要跳过
            target_chars = list(correct_text)

            # 当前识别结果的字符序列（含碎片）
            glyphs = result.glyphs
            glyph_idx = 0
            char_idx = 0
            added = 0

            while glyph_idx < len(glyphs) and char_idx < len(target_chars):
                g = glyphs[glyph_idx]

                if g.char != "UNKNOWN":
                    # 已经认识，跳过
                    glyph_idx += 1
                    continue

                if not g.normalized_hash or g.bitmap is None:
                    glyph_idx += 1
                    continue

                target_char = target_chars[char_idx]

                # 检查这个 hash 是否已在库中
                if engine.library.lookup(g.normalized_hash):
                    glyph_idx += 1
                    char_idx += 1
                    total_skipped += 1
                    continue

                # 加入库
                engine.library.add(g.normalized_hash, target_char, autosave=False)
                added += 1
                total_added += 1
                glyph_idx += 1
                char_idx += 1

            if added > 0:
                print(f"  ✅ {isr.filename}[{rule_name}]: +{added} 个 (文本: {correct_text!r})")

    engine.library.save()
    print(f"\n字模库已保存: {engine.library.size} 个条目 (本次新增 {total_added})")
    return total_added, engine.library.size


# =====================================================================
# 验证：重新识别所有图片看效果
# =====================================================================

def verify_all(scan_results: Optional[List[ImageScanResult]] = None) -> None:
    """用当前库重新识别所有图片，报告准确率。"""
    engine = GlyphRecognizer()

    images = sorted(GLYPH_IMAGE_DIR.glob("*.png"))
    print(f"\n{'='*70}")
    print(f"验证：用当前库 ({engine.library.size} 条目) 重新识别所有图片")
    print(f"{'='*70}\n")

    for img_path in images:
        img = Image.open(img_path).convert("RGBA")
        arr = np.array(img)
        if arr.shape[2] == 4:
            alpha = arr[:, :, 3:4].astype(float) / 255.0
            arr_rgb = (arr[:, :, :3] * alpha).astype(np.uint8)
        else:
            arr_rgb = arr[:, :, :3]

        rules = get_rules_for_image(img_path.name, img)
        coord_tag = "[坐标]" if is_coord_image(img_path.name, img) else "[JHRW]"

        for rule_name, rule in rules:
            result = engine.recognize(arr_rgb, rule=rule)
            status = "✅" if result.unknown_count == 0 else f"⚠️ {result.unknown_count}u"
            text_display = result.raw_text[:60] + ("..." if len(result.raw_text) > 60 else "")
            print(f"  {img_path.name:24s} {coord_tag:5s} {rule_name:7s}: {text_display!r:50s} {status}")


# =====================================================================
# 主入口
# =====================================================================

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "scan"

    if cmd == "scan":
        print("=" * 70)
        print("Step 1: 扫描所有图片，收集未知字模")
        print("=" * 70 + "\n")
        results = scan_all_images()
        export_dir = export_unknown_glyphs(results)
        print(f"\n查看导出的字模位图: {export_dir}")

    elif cmd == "label":
        # 需要提供标注数据
        print("label 模式需要配合标注数据使用")
        print("请使用 build 模式或手动调用 label_from_text()")

    elif cmd == "verify":
        verify_all()

    elif cmd == "build":
        print("=" * 70)
        print("Step 1: 扫描")
        print("=" * 70 + "\n")
        results = scan_all_images()

        print("\n" + "=" * 70)
        print("Step 2: 导出未知字模")
        print("=" * 70 + "\n")
        export_dir = export_unknown_glyphs(results)

        print("\n" + "=" * 70)
        print("Step 3: 验证（用当前库）")
        print("=" * 70)
        verify_all(results)

    else:
        print(f"未知命令: {cmd}")
        print("用法: python batch_build_glyphs.py [scan|label|verify|build]")
