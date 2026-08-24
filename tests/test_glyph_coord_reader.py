# -*- coding: utf-8 -*-
"""C1 补测：glyph_coord_reader 坐标提取 / 文本解析纯函数（2026-08-24）。

覆盖 REVIEW.md C1（核心识别模块零单测）中的坐标读取链路：
- extract_coord_global：全括号扫描（2026-08-05 多轮修复的核心，最易回归）
- extract_coord_spatial：空间邻域法
- parse_location_text / parse_progress_text / parse_coord_pair：纯文本解析

数据为合成 Glyph 序列（bbox 模拟 16px 字号渲染：数字/标点 8x16、中文 12x16、
逗号 2x4、行高 16px）。断言与 live 实测一致（(130,47)/(66,103) 等）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.glyph_coord_reader import (  # noqa: E402
    extract_coord_global,
    extract_coord_spatial,
    parse_coord_pair,
    parse_location_text,
    parse_progress_text,
)
from core.glyph_recognizer import Glyph, RecognitionResult  # noqa: E402


def G(char, x, y=10, w=8, h=16):
    """构造合成 glyph（数字/标点默认 8x16；中文宽度由调用方 w 覆盖）。"""
    return Glyph(char=char, bbox=(x, y, w, h))


def result_of(glyphs):
    return RecognitionResult(glyphs=glyphs)


class TestExtractCoordGlobal:
    """extract_coord_global：穷举 '(' 候选 + 评分选最优。"""

    def test_same_line_with_comma(self):
        # (66,47)：逗号存在 + Y 2 位紧贴逗号（y_digits 15px 阈值内）
        r = result_of([
            G("(", 0), G("6", 10), G("6", 18), G(",", 27, 19, 2, 4),
            G("4", 30), G("7", 38), G(")", 46),
        ])
        assert extract_coord_global([r]) == (66, 47)

    def test_same_line_comma_3digit_y_compact(self):
        # (66,103)：数字窄渲染时 Y 3 位可紧贴逗号
        r = result_of([
            G("(", 0, w=10), G("6", 10, w=5), G("6", 16, w=5), G(",", 22, 19, 2, 4),
            G("1", 25, w=5), G("0", 31, w=5), G("3", 37, w=5), G(")", 43, w=10),
        ])
        assert extract_coord_global([r]) == (66, 103)

    def test_no_comma_hard_split_2_3(self):
        # (66,103) 逗号被吞：无逗号 5 位硬切 2+3（X=66 Y=103）
        r = result_of([
            G("(", 0), G("6", 10), G("6", 18), G("1", 26), G("0", 34), G("3", 42), G(")", 50),
        ])
        assert extract_coord_global([r]) == (66, 103)

    def test_cross_line_continuation(self):
        # (66,10 + 行2 3) → (66,103)：跨行 Y 续接（+20 跨行分）
        r = result_of([
            G("(", 0), G("6", 10), G("6", 18), G(",", 27, 19, 2, 4), G("1", 30), G("0", 38),
            G("3", 2, 26), G(")", 10, 26),
        ])
        assert extract_coord_global([r]) == (66, 103)

    def test_cjk_inside_paren_excluded(self):
        # (当前第290次)：括号内混中文 → 直接排除非坐标
        r = result_of([
            G("(", 0), G("当", 10, w=12), G("前", 22, w=12), G("第", 34, w=12),
            G("2", 46), G("9", 54), G("0", 62), G("次", 70, w=12), G(")", 82),
        ])
        assert extract_coord_global([r]) is None

    def test_no_comma_gap_split(self):
        # (130,47) 逗号被吞但留空隙：最大间隙分界 → 3+2（2026-08-05 二轮修复）
        r = result_of([
            G("(", 0), G("1", 10), G("3", 18), G("0", 26), G("4", 40), G("7", 48), G(")", 56),
        ])
        assert extract_coord_global([r]) == (130, 47)

    def test_no_comma_no_gap_hard_split_known_behavior(self):
        # (130,47) 无间隙纯硬切：5 位先验 2+3 优先 → (13,47)。
        # 已知边界（真实场景靠间隙 / UNKNOWN 补位修正），锁定行为防意外回归。
        r = result_of([
            G("(", 0), G("1", 10), G("3", 18), G("0", 26), G("4", 34), G("7", 42), G(")", 50),
        ])
        assert extract_coord_global([r]) == (13, 47)

    def test_unknown_narrow_fill(self):
        # 0 变体未入库 → UNKNOWN 窄块补位穷举：(13?47) → (130,47)
        r = result_of([
            G("(", 0), G("1", 10), G("3", 18),
            Glyph(char="UNKNOWN", bbox=(26, 10, 4, 12)),
            G("4", 36), G("7", 44), G(")", 52),
        ])
        assert extract_coord_global([r]) == (130, 47)

    def test_white_ghost_3_3_single(self):
        # 白通道 (3,3) 残影：低分但唯一候选时返回；调用方只对黄通道使用
        # （本函数行为锁定：单候选返回、多候选被高分压制）
        r = result_of([
            G("(", 0), G("3", 10), G(",", 19, 19, 2, 4), G("3", 22), G(")", 30),
        ])
        assert extract_coord_global([r]) == (3, 3)

    def test_multiple_parens_best_wins(self):
        # (66,47) + (当前第290次)：中文排除 + 低分压制 → (66,47)
        r = result_of([
            G("(", 0), G("6", 10), G("6", 18), G(",", 27, 19, 2, 4), G("4", 30), G("7", 38), G(")", 46),
            G("(", 70), G("当", 80, w=12), G("前", 92, w=12), G("第", 104, w=12),
            G("2", 116), G("9", 124), G("0", 132), G("次", 140, w=12), G(")", 152),
        ])
        assert extract_coord_global([r]) == (66, 47)

    def test_empty_glyphs(self):
        assert extract_coord_global([result_of([])]) is None

    def test_none_result_skipped(self):
        assert extract_coord_global([None]) is None

    def test_multiple_results_first_success(self):
        # 第一个 result 无坐标、第二个有 → 取第二个成功
        r_bad = result_of([G("当", 0, w=12), G("前", 12, w=12)])
        r_ok = result_of([
            G("(", 0), G("6", 10), G("6", 18), G(",", 27, 19, 2, 4), G("4", 30), G("7", 38), G(")", 46),
        ])
        assert extract_coord_global([r_bad, r_ok]) == (66, 47)


class TestExtractCoordSpatial:
    """extract_coord_spatial：'(' + 最近 ')' 单点试探。"""

    def test_basic(self):
        r = result_of([
            G("(", 0), G("6", 10), G("6", 18), G(",", 27, 19, 2, 4), G("4", 30), G("7", 38), G(")", 46),
        ])
        assert extract_coord_spatial(r) == (66, 47)

    def test_none_or_empty(self):
        assert extract_coord_spatial(None) is None
        assert extract_coord_spatial(result_of([])) is None


class TestParseText:
    """纯文本解析（红/白通道正则兜底）。"""

    def test_coord_pair(self):
        assert parse_coord_pair("(105,25)") == (105, 25)
        assert parse_coord_pair("前往(66,103)处查明") == (66, 103)
        assert parse_coord_pair("没有坐标") is None

    def test_location_text(self):
        assert parse_location_text("建邺城(203,56)") == {"map": "建邺城", "x": 203, "y": 56}
        assert parse_location_text("长安城[248,100]") == {"map": "长安城", "x": 248, "y": 100}
        assert parse_location_text("江南野外 34,116") == {"map": "江南野外", "x": 34, "y": 116}
        assert parse_location_text("") is None

    def test_progress_text(self):
        assert parse_progress_text("身份(当前第229次)") == 229
        assert parse_progress_text("第12次") == 12
        assert parse_progress_text("当前290") == 290   # 兜底：唯一多位数字
        assert parse_progress_text("没有数字") is None
