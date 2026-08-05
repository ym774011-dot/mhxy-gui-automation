# -*- coding: utf-8 -*-
"""
JHRW 解析回归测试 —— 验证本次修复：

  1. extract_coord_spatial —— 逗号被吞、4 位数字（如 "3966"）硬切 2+2
  2. _map_name_subsequence  —— 江三点水被吞（如 [南, 野, 外, 外]）模糊匹配回退

无需真实截图，用合成的 RecognitionResult 直接驱动两个被测函数。
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import unittest
from core.glyph_coord_reader import (
    extract_coord_spatial,
    _map_name_subsequence,
    _dedupe_neighbor_same_char,
    KNOWN_JHRW_MAPS,
)
from core.glyph_recognizer import Glyph, RecognitionResult


def _g(char, x, w=8, h=12, y=0):
    """快速构造 Glyph"""
    return Glyph(char=char, bbox=(x, y, w, h))


def _result(glyphs):
    return RecognitionResult(glyphs=glyphs, raw_text="".join(g.char for g in glyphs))


class CoordSpatialTests(unittest.TestCase):
    """extract_coord_spatial 的兜底场景：4 位数字无逗号"""

    def test_4digits_no_comma_3966(self):
        """4 位数字 "3966" 在 ( ... ) 之间无逗号 → 应硬切 2+2 = (39, 66)"""
        glyphs = [
            _g("(", 0),
            _g("3", 12), _g("9", 22),
            _g("6", 32), _g("6", 42),
            _g(")", 52),
        ]
        coord = extract_coord_spatial(_result(glyphs))
        self.assertEqual(coord, (39, 66), "3966 应硬切为 (39, 66)")

    def test_5digits_no_comma_12345(self):
        """5 位数字 "12345" → 应硬切 2+3 = (12, 345)"""
        glyphs = [
            _g("(", 0),
            _g("1", 12), _g("2", 22),
            _g("3", 32), _g("4", 42), _g("5", 52),
            _g(")", 62),
        ]
        coord = extract_coord_spatial(_result(glyphs))
        self.assertEqual(coord, (12, 345), "12345 应硬切为 (12, 345)")

    def test_6digits_no_comma_248100(self):
        """6 位数字 "248100" → 应硬切 3+3 = (248, 100)"""
        glyphs = [
            _g("(", 0),
            _g("2", 12), _g("4", 22), _g("8", 32),
            _g("1", 42), _g("0", 52), _g("0", 62),
            _g(")", 72),
        ]
        coord = extract_coord_spatial(_result(glyphs))
        self.assertEqual(coord, (248, 100), "248100 应硬切为 (248, 100)")

    def test_normal_with_comma_still_works(self):
        """含逗号场景仍正常 —— "(39,66)" → (39, 66)"""
        glyphs = [
            _g("(", 0),
            _g("3", 12), _g("9", 22),
            _g(",", 32, w=3, h=8),
            _g("6", 42), _g("6", 52),
            _g(")", 62),
        ]
        coord = extract_coord_spatial(_result(glyphs))
        self.assertEqual(coord, (39, 66), "(39,66) 正常路径")

    def test_paren_without_close_paren_hard_split(self):
        """截图右侧被裁掉 — 没有 ')' — 4 位数字应硬切 2+2 = (39, 66)

        这是 2026-08-03 23:13 live log 的根因：
        用户江南野外(39,66) 截图被裁掉了 ')'，extract_coord_spatial
        之前会 return None，回落到白通道拿到 (3, 3)。
        修复后构造虚拟 ')' 让数字位数硬切能跑通。
        """
        glyphs = [
            _g("(", 0),
            _g("3", 12), _g("9", 22),
            _g("6", 32), _g("6", 42),
            # 注意：没有 ')'
        ]
        coord = extract_coord_spatial(_result(glyphs))
        self.assertEqual(coord, (39, 66),
                         "缺少 ')' 时 4 位数字也应硬切 2+2 = (39, 66)")

    def test_2digits_no_comma_5_3(self):
        """2 位数字无逗号 → 大间隙兜底应切为 (5, 3)"""
        glyphs = [
            _g("(", 0),
            _g("5", 12),
            _g("3", 32),  # 大间隙 8px
            _g(")", 52),
        ]
        coord = extract_coord_spatial(_result(glyphs))
        self.assertEqual(coord, (5, 3), "2 位数字大间隙 → (5, 3)")


class MapNameSubsequenceTests(unittest.TestCase):
    """_map_name_subsequence 的模糊匹配场景：江三点水被吞"""

    def test_jianjiang_missing_full_overlap(self):
        """江被吞、外重复 → [南, 野, 外, 外] 应模糊匹配 江南野外"""
        glyphs = [
            _g("南", 30),
            _g("野", 50),
            _g("外", 70),
            _g("外", 80),  # 重复
            _g("(", 95),
            _g("3", 105), _g("9", 115), _g("6", 125), _g("6", 135),
        ]
        name = _map_name_subsequence(_result(glyphs))
        self.assertEqual(name, "江南野外", "江被吞时模糊匹配应为 江南野外")

    def test_donghaiwan_normal(self):
        """东海湾 正常识别 → 不走模糊"""
        glyphs = [
            _g("东", 30), _g("海", 50), _g("湾", 70),
            _g("(", 95),
            _g("5", 105), _g("8", 115), _g(",", 122, w=3),
            _g("5", 130), _g("5", 140),
        ]
        name = _map_name_subsequence(_result(glyphs))
        self.assertEqual(name, "东海湾", "东海湾 正常子序列匹配")

    def test_jianyechen_missing_ye(self):
        """建邺城 邺 被吞 → [建, 城] 是 子序列 → 仍可识别（无歧义）"""
        glyphs = [
            _g("建", 30), _g("城", 70),
        ]
        name = _map_name_subsequence(_result(glyphs))
        self.assertEqual(name, "建邺城", "建城 是 建邺城 的子序列 → 仍可识别")

    def test_empty(self):
        """无字形 → None"""
        self.assertIsNone(_map_name_subsequence(_result([])))

    def test_all_donghai_chars_missing(self):
        """东海湾 全 UNKNOWN → None"""
        glyphs = [_g("?", 30), _g("?", 50)]
        name = _map_name_subsequence(_result(glyphs))
        self.assertIsNone(name, "无任何已识别地图名字符 → None")

    def test_user_log_scenario_jhrw_yellow(self):
        """回归 2026-08-03 22:54 live 日志：黄通道 raw 含
        ')UNKNOWNUNKNOWNUNKNOWN南野外外(3966UNKNOWN'
        → target_location=江南野外（江被吞模糊匹配）, coord=(39,66)（逗号被吞硬切）

        这是用户报的真实 log：地图名变成"南野外外"，坐标变成 (3,3)。
        修复后：模糊匹配回退到 江南野外；4 位 3966 按 2+2 硬切为 (39, 66)。
        """
        # 复刻黄通道字形：) UNKNOWN×3 南 野 外 外 ( 3 9 6 6 ) UNKNOWN
        glyphs = [
            _g(")", 0),
            _g("?", 10), _g("?", 20), _g("?", 30),     # 前帧残留
            _g("南", 40), _g("野", 60), _g("外", 80), _g("外", 90),
            _g("(", 105),
            _g("3", 115), _g("9", 125), _g("6", 135), _g("6", 145),
            _g(")", 158), _g("?", 168),
        ]
        # 地图名（江被吞）
        name = _map_name_subsequence(_result(glyphs))
        self.assertEqual(name, "江南野外",
                         "log 场景: 江被吞 + 外重复 → 模糊匹配回退到 江南野外")

        # 坐标（逗号被吞）—— 注意 _first_coord_x 用字库 '()' 命中定位，digits 找 4 个连续数字
        coord = extract_coord_spatial(_result(glyphs))
        self.assertEqual(coord, (39, 66),
                         "log 场景: 4 位 3966 无逗号 → 2+2 硬切 → (39, 66)")


class DedupeNeighborSameCharTests(unittest.TestCase):
    """_dedupe_neighbor_same_char：合并"1"被毛刺切成两半的相邻同字符 blob。

    回归 2026-08-04 01:00 user live log：游戏实际 "东海湾[19,100]" 被字模
    误读成 (119, 100)。抗锯齿下单个 "1" 被 blob splitter 切成 2 个独立
    连通域（hash 不同但 char 都是 "1"）。
    """

    def test_duplicate_1_merged_into_single_19(self):
        """东海湾[19,100]：单 "1" 被切两半（h=12 主体 + h=10 毛刺）→ 合并为 1 个 '1'"""
        # 复刻 live log 的实际 blob 序列：东海湾 + [ + 1 + 1(毛刺) + 9 + , + 1 + 0 + 0 + ]
        glyphs = [
            _g("?", 10, w=11, h=14), _g("?", 29, w=9, h=14), _g("?", 45, w=8, h=14),
            _g("[", 55, w=3, h=12),
            _g("1", 58, w=3, h=12), _g("1", 65, w=5, h=10),  # ← 真 1 (h=12) + 毛刺 1 (h=10)
            _g("9", 73, w=6, h=10),
            _g(",", 80, w=3, h=4),
            _g("1", 92, w=5, h=10),
            _g("0", 100, w=6, h=10), _g("0", 109, w=6, h=10),
            _g("]", 117, w=3, h=12),
        ]
        deduped = _dedupe_neighbor_same_char(glyphs)
        chars = [g.char for g in deduped]
        # 毛刺"1"(h=10) < 真"1"(h=12) → 去重；两个"0"h=10 一致 → 保留
        self.assertEqual(chars,
                         ["?", "?", "?", "[", "1", "9", ",", "1", "0", "0", "]"],
                         "东海湾[19,100] 应识别为 5 个数字（119→19，100 保留两个 0）")

    def test_real_chars_with_same_height_not_merged(self):
        """真实相邻字符 "100" 中两个 0 高度一致 → 不去重（user live log 2026-08-04 01:04 教训）"""
        glyphs = [
            _g("1", 0, w=3, h=12),
            _g("0", 5, w=6, h=10), _g("0", 14, w=6, h=10),  # 两个 0 高度一致
        ]
        deduped = _dedupe_neighbor_same_char(glyphs)
        self.assertEqual([g.char for g in deduped], ["1", "0", "0"],
                         "两个 0 高度一致（h=10/h=10）不应去重")

    def test_real_chars_not_merged_by_gap(self):
        """正常相邻字符 "12"（gap > 5 或字符宽度差异显著）不去重"""
        glyphs = [
            _g("1", 0, w=3, h=12),
            _g("2", 10, w=5, h=10),
        ]
        deduped = _dedupe_neighbor_same_char(glyphs)
        self.assertEqual([g.char for g in deduped], ["1", "2"],
                         "相邻字符 12 保留，不去重")

    def test_punctuation_not_merged(self):
        """标点不会因同字符相邻被去重（避免 '1,1' → '1,'）"""
        glyphs = [
            _g("1", 0, w=3),
            _g(",", 4, w=2),
            _g(",", 8, w=2),
            _g("1", 12, w=3),
        ]
        deduped = _dedupe_neighbor_same_char(glyphs)
        self.assertEqual([g.char for g in deduped], ["1", ",", ",", "1"],
                         "两个连续逗号不被合并")

    def test_different_rows_not_merged(self):
        """不同行（垂直不重叠）的同字符不合并"""
        glyphs = [
            _g("1", 0, w=3, y=0),
            _g("1", 5, w=3, y=20),  # 垂直偏移 20px，不重叠
        ]
        deduped = _dedupe_neighbor_same_char(glyphs)
        self.assertEqual([g.char for g in deduped], ["1", "1"],
                         "不同行的两个 '1' 不应合并")

    def test_empty(self):
        self.assertEqual(_dedupe_neighbor_same_char([]), [])


class CoordCrossLineTests(unittest.TestCase):
    """坐标跨行换行续接（2026-08-04 23:52 live log）：

    游戏面板过窄时 "(109, 105)" 被换行拆成：
      第一行尾部  "(109, 1"
      第二行行首  "05)"
    此时本行没有 ')'（虚拟括号），Y 只取到 "1"，
    需要跨行找下一行行首以 ')' 结尾的数字段拼到 Y 后面。
    """

    def _yellow(self):
        """复刻 live log 黄通道 glyph 布局（坐标行 y=62，续行 y=78）。"""
        return [
            # 地图名（y=62 行）
            _g("江", 53, w=12, h=12, y=62),
            _g("南", 66, w=13, h=14, y=60),
            _g("野", 80, w=13, h=13, y=61),
            _g("外", 94, w=6, h=14, y=60),
            _g("外", 102, w=5, h=14, y=60),
            # 坐标 (109, 1  ← 本行只到 '1'，'05)' 换行
            _g("(", 111, w=3, h=12, y=61),
            _g("1", 116, w=5, h=10, y=62),
            _g("0", 122, w=6, h=10, y=62),
            _g("9", 129, w=6, h=10, y=62),
            _g(",", 137, w=2, h=4, y=70),
            _g("1", 144, w=5, h=10, y=62),
            # 续行 "05)"（第二行行首，x 小）
            _g("0", 10, w=6, h=10, y=78),
            _g("5", 18, w=5, h=10, y=78),
            _g(")", 25, w=3, h=12, y=77),
            # 行尾干扰块（y=23 上方）
            _g("UNKNOWN", 149, w=10, h=8, y=23),
        ]

    def test_cross_line_y_continuation(self):
        """"(109, 1" + 换行 "05)" → (109, 105)"""
        coord = extract_coord_spatial(_result(self._yellow()))
        self.assertEqual(coord, (109, 105),
                         "跨行坐标 (109, 105) 应续接为 105")

    def test_no_virtual_cp_no_crossline(self):
        """正常场景（有真实 ')' 在同一行）不应触发跨行续接。

        "(39, 66)" 全部在一行 → 直接 (39, 66)。
        """
        glyphs = [
            _g("(", 0, y=62),
            _g("3", 8, y=62), _g("9", 16, y=62),
            _g(",", 24, y=66),
            _g("6", 28, y=62), _g("6", 36, y=62),
            _g(")", 44, w=3, h=12, y=61),
        ]
        coord = extract_coord_spatial(_result(glyphs))
        self.assertEqual(coord, (39, 66), "同行坐标不应跨行续接")


class MapNameFuzzyTests(unittest.TestCase):
    """地图名模糊归一化（2026-08-05 00:16 用户需求）：

    字模识别"江南野"（"外"与"["粘连丢失）应归一化为"江南野外"。
    """

    def _parse(self, text: str):
        from core.glyph_coord_reader import parse_location_text
        return parse_location_text(text)

    def test_missing_last_char_jnys(self):
        """"江南野08,103"（"外"丢失）→ map='江南野外', x=8, y=103"""
        loc = self._parse("江南野08,103)")
        self.assertEqual(loc["map"], "江南野外")
        self.assertEqual((loc["x"], loc["y"]), (8, 103))

    def test_full_name_exact(self):
        """"东海湾" 完全匹配 → 原样返回"""
        loc = self._parse("东海湾(58,55)")
        self.assertEqual(loc["map"], "东海湾")
        self.assertEqual((loc["x"], loc["y"]), (58, 55))

    def test_missing_two_chars(self):
        """"建邺"（丢"城"）→ '建邺城'"""
        loc = self._parse("建邺(251,23)")
        self.assertEqual(loc["map"], "建邺城")
        self.assertEqual((loc["x"], loc["y"]), (251, 23))

    def test_unknown_in_map_no_crash(self):
        """map 含 UNKNOWN 占位 → 子序列仍可匹配（重叠兜底）"""
        from core.glyph_coord_reader import parse_location_text
        # "长安UNKNOWN城" → 删 UNKNOWN → "长安城"
        loc = parse_location_text("长安UNKNOWN城248,100)")
        self.assertEqual(loc["map"], "长安城")
        self.assertEqual((loc["x"], loc["y"]), (248, 100))

    def test_unknown_name_returns_as_is(self):
        """"XXX" 无法匹配 → 原样返回（不崩溃）"""
        loc = self._parse("XXX12,34)")
        self.assertEqual(loc["map"], "XXX")
        self.assertEqual((loc["x"], loc["y"]), (12, 34))


if __name__ == "__main__":
    unittest.main(verbosity=2)