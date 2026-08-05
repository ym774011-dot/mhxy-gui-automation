# -*- coding: utf-8 -*-
"""
输入控制器：按键名 -> 虚拟键码映射单元测试。

覆盖 PR #5 的合并重构：
    - 原前台路径局部 KEY_MAP（hex 字面量）与原后台 _SPECIAL_VK（win32con）
      合并为单一权威映射 InputController._KEY_NAME_TO_VK，两发送后端共用。
    - 表驱动测试验证：并集完整、值与 win32con 一致、前台曾缺失的键现已可用。
"""
import pytest
import win32con
from unittest.mock import patch, MagicMock

from core.input_controller import InputController


# 旧两表并集期望键名（来自原前台 KEY_MAP + 原后台 _SPECIAL_VK）
_LEGACY_KEYS = {
    # 原前台 KEY_MAP
    "alt", "ctrl", "control", "shift", "win", "tab", "enter", "return",
    "esc", "escape", "space", "backspace", "delete", "del", "up", "down",
    "left", "right", "home", "end", "pageup", "pagedown",
    "f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9", "f10", "f11", "f12",
    # 原后台 _SPECIAL_VK（前台曾缺失，合并后补齐）
    "menu", "bs", "insert", "ins", "capslock", "numlock", "scrolllock",
    "pgup", "pgdn",
}

# 代表性键 -> win32con 期望值（核对合并后值无漂移）
_EXPECTED = {
    "ctrl": win32con.VK_CONTROL,
    "alt": win32con.VK_MENU,
    "shift": win32con.VK_SHIFT,
    "win": win32con.VK_LWIN,
    "enter": win32con.VK_RETURN,
    "tab": win32con.VK_TAB,
    "esc": win32con.VK_ESCAPE,
    "space": win32con.VK_SPACE,
    "backspace": win32con.VK_BACK,
    "delete": win32con.VK_DELETE,
    "up": win32con.VK_UP,
    "down": win32con.VK_DOWN,
    "left": win32con.VK_LEFT,
    "right": win32con.VK_RIGHT,
    "home": win32con.VK_HOME,
    "end": win32con.VK_END,
    "pageup": win32con.VK_PRIOR,
    "pagedown": win32con.VK_NEXT,
    # 合并后补齐的前台曾缺失键
    "menu": win32con.VK_MENU,
    "bs": win32con.VK_BACK,
    "insert": win32con.VK_INSERT,
    "capslock": win32con.VK_CAPITAL,
    "numlock": win32con.VK_NUMLOCK,
    "scrolllock": win32con.VK_SCROLL,
    "f1": win32con.VK_F1,
    "f12": win32con.VK_F12,
}


def _ic():
    """拿到单例实例（InputController 为单例，__new__ 返回既有 _instance）。"""
    return InputController()


def test_union_completeness():
    """合并后的映射应包含旧两表的所有键名。"""
    for k in _LEGACY_KEYS:
        assert k in InputController._KEY_NAME_TO_VK, f"合并后缺失键: {k}"


def test_no_drift_vs_win32con():
    """每个键的值都与 win32con 常量一致（无漂移）。"""
    for k, v in _EXPECTED.items():
        assert InputController._KEY_NAME_TO_VK[k] == v, f"键 {k} 值漂移"


def test_foreground_missing_keys_now_present():
    """PR #5 修复点：前台路径曾缺失的键，合并后已可用。"""
    for k in ["menu", "bs", "insert", "ins", "capslock", "numlock", "scrolllock", "pgup", "pgdn"]:
        assert k in InputController._KEY_NAME_TO_VK


def test_key_to_vk_table_driven():
    """_key_to_vk 对表内键返回正确 VK（表驱动）。"""
    ic = _ic()
    for k, v in _EXPECTED.items():
        assert ic._key_to_vk(k) == v, f"_key_to_vk({k!r}) 返回错误"


def test_key_to_vk_single_char():
    """单字符走 VkKeyScan 路径。"""
    ic = _ic()
    assert ic._key_to_vk("a") == ord("A")
    assert ic._key_to_vk("1") == ord("1")


def test_key_to_vk_unknown():
    """未知键 / 空键返回 None。"""
    ic = _ic()
    assert ic._key_to_vk("zzz") is None
    assert ic._key_to_vk("") is None


def test_foreground_press_uses_shared_map():
    """
    集成验证：前台路径改用共享表，能解析此前前台不支持的键（如 menu/f1）。

    mock 掉 ctypes.windll.user32.keybd_event 捕获发送的 VK，并强制前台模式。
    """
    ic = _ic()
    sent = []
    fake_user32 = MagicMock()
    fake_user32.keybd_event.side_effect = lambda vk, *a, **k: sent.append(vk)
    fake_windll = MagicMock()
    fake_windll.user32 = fake_user32

    with patch("ctypes.windll", new=fake_windll), \
         patch("core.input_controller.pyautogui", new=MagicMock()), \
         patch.object(ic, "_ensure_window", return_value=True), \
         patch.object(ic, "_get_mode", return_value="foreground"), \
         patch.object(ic, "_wm", create=True) as mock_wm:
        mock_wm.set_foreground = MagicMock()
        ic.press_key("alt+f1")

    assert win32con.VK_MENU in sent, "前台未发送 alt(VK_MENU)"
    assert win32con.VK_F1 in sent, "前台未发送 f1(VK_F1)（合并前前台缺失 F 支持）"
