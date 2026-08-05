# -*- coding: utf-8 -*-
"""后台输入模式注入测试（2026-08-05 全后台化阶段 1）。"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/..")

from core.task_library_manager import TaskLibraryManager


def _fake_map_func(target_coord, *more, pid=0, click=True, background=False, verbose=False):
    return target_coord, background


class BackgroundModeTests(unittest.TestCase):
    def setUp(self):
        self.mgr = TaskLibraryManager()

    def _patch_mode(self, mode):
        return mock.patch(
            "core.input_controller.input_controller._get_mode",
            return_value=mode,
        )

    def test_inject_when_background_config(self):
        with self._patch_mode("background"):
            _, kwargs = self.mgr._inject_background_mode(
                _fake_map_func, "JYC", "JYC", ((100, 100),), {}
            )
        self.assertTrue(kwargs.get("background"))

    def test_not_inject_when_foreground_config(self):
        with self._patch_mode("foreground"):
            _, kwargs = self.mgr._inject_background_mode(
                _fake_map_func, "JYC", "JYC", ((100, 100),), {}
            )
        self.assertNotIn("background", kwargs)

    def test_explicit_background_not_overridden(self):
        with self._patch_mode("background"):
            _, kwargs = self.mgr._inject_background_mode(
                _fake_map_func, "JYC", "JYC", ((100, 100),), {"background": False}
            )
        self.assertFalse(kwargs.get("background"))

    def test_no_background_param_untouched(self):
        def fake_jhrw(pid=0):
            return 1
        with self._patch_mode("background"):
            _, kwargs = self.mgr._inject_background_mode(
                fake_jhrw, "JHRW", "JHRW", (), {}
            )
        self.assertEqual(kwargs, {})


if __name__ == "__main__":
    unittest.main()
