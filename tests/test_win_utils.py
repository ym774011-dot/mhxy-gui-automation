# -*- coding: utf-8 -*-
"""窗口查找公共模块（library/common/win_utils.py）回归测试。

验证从 9 个地图函数包抽取的公共函数行为正确：
  - find_game_pids 返回进程 PID 列表（不崩、可枚举）
  - find_game_window 找不到窗口时返回 (None, None)
  - client_to_screen 坐标转换不抛异常
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from library.common.win_utils import (
    find_game_window,
    find_game_pids,
    locate_game_window,
    client_to_screen,
    GAME_TITLE_KEYWORDS,
)


class TestWinUtils:
    """公共窗口模块基础行为。"""

    def test_keywords_present(self):
        """游戏标题特征字齐全。"""
        for kw in ("鲜衣", "一梦", "梦幻", "十年"):
            assert kw in GAME_TITLE_KEYWORDS

    def test_find_game_pids_returns_list(self):
        """枚举进程返回列表（可能为空，但不崩）。"""
        pids = find_game_pids()
        assert isinstance(pids, list)
        for p in pids:
            assert isinstance(p, int)
            assert p > 0

    def test_find_game_window_invalid_pid(self):
        """无效 PID 返回 (None, None)。"""
        hwnd, title = find_game_window(999999999)
        assert hwnd is None and title is None

    def test_locate_game_window_never_crashes(self):
        """定位函数不抛异常；preferred_pid 无效时兜底枚举真实进程（有窗口返回 hwnd，无则 None）。"""
        hwnd, title = locate_game_window(preferred_pid=999999999, verbose=False)
        # 两种合法结果：兜底找到真实游戏窗口(hwnd非0)，或完全找不到(hwnd=None)
        assert hwnd is None or hwnd != 0

    def test_client_to_screen_invalid_hwnd(self):
        """无效窗口句柄坐标转换不崩（返回坐标元组）。"""
        result = client_to_screen(0, 100, 200)  # hwnd=0 无效，应返回坐标
        assert isinstance(result, tuple)
        assert len(result) == 2


class TestMapPackIntegration:
    """地图函数包 import 公共模块的集成验证。"""

    def test_map_pack_alias_import(self):
        """地图包通过别名 import 公共函数（重构后兼容）。"""
        import library.map_packs  # noqa

        # 抽查一个包：窗口函数应为公共模块函数
        from library.map_packs import ALG
        assert callable(ALG._find_game_pids)
        # 与公共模块同对象
        assert ALG._find_game_pids == find_game_pids
