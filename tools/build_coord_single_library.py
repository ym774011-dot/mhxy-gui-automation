# -*- coding: utf-8 -*-
"""
把 3 个地图名(东/海/湾/建/邺/城/江/南/野/外) + 0-9 数字 + 标点(,),()
的单字字模合并进现有 glyph_library.json。
每个独立汉字/数字/标点 = 一条（不做整串合并）。
保留原有 JHRW 合并条目（hash 空间不同，互不冲突）。
"""
from __future__ import annotations
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "data", "glyph_library.json")

# (hash, char) —— 单字，逐字由 ASCII 人工判定
NEW_ENTRIES = {
    # 东海湾
    "6f45100a1bcdbba97a3f3987808a42c9": "东",
    "f0201c7159d23e8ed35a64384329ef76": "海",
    "17d3cff2f003fe8d17d7a2aeea11ec07": "湾",
    # 建邺城
    "3a0b2cc15f97ef0e827a2eca122c1b7f": "建",
    "275b9df559090a40676bb3996451b6af": "邺",
    "0cdcd0dfe8a436143c8124d2d06a52ae": "城",
    # 江南野外
    "ace2383ec3f31a6174472161a657de7c": "江",
    "1b90a6bdab429ff7975653163b514e75": "南",
    "fe06c20923550af8c7831f4a914c727c": "野",
    "79a3bdfbaab613bac67fd689eb95fa80": "外",
    # 数字 0-9（含 1px 抖动变体）
    "ecfe0b253c927302d5ea1bd37f1fbbb7": "0",
    "cbb8f95764aa2eb24bbd5e170c2ba730": "1",
    "1c7c2ff47987ea60bfc747125b618c87": "1",
    "8264608566e95ae84195635d9ff9d950": "2",
    "3e993af197522ff3daa9469f523ae0ea": "4",
    "37cce802c6273aada6316ed878f16350": "5",
    "7ef67c3fc4c5da2a3ec68aa60c2ba730": "6",
    "03e299bb8178e9f43080699c4ece10d3": "7",
    "dab442bb635a6c82023490c659fe2add": "8",
    "d2b76b22f41ba49d3d8acd72cf968529": "8",
    "b77bfd68a5d1790d61dfd6e4672f406a": "9",
    "57b0a2b4261311e5afd6978d64954775": "3",
    "7a00fc86246dda6cf0f1c643e6cd13d8": "3",
    # 标点
    "06eb740d3623ea4adb42948903839881": ",",
    "9871d9bcb91067b6407e70498fd8dcfb": ")",  # 墨在右、开口朝左
    "a299340c02eea60eb696d6b00e76ce8d": "(",  # 墨在左、开口朝右
    "da8455f596482070f141bb0839edd635": "(",  # 墨在左、开口朝右
}

def main():
    d = json.load(open(LIB, encoding="utf-8"))
    entries = d.setdefault("entries", {})
    added, dup = 0, 0
    for hx, ch in NEW_ENTRIES.items():
        if hx in entries:
            if entries[hx] != ch:
                print(f"冲突覆盖: {hx} {entries[hx]!r} -> {ch!r}")
            entries[hx] = ch
            dup += 1
        else:
            entries[hx] = ch
            added += 1
    d["metadata"] = dict(d.get("metadata", {}))
    d["metadata"]["single_char_maps"] = ["东海湾", "建邺城", "江南野外"]
    d["metadata"]["single_char_note"] = (
        "每个独立汉字/数字/标点单条入库；地图名+0-9 数字为单字模式识别源"
    )
    json.dump(d, open(LIB, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"新增 {added} 条，已存在(含覆盖) {dup} 条；当前字库共 {len(entries)} 条")
    # 打印字符覆盖统计
    from collections import Counter
    c = Counter(entries.values())
    singles = [k for k, v in entries.items() if len(v) == 1]
    print(f"单字类(长度1)条目数: {len(singles)}")

if __name__ == "__main__":
    main()
