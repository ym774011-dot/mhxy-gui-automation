# -*- coding: utf-8 -*-
"""
等待到达期间隐藏鼠标 —— 回归测试。

用户需求（2026-08-05 14:16）：等待到达期间把鼠标移到屏幕 (5,5)，
避免光标挡住 YOLO/模板识别目标导致识别失败。

覆盖：
  1. wait_for_arrival 签名含 hide_mouse 参数（默认 True）
  2. hide_mouse=False 时不调用移鼠标
  3. task_engine 透传 wait_arrival_hide_mouse 参数
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import inspect
import unittest
from unittest import mock

from core.arrival_verifier import ArrivalVerifier
from core.jhrw_controller import JHRWController


class HideMouseTests(unittest.TestCase):
    """等待到达隐藏鼠标"""

    def test_signature_has_hide_mouse(self):
        """wait_for_arrival 必须暴露 hide_mouse 参数（默认 True）"""
        sig = inspect.signature(ArrivalVerifier.wait_for_arrival)
        self.assertIn("hide_mouse", sig.parameters)
        self.assertEqual(sig.parameters["hide_mouse"].default, True)

    def test_hide_mouse_triggered_by_default(self):
        """默认 hide_mouse=True → 应调用 _move_mouse_away"""
        v = ArrivalVerifier()
        with mock.patch.object(v, "_move_mouse_away") as m, \
             mock.patch.object(v, "_reader", create=True) as r:
            r.is_connected = True
            # should_stop_cb 立即返回 True → 循环第一轮退出
            v.wait_for_arrival(10, 10, timeout=1, should_stop_cb=lambda: True)
            m.assert_called_once()

    def test_hide_mouse_skipped_when_disabled(self):
        """hide_mouse=False → 不调用 _move_mouse_away"""
        v = ArrivalVerifier()
        with mock.patch.object(v, "_move_mouse_away") as m, \
             mock.patch.object(v, "_reader", create=True) as r:
            r.is_connected = True
            v.wait_for_arrival(10, 10, timeout=1, should_stop_cb=lambda: True,
                               hide_mouse=False)
            m.assert_not_called()

    def test_jhrw_controller_signature(self):
        """jhrw_controller.wait_for_arrival 同样暴露 hide_mouse（默认 True）"""
        sig = inspect.signature(JHRWController.wait_for_arrival)
        self.assertIn("hide_mouse", sig.parameters)
        self.assertEqual(sig.parameters["hide_mouse"].default, True)


if __name__ == "__main__":
    unittest.main()
