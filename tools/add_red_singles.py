# -*- coding: utf-8 -*-
"""将红通道缺失的单字（初出江湖/当前第 的整字）补录进字库。

这些 hash 来自 collect_red_glyphs.py 对 7 张 JHRW 任务截图的红通道单字抽取，
对应「初出江湖当前第N次)」中的整字（红字体比坐标白字小，需单独建库）。
"""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.glyph_recognizer import GlyphRecognizer

NEW = {
    # 红通道整字（单字粒度）
    "588317bea2bd34ceab02d4dedc557748": "初",
    "5c8ce2ca3a4074709c9d93cb8861aa74": "出",
    "7dfeb66fbab6817be144f66c0d9f8358": "湖",
    "63097c68939c7351dac80438921b3d48": "第",
    "32eca6a57722b8bc11a0898ce19a53b7": "前",
}


def main():
    lib = GlyphRecognizer().library
    added, skipped, conflicts = [], [], []
    for h, ch in NEW.items():
        if h in lib._entries:
            if lib._entries[h] == ch:
                skipped.append((h, ch))
            else:
                conflicts.append((h, lib._entries[h], ch))
        else:
            lib.add(h, ch, autosave=False)
            added.append((h, ch))
    if added:
        lib.save()
    print(f"新增 {len(added)} 条，跳过 {len(skipped)} 条，冲突 {len(conflicts)} 条")
    for h, ch in added:
        print(f"  + {ch} <- {h}")
    for h, old, new in conflicts:
        print(f"  ! 冲突 {h}: 库={old} 新={new}")
    print(f"当前字库共 {lib.size} 条")


if __name__ == "__main__":
    main()
