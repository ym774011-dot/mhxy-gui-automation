# -*- coding: utf-8 -*-
"""
用用户提供的截图验证字模方案能否正确识别 JHRW 任务栏。

用法：
    E:/py/python.exe tools/verify_jhrw_user_image.py <图片路径>

图片应为任务追踪栏的裁剪局部（或完整窗口截图亦可，会按 JHRW_ROI 逻辑处理）。
脚本直接把图喂入 JHRWGlyphReader._do_recognize_jhrw(img=...)，绕开屏幕捕获，
便于离线验证字模库是否覆盖当前渲染字形。
"""
import sys
import os
import cv2

# 确保项目根在 sys.path（直接 `python tools/xxx.py` 运行时 sys.path[0] 是 tools/）
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from core.glyph_coord_reader import jhrw_reader


def main():
    img_path = sys.argv[1] if len(sys.argv) > 1 else (
        r"C:\Users\Administrator\.workbuddy\clipboard-images"
        r"\clipboard-2026-08-03T13-20-02-591Z-79f5de34.png"
    )
    img = cv2.imread(img_path)
    if img is None:
        print(f"[FAIL] 无法读取图片: {img_path}")
        return 1

    print(f"[INFO] 图片尺寸: {img.shape[1]}x{img.shape[0]} (WxH)")

    # 直接喂图，绕开屏幕捕获
    info = jhrw_reader._do_recognize_jhrw(img=img)
    if info is None:
        print("[FAIL] 字模识别返回 None")
        return 1

    print("=" * 50)
    print("识别结果:")
    print(f"  quest_name      = {info['quest_name']!r}")
    print(f"  target_location = {info['target_location']!r}")
    print(f"  target_coord    = {info['target_coord']}")
    print(f"  npc_name        = {info['npc_name']!r}")
    print(f"  progress        = {info['progress']}")
    print(f"  instruction     = {info['instruction']!r}")
    print(f"  unknown_count   = {info['unknown_count']}")
    print("-" * 50)
    print("原始分通道文本:")
    for ch in ("yellow", "red", "white", "green"):
        print(f"  [{ch}] {info['raw'].get(ch, '')!r}")
    print("=" * 50)

    # 期望（来自用户描述）：初出江湖 / 东海湾(58,55) / 江湖大盗 / 第238次
    expect_map, expect_coord = "东海湾", (58, 55)
    ok_map = info["target_location"] == expect_map
    ok_coord = info["target_coord"] == expect_coord
    ok_quest = info["quest_name"] == "初出江湖"
    print(f"期望对比: quest=初出江湖({ok_quest}) "
          f"map=东海湾({ok_map}) coord=(58,55)({ok_coord})")
    return 0 if (ok_map and ok_coord and ok_quest) else 2


if __name__ == "__main__":
    sys.exit(main())
