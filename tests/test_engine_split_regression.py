# -*- coding: utf-8 -*-
"""任务引擎 Mixin 拆分回归测试。

验证 task_engine.py 拆分为 ClickMixin/YoloMixin/SwitchMixin 后：
  1. 方法仍可从 TaskEngine 实例调用（继承链完整）
  2. _do_click 的 input_controller 运行时从主模块取（测试可 patch）
  3. switch 条件分发正常
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import patch, Mock, MagicMock

from core.task_engine import TaskEngine, task_engine
from core.task_engine_mixins import ClickMixin, YoloMixin, SwitchMixin


class TestEngineSplit:
    """拆分后继承链与单例完整性。"""

    def test_mixins_in_mro(self):
        """TaskEngine 继承链包含三个 Mixin。"""
        mro = [c.__name__ for c in TaskEngine.__mro__]
        assert "ClickMixin" in mro
        assert "YoloMixin" in mro
        assert "SwitchMixin" in mro

    def test_singleton_unchanged(self):
        """模块级单例仍是 TaskEngine 实例。"""
        assert isinstance(task_engine, TaskEngine)

    def test_methods_available(self):
        """关键方法从 TaskEngine 可调用（不管定义在哪个 Mixin）。"""
        for m in ["_do_click", "_do_additional_click", "_lookup_coord_from_file",
                  "_execute_yolo_detect", "_yolo_pick_target",
                  "_execute_switch_condition_with_depth",
                  "_execute_switch_actions"]:
            assert callable(getattr(TaskEngine, m)), f"{m} 不可调用"

    def test_method_qualname(self):
        """确认方法确实定义在 Mixin（而非主类）。"""
        assert TaskEngine._do_click.__qualname__.startswith("ClickMixin")
        assert TaskEngine._execute_yolo_detect.__qualname__.startswith("YoloMixin")
        assert (TaskEngine._execute_switch_condition_with_depth
                .__qualname__.startswith("SwitchMixin"))


class TestDoClickSplit:
    """_do_click 拆分后行为不变（patch 生效）。"""

    @patch("core.task_engine.input_controller")
    @patch("core.window_manager.window_manager")
    def test_do_click_left(self, mock_wm, mock_ic):
        mock_wm.is_valid.return_value = True
        mock_ic.click = Mock(return_value=True)
        engine = TaskEngine.__new__(TaskEngine)
        result = engine._do_click((100, 200), "left", 0.0)
        assert result is True
        mock_ic.click.assert_called_once()

    @patch("core.task_engine.input_controller")
    @patch("core.window_manager.window_manager")
    def test_do_click_move(self, mock_wm, mock_ic):
        """move 类型：只移动不点击。"""
        mock_wm.is_valid.return_value = True
        mock_ic.move_to = Mock(return_value=True)
        engine = TaskEngine.__new__(TaskEngine)
        result = engine._do_click((100, 200), "move", 0.0)
        assert result is True
        mock_ic.move_to.assert_called_once_with(100, 200)
        mock_ic.click.assert_not_called()

    @patch("core.window_manager.window_manager")
    def test_do_click_window_not_bound(self, mock_wm):
        """窗口未绑定返回 False。"""
        mock_wm.is_valid.return_value = False
        engine = TaskEngine.__new__(TaskEngine)
        result = engine._do_click((100, 200), "left", 0.0)
        assert result is False
