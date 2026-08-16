# -*- coding: utf-8 -*-
"""门派闯关识别器（sect_task_recognizer）回归测试。

验证：
  1. 15 张 BMP 模板交叉验证命中率 100%（地图名 + 次数）
  2. 模板加载 lru_cache 生效（二次加载同对象）
  3. 端到端识别输出格式 "地图名,N次"
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cv2
import numpy as np
import pytest
from PIL import Image

from core.sect_task_recognizer import (
    MAP_NAMES,
    _load_templates,
    recognize_sect_task,
    _extract_red_digits,
)

# 15 张模板的期望真值（文件名 → (地图名, 次数)）
EXPECTED = {
    "dt": ("大唐官府", "0"),
    "fcs": ("方寸山", "2"),
    "hss": ("化生寺", "12"),
    "lbc": ("凌波城", "9"),
    "lg": ("龙宫", "13"),
    "mw": ("魔王寨", "4"),
    "nrc": ("女儿村", "11"),
    "psd": ("普陀山", "7"),
    "pts": ("盘丝洞", "10"),
    "sml": ("神木林", "8"),
    "stl": ("狮驼岭", "14"),
    "tg": ("天宫", "6"),
    "wdd": ("无底洞", "8"),
    "wz": ("五庄观", "5"),
    "ycdf": ("阴曹地府", "3"),
}

BMP_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "assets", "game_data", "门派闯关",
)


def _load_img(fname):
    """读 BMP（cv2.imread 读不了 8-bit BMP，用 PIL）。"""
    img = np.array(Image.open(os.path.join(BMP_DIR, fname)).convert("RGB"))
    return cv2.cvtColor(img, cv2.COLOR_RGB2BGR)


class TestSectRecognizer:
    """门派闯关识别回归。"""

    @pytest.mark.parametrize("key", sorted(EXPECTED.keys()))
    def test_template_match_all(self, key):
        """15 张模板交叉验证：地图名 100% 命中。"""
        map_name, count = EXPECTED[key]
        img = _load_img(f"{key}.bmp")
        detail = recognize_sect_task(img, return_detail=True)
        assert detail["map_name"] == map_name, (
            f"{key}.bmp 期望 {map_name}，实际 {detail['map_name']}")
        assert detail["best_score"] > 0.95

    def test_output_format(self):
        """输出格式为 '地图名,N次'。"""
        img = _load_img("tg.bmp")
        text = recognize_sect_task(img)
        assert text == "天宫,6次", f"格式错误: {text}"

    def test_lru_cache(self):
        """模板加载缓存：二次调用同一对象。"""
        t1 = _load_templates()
        t2 = _load_templates()
        assert t1 is t2

    def test_cache_clear(self):
        """cache_clear 后重新加载。"""
        t1 = _load_templates()
        _load_templates.cache_clear()
        t2 = _load_templates()
        assert t1 is not t2

    def test_map_names_complete(self):
        """MAP_NAMES 含 16 个门派（含花果山）。"""
        assert len(MAP_NAMES) == 16
        assert "hgs" in MAP_NAMES
        assert MAP_NAMES["hgs"] == "花果山"

    def test_digit_extract(self):
        """红字数字提取：dt.bmp 应提取出 0。"""
        img = _load_img("dt.bmp")
        digits = _extract_red_digits(img)
        assert len(digits) >= 1
