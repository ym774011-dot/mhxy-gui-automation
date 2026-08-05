# -*- coding: utf-8 -*-
"""
JHRW 坐标识别调试工具。

对一张 JHRW 面板截图（BMP/PNG，BGR 或 RGB 均可）跑全部坐标提取路径，
diff 出各路径的候选坐标与命中的 '(' / ')' / 数字几何信息，用于定位
"为什么识别成了 (3,3)" 这类问题。

用法::
    E:/py/python.exe tools/debug_jhrw_coord.py <图片路径> [--verbose]
    E:/py/python.exe tools/debug_jhrw_coord.py debug_capture/jhrw_live_v10.png
    E:/py/python.exe tools/debug_jhrw_coord.py <截图> --verbose   # 输出全部 glyph bbox

若不带图片参数，默认对 config/settings.json 的 JHRW ROI 区域做一次
在线截屏识别（需要游戏窗口已绑定）。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cv2

from core.glyph_recognizer import (
    GlyphRecognizer,
    JHRW_YELLOW_RULE,
    JHRW_WHITE_RULE,
    JHRW_RED_RULE,
)
from core.glyph_coord_reader import (
    extract_coord_global,
    extract_coord_spatial,
    parse_coord_pair,
    get_jhrw_roi,
    _first_coord_x,
    _map_name_subsequence,
    recognize_map_name_fingerprint,
)
from utils.logger import logger


def analyze(path: str, verbose: bool = False) -> None:
    img = cv2.imread(path)
    if img is None:
        # 尝试按 BGR 读（cv2.imread 默认 BGR，失败说明路径问题）
        print(f"[错误] 无法读取图片: {path}")
        return
    print(f"图片: {path}  尺寸={img.shape[1]}x{img.shape[0]}")
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

    recog = GlyphRecognizer()
    yr = recog.recognize(rgb, rule=JHRW_YELLOW_RULE, segmentation="blobs")
    wr = recog.recognize(rgb, rule=JHRW_WHITE_RULE, segmentation="blobs")
    rr = recog.recognize(rgb, rule=JHRW_RED_RULE, segmentation="single")

    print("\n── 各通道原始识别 ──")
    print(f"  黄: {yr.raw_text!r}  (unknown={yr.unknown_count})")
    print(f"  白: {wr.raw_text!r}  (unknown={wr.unknown_count})")
    print(f"  红: {rr.raw_text!r}  (unknown={rr.unknown_count})")

    print("\n── 地图名识别 ──")
    fprint = recognize_map_name_fingerprint(rgb, yr)
    subseq = _map_name_subsequence(yr)
    print(f"  整块指纹: {fprint!r}")
    print(f"  字符子序列: {subseq!r}")
    print(f"  坐标起始列 x={_first_coord_x(yr)}")

    print("\n── 坐标提取各路径对比 ──")
    g_global = extract_coord_global([yr, wr])
    g_spatial_y = extract_coord_spatial(yr)
    g_spatial_w = extract_coord_spatial(wr)
    g_re_y = parse_coord_pair(yr.raw_text)
    g_re_w = parse_coord_pair(wr.raw_text)
    print(f"  [新] extract_coord_global(黄+白): {g_global}")
    print(f"  [旧] extract_coord_spatial(黄):    {g_spatial_y}")
    print(f"  [旧] extract_coord_spatial(白):    {g_spatial_w}")
    print(f"  [旧] parse_coord_pair(黄 raw):     {g_re_y}")
    print(f"  [旧] parse_coord_pair(白 raw):     {g_re_w}")
    print(f"  ── 最终优先级结果 ──")
    print(f"  {g_global or g_spatial_y or g_spatial_w or g_re_y or g_re_w}")

    if verbose:
        print("\n── 黄通道全部 glyph ──")
        for g in sorted(yr.glyphs, key=lambda g: (g.bbox[1], g.bbox[0])):
            print(
                f"  {g.char!r:10} bbox={g.bbox}  "
                f"cy={g.bbox[1] + g.bbox[3] / 2:.0f}  hash={g.normalized_hash[:12]}"
            )
        print("\n── 白通道全部 glyph ──")
        for g in sorted(wr.glyphs, key=lambda g: (g.bbox[1], g.bbox[0])):
            print(
                f"  {g.char!r:10} bbox={g.bbox}  "
                f"cy={g.bbox[1] + g.bbox[3] / 2:.0f}  hash={g.normalized_hash[:12]}"
            )


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    verbose = "--verbose" in sys.argv or "-v" in sys.argv
    if args:
        analyze(args[0], verbose=verbose)
        return 0

    # 无参数 → 在线截屏
    from core.screen_capture import screen_capture

    x, y, w, h = get_jhrw_roi()
    print(f"在线截屏 JHRW ROI ({x},{y}) {w}x{h} ...")
    img = screen_capture.capture_region(x, y, w, h)
    if img is None:
        print("[错误] 截屏失败")
        return 1
    tmp = os.path.join(os.path.dirname(__file__), "..", "debug_capture", "debug_jhrw_live.png")
    os.makedirs(os.path.dirname(tmp), exist_ok=True)
    cv2.imwrite(tmp, img)
    print(f"已保存: {tmp}")
    analyze(tmp, verbose=verbose)
    return 0


if __name__ == "__main__":
    sys.exit(main())
