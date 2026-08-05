# -*- coding: utf-8 -*-
"""task_library_manager._filter_kwargs 单元测试。

验证 GUI「填入关键字参数」生成的通用 key 在传给不同地图函数时，
能被正确过滤，避免 ``TypeError: XXX() got an unexpected keyword argument``。

覆盖场景：
  - JNYW/ALG/BXG/CSC/DHW/JYC/XLNR/ZZG 等点击函数（不接受 location）
  - JHRW（接受 target_location）
  - 声明 **kwargs 的函数（不过滤）
  - 空 kwargs / 仅保留有效参数
"""
import pytest

from core.task_library_manager import TaskLibraryManager


# ---- 模拟真实地图函数签名（与 梦幻西游脚本函数包/地图数据/*.py 一致）----
def _map_click_fn(target_coord, *more, pid=28024, click=True,
                  background=True, verbose=False):
    """模拟 JNYW/ALG/BXG/... 等地图点击函数签名。"""
    return target_coord


def _jhrw_fn(target_location=None, target_coord=None, pid=None, verbose=False):
    """模拟 JHRW（接受 target_location）签名。"""
    return target_location


def _var_kw_fn(a, **kwargs):
    """声明 **kwargs 的函数，应接受任意关键字。"""
    return (a, kwargs)


# _filter_kwargs 不依赖实例状态（仅用 inspect + 模块级 logger），用类直接调用
_filter = TaskLibraryManager._filter_kwargs


class TestFilterKwargs:
    """_filter_kwargs 行为测试。"""

    def test_filter_location_from_click_fn(self):
        """JNYW 等点击函数不接受 location，应被过滤。"""
        out = _filter(None, _map_click_fn, "JNYW", "JNYW",
                      {"location": "江南野外"})
        assert out == {}

    def test_filter_target_location_from_click_fn(self):
        """点击函数也不接受 target_location，应被过滤。"""
        out = _filter(None, _map_click_fn, "JNYW", "JNYW",
                      {"target_location": "江南野外"})
        assert out == {}

    def test_keep_target_location_for_jhrw(self):
        """JHRW 接受 target_location，应保留。"""
        out = _filter(None, _jhrw_fn, "JHRW", "JHRW",
                      {"target_location": "江南野外"})
        assert out == {"target_location": "江南野外"}

    def test_keep_valid_drop_invalid(self):
        """有效参数保留，无效参数过滤。"""
        out = _filter(None, _map_click_fn, "JNYW", "JNYW",
                      {"pid": 12345, "location": "x", "click": False})
        assert out == {"pid": 12345, "click": False}

    def test_no_filter_when_var_keyword(self):
        """函数声明 **kwargs 时，不过滤任何关键字。"""
        out = _filter(None, _var_kw_fn, "M", "f",
                      {"a": 1, "anything": 2, "location": "x"})
        assert out == {"a": 1, "anything": 2, "location": "x"}

    def test_empty_kwargs_passthrough(self):
        """空 kwargs 原样返回。"""
        assert _filter(None, _map_click_fn, "JNYW", "JNYW", {}) == {}

    def test_all_valid_kept(self):
        """全部参数都有效时原样返回。"""
        kw = {"pid": 1, "click": True, "background": False, "verbose": True}
        out = _filter(None, _map_click_fn, "JNYW", "JNYW", kw)
        assert out == kw


class TestCallFunctionIntegration:
    """call_function 端到端：多余 kwargs 不再导致调用失败。"""

    def test_call_function_drops_unexpected_kwarg(self, monkeypatch):
        """call_function 传 location 给点击函数，不再抛 TypeError。"""
        from core import task_library_manager as tlm

        # 构造一个最小 manager，注入模拟模块
        mgr = tlm.TaskLibraryManager.__new__(tlm.TaskLibraryManager)
        mgr.modules = {
            "JNYW": {
                "enabled": True,
                "module": None,
                "functions": [("JNYW", _map_click_fn, "(target_coord, ...)")],
            }
        }
        import threading
        mgr._lock = threading.Lock()

        # 屏蔽 PID 注入（避免依赖 window_manager）
        monkeypatch.setattr(mgr, "_inject_bound_pid",
                            lambda func, m, f, a, k: (a, k))

        ok, result, err = mgr.call_function(
            "JNYW", "JNYW", (102, 80), location="江南野外"
        )
        assert ok is True, f"应成功，但报错: {err}"
        assert result == (102, 80)
        assert err == ""
