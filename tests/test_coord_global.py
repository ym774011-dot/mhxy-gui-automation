# -*- coding: utf-8 -*-
"""
extract_coord_global 全括号扫描提取坐标 —— 回归测试。

用户需求（2026-08-05）：坐标 100% 在括号里，不管第几行，只要在 () 内
就是完整坐标。本测试覆盖：

  1. 跨行坐标 (66,103) —— `(66,10` + 行2 `3)`（真实 live log 场景）
  2. 同行坐标 (251,23)
  3. 括号内中文 → 排除（如 `(当前第290次)`）
  4. 无逗号 4 位硬切 (39,66)
  5. 多括号竞争：跨行 (66,103) vs 干扰 (3,3)
  6. 黄通道失败回退白通道
  7. 白通道 `(3,3)` 残影不应骗到黄通道正确坐标
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import unittest
from core.glyph_coord_reader import extract_coord_global
from core.glyph_recognizer import Glyph, RecognitionResult


def _g(char, x, y=0, w=6, h=12):
    """快速构造 Glyph"""
    return Glyph(char=char, bbox=(x, y, w, h))


def _result(glyphs):
    return RecognitionResult(glyphs=glyphs, raw_text="".join(g.char for g in glyphs))


class CoordGlobalTests(unittest.TestCase):
    """extract_coord_global 核心场景"""

    def test_cross_line_66103(self):
        """跨行坐标：行1 `(66,10`，行2 行首 `3)` → (66, 103)"""
        glyphs = [
            _g("江", 0), _g("南", 13, w=12),
            _g("(", 40, w=3),
            _g("6", 45), _g("6", 52),
            _g(",", 60, w=2, h=4),
            _g("1", 64, w=3), _g("0", 68),
            # 行2
            _g("3", 40, y=16),
            _g(")", 47, y=16, w=3),
            _g("处", 60, y=16, w=12), _g("查", 73, y=16, w=12),
        ]
        coord = extract_coord_global([_result(glyphs)])
        self.assertEqual(coord, (66, 103), "跨行 (66,10 + 3) 应拼接为 (66, 103)")

    def test_same_line_25123(self):
        """同行坐标 (251, 23)"""
        glyphs = [
            _g("建", 0, w=12),
            _g("(", 30, w=3),
            _g("2", 35), _g("5", 42), _g("1", 49, w=3),
            _g(",", 53, w=2, h=4),
            _g("2", 57), _g("3", 64),
            _g(")", 71, w=3),
            _g("处", 80, w=12),  # ')' 右侧中文不应干扰
        ]
        coord = extract_coord_global([_result(glyphs)])
        self.assertEqual(coord, (251, 23))

    def test_progress_paren_excluded(self):
        """进度 `(当前第290次)` 括号内有中文 → 排除"""
        glyphs = [
            _g("(", 30, w=3),
            _g("当", 35, w=12), _g("前", 48, w=12),
            _g("2", 61), _g("9", 68), _g("0", 75),
            _g(")", 82, w=3),
        ]
        coord = extract_coord_global([_result(glyphs)])
        self.assertIsNone(coord, "括号内有中文的进度数字不应被当作坐标")

    def test_no_comma_4digits_3966(self):
        """无逗号 4 位硬切 (39, 66)"""
        glyphs = [
            _g("(", 30, w=3),
            _g("3", 35), _g("9", 42),
            _g("6", 49), _g("6", 56),
            _g(")", 63, w=3),
        ]
        coord = extract_coord_global([_result(glyphs)])
        self.assertEqual(coord, (39, 66))

    def test_multi_paren_competition(self):
        """多括号竞争：跨行 (66,103) 应胜出，干扰 (3,3) 不应选中"""
        glyphs = [
            _g("(", 40, w=3),
            _g("6", 45), _g("6", 52),
            _g(",", 60, w=2, h=4),
            _g("1", 64, w=3), _g("0", 68),
            _g("3", 40, y=16), _g(")", 47, y=16, w=3),
            # 干扰 (3,3)
            _g("(", 110, w=3), _g("3", 115), _g(")", 122, w=3),
        ]
        coord = extract_coord_global([_result(glyphs)])
        self.assertEqual(coord, (66, 103))

    def test_fallback_white_when_yellow_empty(self):
        """黄通道空 → 回退白通道 (58, 55)"""
        white_glyphs = [
            _g("(", 30, w=3),
            _g("5", 35), _g("8", 42),
            _g(",", 49, w=2, h=4),
            _g("5", 53), _g("5", 60),
            _g(")", 67, w=3),
        ]
        coord = extract_coord_global([
            _result([]),          # 黄通道无结果
            _result(white_glyphs) # 白通道有
        ])
        self.assertEqual(coord, (58, 55))

    def test_white_ghost_33_not_override_yellow(self):
        """白通道 `(3,3)` 残影不应覆盖黄通道正确 (66,103)"""
        yellow = [
            _g("(", 40, w=3),
            _g("6", 45), _g("6", 52),
            _g(",", 60, w=2, h=4),
            _g("1", 64, w=3), _g("0", 68),
            _g("3", 40, y=16), _g(")", 47, y=16, w=3),
        ]
        white = [
            _g("(", 22, w=3),
            _g("3", 27, w=3), _g(",", 32, w=2, h=4), _g("3", 36),
            _g(")", 41, w=3),
        ]
        coord = extract_coord_global([_result(yellow), _result(white)])
        self.assertEqual(coord, (66, 103), "黄通道应优先且不受白通道残影干扰")

    def test_cross_line_109105(self):
        """跨行坐标：(109,1 换行 05) → (109, 105)（2026-08-04 live log 场景）"""
        glyphs = [
            _g("(", 111, y=61, w=3),
            _g("1", 116, y=62, w=5), _g("0", 122, y=62),
            _g("9", 129, y=62), _g(",", 137, y=70, w=2, h=4),
            _g("1", 144, y=62, w=5),
            # 续行 "05)"（行首 x 小）
            _g("0", 10, y=78), _g("5", 18, y=78, w=5),
            _g(")", 25, y=77, w=3),
        ]
        coord = extract_coord_global([_result(glyphs)])
        self.assertEqual(coord, (109, 105))

    def test_no_comma_5digits_13047_gap(self):
        """无逗号 5 位，逗号位置有大间隙 → 间隙分界切 3+2 = (130, 47)

        用户 live log 2026-08-05 13:18:55：正确坐标 (130,47) 被识别成 (13,47)。
        逗号 2×3px 被连通域吞掉后，X/Y 交界处（0|4 之间）间隙明显大于字间距。
        """
        glyphs = [
            _g("(", 30, w=3),
            _g("1", 35), _g("3", 42), _g("0", 49),
            # 大间隙（逗号位置，约 13px）
            _g("4", 62), _g("7", 69),
            _g(")", 76, w=3),
        ]
        coord = extract_coord_global([_result(glyphs)])
        self.assertEqual(coord, (130, 47))

    def test_no_comma_5digits_13047_even(self):
        """无逗号 5 位等距（间隙不显著）→ 双候选，3+2 与 2+3 都生成，
        评分相同按先验取 2+3 → (13, 47)；此场景本质歧义，留给真实截图
        的 0 变体入库解决。这里仅验证不崩溃且返回合法候选之一。"""
        glyphs = [
            _g("(", 30, w=3),
            _g("1", 35), _g("3", 43), _g("0", 51),
            _g("4", 59), _g("7", 67),
            _g(")", 74, w=3),
        ]
        coord = extract_coord_global([_result(glyphs)])
        self.assertIn(coord, ((13, 47), (130, 47)))

    def test_4digits_no_comma_1347_0_lost(self):
        """0 被识别为 UNKNOWN（未入库变体）→ 括号间有 UNKNOWN 窄块夹在
        数字之间，补位穷举应还原 (130, 47)（用户 live log 场景）。"""
        glyphs = [
            _g("(", 30, w=3),
            _g("1", 35), _g("3", 42),
            _g("UNKNOWN", 49, w=5, h=10),  # 丢失的 0（窄高块）
            _g("4", 62), _g("7", 69),       # 大间隙（逗号位置）
            _g(")", 76, w=3),
        ]
        coord = extract_coord_global([_result(glyphs)])
        self.assertEqual(coord, (130, 47))

    def test_cross_line_13047_real_layout(self):
        """真实 live 布局（2026-08-05 13:38 新 ROI）：行1 `(130,4` + 行2 `7)`，
        逗号被吞 → (130, 47)。复刻黄通道 glyph 几何。"""
        glyphs = [
            _g("(", 108, y=25, w=3),
            _g("1", 113, y=26, w=5),
            _g("3", 120, y=26, w=5),
            _g("0", 126, y=26, w=6),
            _g("4", 141, y=26, w=5),
            # 行2 续接
            _g("7", 8, y=42, w=5),
            _g(")", 15, y=41, w=3),
        ]
        coord = extract_coord_global([_result(glyphs)])
        self.assertEqual(coord, (130, 47))

    def test_none_when_no_paren(self):
        """没有括号 → None"""
        glyphs = [_g("江", 0, w=12), _g("南", 13, w=12)]
        self.assertIsNone(extract_coord_global([_result(glyphs)]))


if __name__ == "__main__":
    unittest.main()
