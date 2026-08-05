# -*- coding: utf-8 -*-
"""地图 UI 遮挡避让测试（max_game_coord 用户实测优先）。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/..")

from core.map_ui_block import (
    _load_ui_blocks,
    get_map_calibration,
    map_coord_ui_avoid,
)


class MapUiBlockTests(unittest.TestCase):
    def test_maps_have_user_limits(self):
        data = _load_ui_blocks()
        for m in ("江南野外", "建邺城", "东海湾"):
            self.assertIn(m, data, f"{m} 应有配置")
            self.assertEqual(len(data[m]["max_game_coord"]), 2, f"{m} 应有 max_game_coord")

    def test_jnyw_158_74_clamped(self):
        """用户案例：江南野外 (158,74) X>157 → 钳制 (157,74)"""
        x, y, ui = map_coord_ui_avoid("江南野外", 158, 74)
        self.assertEqual(ui, "大地图有效范围")
        self.assertEqual((x, y), (157.0, 74.0))

    def test_inside_limit_unchanged(self):
        """未超限坐标不变"""
        x, y, ui = map_coord_ui_avoid("江南野外", 100, 60)
        self.assertIsNone(ui)
        self.assertEqual((x, y), (100.0, 60.0))

    def test_dhw_limits(self):
        """东海湾上限 (117,117)"""
        x, y, ui = map_coord_ui_avoid("东海湾", 200, 100)
        self.assertEqual((x, y), (117.0, 100.0))
        x, y, ui = map_coord_ui_avoid("东海湾", 150, 150)
        self.assertEqual((x, y), (117.0, 117.0))

    def test_jyc_user_limit_not_harmed_by_pixel_rect(self):
        """建邺城 (284,80) 用户实测有效 → 不被旧像素矩形误伤"""
        x, y, ui = map_coord_ui_avoid("建邺城", 284, 80)
        self.assertIsNone(ui)
        self.assertEqual((x, y), (284.0, 80.0))
        # 超限 → 钳制
        x, y, ui = map_coord_ui_avoid("建邺城", 300, 80)
        self.assertEqual((x, y), (284.0, 80.0))

    def test_unknown_map_no_crash(self):
        x, y, ui = map_coord_ui_avoid("不存在的地图", 100, 100)
        self.assertIsNone(ui)
        self.assertEqual((x, y), (100.0, 100.0))

    def test_calibration_readable(self):
        for m in ("江南野外", "建邺城", "东海湾"):
            self.assertIsNotNone(get_map_calibration(m), f"{m} 校准应可读")


if __name__ == "__main__":
    unittest.main()
