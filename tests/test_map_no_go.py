# -*- coding: utf-8 -*-
"""
地图禁区规避 —— 回归测试。

用户需求（2026-08-05 14:36）：NPC 站在地图传送热点上，角色走过去会被
传送到别的地图。用户在 data/map_no_go_zones.json 维护禁区表，脚本在
点地图前自动把目标坐标修正到禁区外最近安全点。

覆盖：
  1. resolve_safe_coord：禁区内目标修正 / 禁区外不变
  2. safe_target_for_module：模块名 → 地图名映射
  3. task_library_manager._avoid_no_go_zone：
     - kwargs 场景修正
     - 位置参数场景修正
     - 非禁区不变
     - 非地图函数（JHRW）不动
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import unittest
from unittest import mock

from core.map_no_go import (
    MODULE_MAP_NAME,
    is_in_no_go_zone,
    resolve_safe_coord,
    safe_target_for_module,
)
from core.task_library_manager import TaskLibraryManager


def fake_map_func(target_coord, pid=0, click=True, background=False, verbose=False):
    return target_coord


class MapNoGoTests(unittest.TestCase):
    """禁区规避核心逻辑"""

    def test_module_map_mapping(self):
        """模块名 → 地图名映射完整"""
        self.assertEqual(MODULE_MAP_NAME["JYC"], "建邺城")
        self.assertEqual(MODULE_MAP_NAME["JNYW"], "江南野外")
        self.assertEqual(MODULE_MAP_NAME["DHW"], "东海湾")
        self.assertIn("CAC", MODULE_MAP_NAME)

    def test_zone_detection(self):
        """禁区内 / 外判定（示例禁区：建邺城 (171,109) 半径 3）"""
        self.assertTrue(is_in_no_go_zone("建邺城", 171, 109)[0])
        self.assertTrue(is_in_no_go_zone("建邺城", 172, 110)[0])  # 半径内
        self.assertFalse(is_in_no_go_zone("建邺城", 100, 100)[0])
        self.assertFalse(is_in_no_go_zone("建邺城", 176, 109)[0])  # 半径外

    def test_resolve_in_zone(self):
        """禁区内目标 → 按 fix 规则修正（建邺城统一 X-5, Y-5）"""
        x, y, adj = resolve_safe_coord("建邺城", 171, 109)
        self.assertTrue(adj)
        # 用户规则：X-5, Y-5
        self.assertEqual((x, y), (166.0, 104.0))
        # 安全点不能在禁区内
        self.assertFalse(is_in_no_go_zone("建邺城", x, y)[0])

    def test_fix_rule_for_all_hotspots(self):
        """建邺城禁区坐标全部按 X-5,Y-5 修正（边界钳到 0）"""
        hotspots = [
            (171, 109), (220, 138), (240, 120), (267, 114), (235, 65),
            (259, 58), (145, 60), (5, 61), (71, 133), (116, 16), (239, 13),
            (271, 114),
        ]
        for hx, hy in hotspots:
            x, y, adj = resolve_safe_coord("建邺城", hx, hy)
            self.assertTrue(adj, f"({hx},{hy}) 应被修正")
            self.assertEqual(
                (x, y), (float(max(0, hx - 5)), float(max(0, hy - 5))),
                f"({hx},{hy}) 应按 X-5,Y-5 修正"
            )
            self.assertFalse(is_in_no_go_zone("建邺城", x, y)[0])

    def test_resolve_outside_unchanged(self):
        """禁区外目标 → 原样返回"""
        x, y, adj = resolve_safe_coord("建邺城", 100, 100)
        self.assertFalse(adj)
        self.assertEqual((x, y), (100.0, 100.0))

    def test_safe_target_for_module(self):
        """按模块名规避"""
        x, y, adj = safe_target_for_module("JYC", (171, 109))
        self.assertTrue(adj)
        self.assertFalse(is_in_no_go_zone("建邺城", x, y)[0])
        # 未登记模块不动
        x2, y2, adj2 = safe_target_for_module("UNKNOWN", (171, 109))
        self.assertFalse(adj2)


class AvoidNoGoZoneHookTests(unittest.TestCase):
    """task_library_manager 钩子"""

    def setUp(self):
        self.mgr = TaskLibraryManager()

    def test_kwargs_adjusted(self):
        """kwargs 传 target_coord 且在禁区 → 修正"""
        _, k = self.mgr._avoid_no_go_zone(
            fake_map_func, "JYC", "JYC", (), {"target_coord": (171, 109)}
        )
        self.assertNotEqual(tuple(int(v) for v in k["target_coord"]), (171, 109))
        sx, sy = k["target_coord"]
        self.assertFalse(is_in_no_go_zone("建邺城", sx, sy)[0])

    def test_positional_adjusted(self):
        """位置参数传 target_coord 且在禁区 → 修正"""
        a, _ = self.mgr._avoid_no_go_zone(
            fake_map_func, "JYC", "JYC", ((171, 109),), {}
        )
        sx, sy = a[0]
        self.assertFalse(is_in_no_go_zone("建邺城", sx, sy)[0])

    def test_expanded_args_adjusted(self):
        """展开传参 JYC(x, y)（日志 15:44:53 实际场景）→ 修正"""
        a, _ = self.mgr._avoid_no_go_zone(
            fake_map_func, "JYC", "JYC", (271, 114), {}
        )
        self.assertEqual(a, (266.0, 109.0))
        sx, sy = a
        self.assertFalse(is_in_no_go_zone("建邺城", sx, sy)[0])

    def test_wait_arrival_target_adjusted(self):
        """等待到达目标（JHRW 结果 target_coord）在禁区 → 修正为安全点"""
        x, y, adj = resolve_safe_coord("建邺城", 271, 114)
        self.assertTrue(adj)
        self.assertEqual((x, y), (266.0, 109.0))

    def test_outside_unchanged(self):
        """禁区外坐标 → 原样"""
        _, k = self.mgr._avoid_no_go_zone(
            fake_map_func, "JYC", "JYC", (), {"target_coord": (100, 100)}
        )
        self.assertEqual(k["target_coord"], (100, 100))

    def test_non_map_module_untouched(self):
        """非地图函数（JHRW）不处理"""
        _, k = self.mgr._avoid_no_go_zone(
            lambda target_coord: target_coord, "JHRW", "JHRW",
            (), {"target_coord": (171, 109)}
        )
        self.assertEqual(k["target_coord"], (171, 109))


if __name__ == "__main__":
    unittest.main()
