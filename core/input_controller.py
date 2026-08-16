# -*- coding: utf-8 -*-
"""
输入控制器模块。

提供 ``InputController`` 类（单例模式），负责：
    - 前台输入：使用 PyAutoGUI 模拟鼠标与键盘操作（窗口必须在前台）
    - 后台输入：使用 win32gui.PostMessage 发送窗口消息（窗口可在后台）
    - 统一接口：根据配置 ``window.input_mode`` 自动切换两种模式

坐标约定：
    - 所有 ``click`` / ``move_to`` 等方法接收的 ``x, y`` 均为 **客户区坐标**
    - 前台模式会通过 ``window_manager.client_to_screen`` 转换为屏幕坐标
    - 后台模式直接使用客户区坐标构造 lParam

使用方式::

    from core.input_controller import input_controller
    from core.window_manager import window_manager

    if window_manager.bind(title="梦幻西游"):
        input_controller.click(100, 200)              # 自动按配置选择前台/后台
        input_controller.press_key("alt+q")
        input_controller.type_text("你好")
"""
import time
import threading

import win32gui
import win32api
import win32con

try:
    import pyautogui
    # 关闭 pyautogui 的 failsafe（默认在屏幕左上角移动鼠标会抛异常），
    # 自动化场景下可能误触发，关闭更稳妥。如需安全保护可重新打开。
    pyautogui.FAILSAFE = False
except ImportError:
    pyautogui = None

from config.config import config
from utils.logger import logger


class InputController:
    """
    输入控制器（单例模式）。

    通过 ``_instance`` 与 ``_lock`` 实现线程安全的单例。
    使用时直接 ``from core.input_controller import input_controller`` 即可拿到全局实例。

    - 前台模式：依赖 ``pyautogui`` 与 ``window_manager``
    - 后台模式：依赖 ``win32gui.PostMessage`` 与 ``window_manager.hwnd``
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        # 线程安全的单例实现
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        # 仅初始化一次
        if getattr(self, "_initialized", False):
            return
        # 延迟导入避免循环依赖
        from core.window_manager import window_manager
        self._wm = window_manager
        self._initialized = True

    # ------------------------------------------------------------------
    # 模式判断
    # ------------------------------------------------------------------
    def _get_mode(self) -> str:
        """
        获取当前输入模式。

        从配置 ``window.input_mode`` 读取，未配置时默认为 ``"foreground"``。

        :return: str，"foreground" 或 "background"
        """
        mode = config.get("window.input_mode", "foreground")
        if mode not in ("foreground", "background"):
            logger.warning(f"未知的 input_mode={mode!r}，回退为 foreground")
            return "foreground"
        return mode

    def _ensure_window(self) -> bool:
        """检查窗口是否已绑定且有效，未绑定或失效返回 False。"""
        if not self._wm.is_valid():
            logger.warning("输入操作失败：未绑定有效窗口")
            return False
        return True

    # ==================================================================
    # 统一接口（对调用方暴露的 API）
    # ==================================================================
    def click(self, x, y, button="left", click_delay=0.0, press_delay=0.05):
        """
        点击鼠标（统一接口）。

        根据 ``config.get("window.input_mode")`` 自动选择前台或后台模式。

        :param x: 客户区 X 坐标
        :param y: 客户区 Y 坐标
        :param button: 鼠标按钮，"left" / "right" / "middle"
        :param click_delay: 点击前等待时间（秒），仅前台模式生效
        :param press_delay: 按下→弹起之间的保持时间（秒），仅后台模式生效。
            2026-08-05 新增：部分游戏要求按下保持 ≥30~50ms 才判定有效点击，
            且偶发失效可通过加大该值缓解；GUI 事件编辑器可配置。
        """
        if not self._ensure_window():
            return
        mode = self._get_mode()
        if mode == "background":
            self._post_click(x, y, button, press_delay=press_delay)
        else:
            self._click_foreground(x, y, button, click_delay)

    def double_click(self, x, y, click_delay=0.0):
        """
        双击鼠标（统一接口）。

        :param x: 客户区 X 坐标
        :param y: 客户区 Y 坐标
        :param click_delay: 点击前等待时间（秒）
        """
        if not self._ensure_window():
            return
        mode = self._get_mode()
        if mode == "background":
            # 后台模式：发送 WM_LBUTTONDBLCLK
            self._post_double_click(x, y)
        else:
            # 前台模式：先移动鼠标再双击
            if pyautogui is None:
                logger.error("pyautogui 未安装，无法使用前台模式")
                return
            screen_x, screen_y = self._wm.client_to_screen(x, y)
            self._wm.set_foreground()
            try:
                # 先移动鼠标到目标位置
                pyautogui.moveTo(screen_x, screen_y, duration=0.1)
                if click_delay:
                    time.sleep(click_delay)
                pyautogui.doubleClick(screen_x, screen_y)
                logger.debug(f"前台移动+双击 ({x},{y}) -> 屏幕({screen_x},{screen_y})")
            except Exception as e:
                logger.exception(f"前台双击失败: {e}")

    def right_click(self, x, y, click_delay=0.0):
        """
        右键点击鼠标（统一接口）。

        :param x: 客户区 X 坐标
        :param y: 客户区 Y 坐标
        :param click_delay: 点击前等待时间（秒）
        """
        if not self._ensure_window():
            return
        mode = self._get_mode()
        if mode == "background":
            self._post_click(x, y, "right")
        else:
            # 前台模式：先移动鼠标再右键点击
            self._click_foreground(x, y, "right", click_delay)

    def move_to(self, x, y, duration=0.1):
        """
        移动鼠标到客户区坐标（带平滑移动）。

        后台模式下无实际效果（PostMessage 不需要鼠标位置），仅记录日志。

        :param x: 客户区 X 坐标
        :param y: 客户区 Y 坐标
        :param duration: 移动持续时间（秒），默认 0.1 秒
        """
        if not self._ensure_window():
            return
        mode = self._get_mode()
        if mode == "background":
            # 后台模式不需要移动真实鼠标，直接返回
            logger.debug(f"后台模式忽略 move_to({x}, {y})")
            return
        # 前台模式：移动真实鼠标（带平滑移动）
        if pyautogui is None:
            logger.error("pyautogui 未安装，无法使用前台模式")
            return
        screen_x, screen_y = self._wm.client_to_screen(x, y)
        try:
            pyautogui.moveTo(screen_x, screen_y, duration=duration)
            logger.debug(f"前台移动鼠标到 ({x},{y}) -> 屏幕({screen_x},{screen_y})")
        except Exception as e:
            logger.exception(f"前台 move_to 失败: {e}")

    def press_key(self, keys):
        """
        按键（统一接口）。

        根据 ``window.input_mode`` 自动选择前台或后台模式。
        组合键格式：``"alt+q"``、``"ctrl+shift+s"`` 等，按键名不区分大小写。

        :param keys: 按键字符串，例如 ``"alt+q"``
        """
        if not self._ensure_window():
            return
        mode = self._get_mode()
        if mode == "background":
            # ALT 组合键不能用 PostMessage：PostMessage 只进消息队列，
            # 不更新系统键盘状态表（GetAsyncKeyState / GetKeyState 读不到
            # ALT 按下状态）→ 游戏组合键判断失败（实测 ALT+E 消息被收到
            # 但背包不触发）。keybd_event 是真实输入，更新状态表，
            # 但会注入到前台窗口 → 需要把游戏窗口置前台（会抢焦点）。
            has_alt = "alt" in [p.strip().lower() for p in keys.split("+") if p.strip()]
            if has_alt:
                logger.info(f"ALT 组合键 {keys!r}：PostMessage 无法模拟键盘状态，"
                            f"降级 SendInput 真实注入（游戏窗口将置前台）")
                self._press_key_foreground(keys)
                return
            self._post_key(keys)
        else:
            self._press_key_foreground(keys)

    def type_text(self, text, interval=0.1):
        """
        输入文本（统一接口）。

        根据 ``window.input_mode`` 自动选择前台或后台模式。

        :param text: 要输入的文本（支持中文，前台模式中文支持依赖 pyautogui 版本）
        :param interval: 字符间间隔（秒），仅前台模式生效
        """
        if not text:
            return
        if not self._ensure_window():
            return
        mode = self._get_mode()
        if mode == "background":
            self._post_text(text)
        else:
            self._type_text_foreground(text, interval)

    def scroll(self, amount, x=None, y=None):
        """
        滚轮操作。

        前台模式：使用 pyautogui.vscroll。
        后台模式：发送 WM_MOUSEWHEEL 消息（部分应用可能不响应）。

        :param amount: 滚动量，正数向上，负数向下
        :param x: 客户区 X 坐标，可选，None 表示当前位置
        :param y: 客户区 Y 坐标，可选，None 表示当前位置
        """
        if not self._ensure_window():
            return
        mode = self._get_mode()
        if mode == "background":
            self._post_scroll(amount, x, y)
        else:
            self._scroll_foreground(amount, x, y)

    # ==================================================================
    # 前台模式实现（pyautogui）
    # ==================================================================
    def _click_foreground(self, x, y, button="left", click_delay=0.0, move_duration=0.1):
        """前台点击：先移动鼠标到目标位置，再点击。"""
        if pyautogui is None:
            logger.error("pyautogui 未安装，无法使用前台模式")
            return
        # 客户区坐标转屏幕坐标
        screen_x, screen_y = self._wm.client_to_screen(x, y)
        # 确保窗口在前台
        self._wm.set_foreground()
        try:
            # 先移动鼠标到目标位置（带平滑移动）
            pyautogui.moveTo(screen_x, screen_y, duration=move_duration)
            # 可选的点击前等待
            if click_delay:
                time.sleep(click_delay)
            # 执行点击
            pyautogui.click(screen_x, screen_y, button=button)
            logger.debug(f"前台移动+点击 ({x},{y}) -> 屏幕({screen_x},{screen_y}) 按钮={button}")
        except Exception as e:
            logger.exception(f"前台点击失败: {e}")

    def _force_foreground(self, hwnd: int) -> bool:
        """绕过 Windows 前台锁强制切换前台（AttachThreadInput + ALT hack）。

        前台锁规则：只有前台进程才有权 SetForegroundWindow。ALT hack 通过
        模拟 ALT 按下让系统认为本进程有输入活动，从而解除锁限制。
        """
        if not hwnd:
            return False
        try:
            import ctypes
            user32 = ctypes.windll.user32
            fg_tid = 0
            target_tid = 0
            try:
                fg_hwnd = win32gui.GetForegroundWindow()
                fg_tid = win32process.GetWindowThreadProcessId(fg_hwnd)[0]
                target_tid = win32process.GetWindowThreadProcessId(hwnd)[0]
            except Exception:
                pass
            attached = False
            if fg_tid and target_tid and fg_tid != target_tid:
                try:
                    win32process.AttachThreadInput(fg_tid, target_tid, True)
                    attached = True
                except Exception:
                    pass
            # ALT hack：模拟 ALT 按下解除前台锁
            user32.keybd_event(0x12, 0, 0, 0)          # VK_MENU down
            win32gui.SetForegroundWindow(hwnd)
            time.sleep(0.03)
            user32.keybd_event(0x12, 0, 0x0002, 0)     # VK_MENU up
            if attached:
                try:
                    win32process.AttachThreadInput(fg_tid, target_tid, False)
                except Exception:
                    pass
            return win32gui.GetForegroundWindow() == hwnd
        except Exception as e:
            logger.warning(f"_force_foreground 失败 hwnd={hwnd}: {e}")
            return False

    def _ensure_foreground(self, retries: int = 3) -> bool:
        """确保游戏窗口真正在前台（带校验，失败重试）。

        SetForegroundWindow 受 Windows 前台锁限制可能"假成功"（返回 0 但未切换），
        这里通过 GetForegroundWindow 实际校验，避免 keybd_event/SendInput
        注入到别的窗口导致按键无效。

        前台锁绕过（2026-08-09 新增）：常规重试失败后，用"模拟 ALT 键按下"
        hack——发送一个 ALT 按下事件让 Windows 认为本进程有输入活动，
        从而解除前台锁限制，随后 SetForegroundWindow 成功率大幅提升。

        :param retries: 常规重试次数
        :return: bool，是否确认游戏窗口为当前前台
        """
        for i in range(retries):
            self._wm.set_foreground()
            time.sleep(0.12)  # 等焦点切换稳定
            try:
                if win32gui.GetForegroundWindow() == self._wm.hwnd:
                    return True
            except Exception:
                pass
            time.sleep(0.1)

        # 最终尝试：ALT 键 hack 绕过前台锁（复用 _force_foreground）
        try:
            if self._force_foreground(self._wm.hwnd):
                time.sleep(0.15)
                if win32gui.GetForegroundWindow() == self._wm.hwnd:
                    logger.info("前台切换成功（ALT hack 绕过前台锁）")
                    return True
        except Exception as e:
            logger.warning(f"ALT hack 切换前台失败: {e}")

        logger.warning(f"_ensure_foreground 失败: 重试 {retries} 次 + ALT hack 后游戏窗口仍未成为前台")
        return False

    def _press_key_foreground(self, keys):
        """前台按键：用 SendInput 注入组合键（VK 模式 + 焦点校验）。

        实测结论（2026-08-09）：梦幻类游戏对 SCANCODE 模式不响应（注入成功
        但 GetAsyncKeyState 已按下但游戏不识别为 ALT 组合键），VK 模式有效。
        因此默认使用 VK 模式，wScan=0。

        流程：置前台+校验 → 按下修饰键→普通键（各间隔100ms）→ 逆序释放
        """
        # 解析组合键
        parts = [p.strip().lower() for p in keys.split("+") if p.strip()]
        if not parts:
            logger.warning(f"press_key 解析为空: keys={keys!r}")
            return
        # 记录注入前的前台窗口（必须在 _ensure_foreground 置游戏前台之前！
        # 否则此时前台已是游戏，归还条件失效）
        prev_fg = 0
        try:
            prev_fg = win32gui.GetForegroundWindow()
        except Exception:
            pass
        # 焦点校验：确保游戏窗口真正在前台
        # 2026-08-09 修复：校验失败不放弃注入（GUI 环境受 Windows 前台锁限制，
        # set_foreground 可能"假成功"，但放弃注入 = 100% 失败；继续注入则可能生效，
        # 且 SendInput 注入本身可能把焦点带向游戏）。降级为警告 + 继续。
        if not self._ensure_foreground():
            logger.warning(f"游戏窗口未确认在前台（keys={keys!r}），仍尝试注入")
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32

            # 虚拟键码映射
            VK_MAP = {
                'alt': 0x12,       # VK_MENU
                'ctrl': 0x11,      # VK_CONTROL
                'control': 0x11,
                'shift': 0x10,     # VK_SHIFT
                'win': 0x5B,       # VK_LWIN
                'tab': 0x09,
                'enter': 0x0D,
                'return': 0x0D,
                'esc': 0x1B,
                'escape': 0x1B,
                'space': 0x20,
                'backspace': 0x08,
                'delete': 0x2E,
                'del': 0x2E,
                'up': 0x26,
                'down': 0x28,
                'left': 0x25,
                'right': 0x27,
                'home': 0x24,
                'end': 0x23,
                'pageup': 0x21,
                'pagedown': 0x22,
                'f1': 0x70, 'f2': 0x71, 'f3': 0x72, 'f4': 0x73,
                'f5': 0x74, 'f6': 0x75, 'f7': 0x76, 'f8': 0x77,
                'f9': 0x78, 'f10': 0x79, 'f11': 0x7A, 'f12': 0x7B,
            }
            KEYEVENTF_KEYUP = 0x0002
            INPUT_KEYBOARD = 1

            # ---- INPUT 结构定义（64 位，union 必须含 MOUSE/HARDWAREINPUT） ----
            ULONG_PTR = ctypes.POINTER(ctypes.c_ulong)

            class MOUSEINPUT(ctypes.Structure):
                _fields_ = [
                    ('dx', wintypes.LONG),
                    ('dy', wintypes.LONG),
                    ('mouseData', wintypes.DWORD),
                    ('dwFlags', wintypes.DWORD),
                    ('time', wintypes.DWORD),
                    ('dwExtraInfo', ULONG_PTR),
                ]

            class KEYBDINPUT(ctypes.Structure):
                _fields_ = [
                    ('wVk', wintypes.WORD),
                    ('wScan', wintypes.WORD),
                    ('dwFlags', wintypes.DWORD),
                    ('time', wintypes.DWORD),
                    ('dwExtraInfo', ULONG_PTR),
                ]

            class HARDWAREINPUT(ctypes.Structure):
                _fields_ = [
                    ('uMsg', wintypes.DWORD),
                    ('wParamL', wintypes.WORD),
                    ('wParamH', wintypes.WORD),
                ]

            class INPUT(ctypes.Structure):
                class _U(ctypes.Union):
                    _fields_ = [
                        ('mi', MOUSEINPUT),
                        ('ki', KEYBDINPUT),
                        ('hi', HARDWAREINPUT),
                    ]
                _anonymous_ = ('_u',)
                _fields_ = [('type', wintypes.DWORD), ('_u', _U)]

            user32.SendInput.restype = wintypes.UINT
            user32.SendInput.argtypes = [
                wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]

            # ---- 解析按键 → 虚拟键码 ----
            vk_codes = []
            for p in parts:
                if p in VK_MAP:
                    vk_codes.append(VK_MAP[p])
                elif len(p) == 1:
                    vk = user32.VkKeyScanW(ord(p)) & 0xFF
                    vk_codes.append(vk)
                else:
                    logger.warning(f"无法识别按键: {p!r}（来源 keys={keys!r}）")
                    return

            KEY_DELAY = 0.1  # 按键间隔（实测 100ms 比 50ms 稳定）

            def _send(vk, up=False):
                """SendInput 发送单键事件（VK 模式）。"""
                inp = INPUT()
                inp.type = INPUT_KEYBOARD
                inp.ki.wVk = vk
                inp.ki.wScan = 0
                inp.ki.dwFlags = KEYEVENTF_KEYUP if up else 0
                inp.ki.time = 0
                inp.ki.dwExtraInfo = None
                sent = user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
                if sent != 1:
                    err = ctypes.get_last_error()
                    logger.warning(f"SendInput 失败 vk=0x{vk:x} err={err}")

            # 按下（修饰键在前）
            for vk in vk_codes:
                _send(vk)
                time.sleep(KEY_DELAY)
            # 释放（逆序）
            for vk in reversed(vk_codes):
                _send(vk, up=True)
                time.sleep(KEY_DELAY)

            logger.info(f"前台按键: {keys!r} -> vk={[hex(v) for v in vk_codes]}")

            # 注入完成后归还焦点到原窗口（默认开启，可通过 input.restore_focus_after_key 关闭）
            # 2026-08-09 新增：ALT 组合键必须置游戏前台注入，但注入完立即把焦点
            # 还给用户原来的窗口，避免长期占用用户前台。
            # 归还同样受前台锁限制（此时游戏是前台），用 _force_foreground 绕过。
            # 2026-08-16 优化：归还延迟 0.15s→0.08s（更快无感），归还失败重试 1 次。
            try:
                restore = config.get("input.restore_focus_after_key", True)
                if restore and prev_fg and prev_fg != self._wm.hwnd:
                    time.sleep(0.08)  # 等游戏消化输入（实测 80ms 足够）
                    if win32gui.IsWindow(prev_fg):
                        restored = self._force_foreground(prev_fg)
                        if not restored:
                            # 归还失败重试一次（前台锁抖动场景）
                            time.sleep(0.05)
                            restored = self._force_foreground(prev_fg)
                        if restored:
                            logger.debug(f"已归还焦点到原窗口 hwnd={prev_fg}")
                        else:
                            logger.warning(f"归还焦点失败（重试后）prev_fg={prev_fg}")
            except Exception:
                pass
        except Exception as e:
            logger.exception(f"前台按键失败: {e}")
            # 回退到 pyautogui（已知对梦幻有效）
            try:
                if pyautogui is not None:
                    pyautogui.hotkey(*parts)
                    logger.info(f"前台按键(pyautogui回退): {keys!r}")
            except Exception as e2:
                logger.exception(f"pyautogui回退也失败: {e2}")

    def _type_text_foreground(self, text, interval=0.1):
        """前台输入文本：用 pyautogui.typewrite。"""
        if pyautogui is None:
            logger.error("pyautogui 未安装，无法使用前台模式")
            return
        # 确保窗口在前台
        self._wm.set_foreground()
        try:
            # typewrite 对纯 ASCII 直接可用；对中文等非 ASCII 字符，
            # pyautogui 会回退使用 clipboard 粘贴（write 仅支持 ASCII）。
            # 这里直接用 typewrite，由 pyautogui 处理。
            pyautogui.typewrite(text, interval=interval)
            logger.debug(f"前台输入文本: {text!r}")
        except Exception as e:
            logger.exception(f"前台输入文本失败: {e}")

    def _scroll_foreground(self, amount, x=None, y=None):
        """前台滚轮：用 pyautogui.vscroll。"""
        if pyautogui is None:
            logger.error("pyautogui 未安装，无法使用前台模式")
            return
        try:
            if x is not None and y is not None:
                screen_x, screen_y = self._wm.client_to_screen(x, y)
                pyautogui.moveTo(screen_x, screen_y)
            pyautogui.vscroll(amount)
            logger.debug(f"前台滚轮: amount={amount}, ({x},{y})")
        except Exception as e:
            logger.exception(f"前台滚轮失败: {e}")

    # ==================================================================
    # 后台模式实现（win32gui.PostMessage）
    # ==================================================================
    # 鼠标消息常量
    WM_MOUSEMOVE = 0x0200
    WM_LBUTTONDOWN = 0x0201
    WM_LBUTTONUP = 0x0202
    WM_LBUTTONDBLCLK = 0x0203
    WM_RBUTTONDOWN = 0x0204
    WM_RBUTTONUP = 0x0205
    WM_MBUTTONDOWN = 0x0207
    WM_MBUTTONUP = 0x0208
    # 键盘消息常量
    WM_KEYDOWN = 0x0100
    WM_KEYUP = 0x0101
    WM_CHAR = 0x0102
    WM_SYSKEYDOWN = 0x0104
    WM_SYSKEYUP = 0x0105
    WM_MOUSEWHEEL = 0x020A

    # 鼠标按钮 -> (DOWN 消息, UP 消息) 映射
    _MOUSE_MSG_MAP = {
        "left": (WM_LBUTTONDOWN, WM_LBUTTONUP),
        "right": (WM_RBUTTONDOWN, WM_RBUTTONUP),
        "middle": (WM_MBUTTONDOWN, WM_MBUTTONUP),
    }
    # 鼠标按钮 -> DOWN 消息的 wparam（MK_ 标志）。
    # Windows 约定 WM_LBUTTONDOWN wparam=MK_LBUTTON(1)、右键=MK_RBUTTON(2)、
    # 中键=MK_MBUTTON(4)；wparam=0 会被很多程序（含游戏）忽略 → 点击无效。
    # 2026-08-05 修复：之前简化为 0，后台分支左键/右键可能全部失效。
    _MOUSE_DOWN_WPARAM = {
        "left": 0x0001,
        "right": 0x0002,
        "middle": 0x0004,
    }

    @staticmethod
    def _make_mouse_lparam(x, y):
        """
        构造鼠标消息的 lParam。

        格式：低 16 位为 X，高 16 位为 Y（客户区坐标）。

        :param x: 客户区 X 坐标
        :param y: 客户区 Y 坐标
        :return: int，lParam 值
        """
        # 对负坐标做截断保护（PostMessage 需要无符号 16 位）
        return (y << 16) | (x & 0xFFFF)

    def _post_message(self, msg, wparam, lparam):
        """封装 win32gui.PostMessage，统一异常处理。"""
        hwnd = self._wm.hwnd
        if not hwnd:
            logger.warning("PostMessage 失败：未绑定窗口句柄")
            return False
        try:
            win32gui.PostMessage(hwnd, msg, wparam, lparam)
            return True
        except Exception as e:
            logger.exception(f"PostMessage(msg=0x{msg:X}) 失败: {e}")
            return False

    def _sync_cursor(self, x, y) -> None:
        """
        光标同步（2026-08-16）：PostMessage 点击前让游戏读到目标光标位置。

        ⚠️ 2026-08-16 方案变更：GetCursorPos IAT hook 方案已废弃（实测导致
        游戏全部闪退——galaxy2d.dll 的 GetCursorPos 是运行时 GetProcAddress
        动态解析，内存扫描把 DATA 节普通指针误当 IAT 槽，重定向破坏游戏内存）。
        现在只保留 **SetCursorPos 瞬移（方案 A）**：
        瞬移物理光标到目标屏幕坐标（不激活窗口、不抢焦点），解决
        GetCursorPos 命中检测失效。物理光标会短暂跳到目标点，但点击由
        PostMessage 完成、窗口保持后台。
        2026-08-16 借出即还：调用方（_post_click/_post_double_click）在
        点击前用 _borrow_cursor 记录原位，点击完成后 _restore_cursor 归还，
        光标不滞留在游戏窗口。

        :param x: 客户区 X 坐标
        :param y: 客户区 Y 坐标
        """
        try:
            sx, sy = self._wm.client_to_screen(x, y)
            win32api.SetCursorPos((int(sx), int(sy)))
        except Exception as e:
            logger.debug(f"光标同步失败（不影响点击）: {e}")

    def _borrow_cursor(self, x, y):
        """
        光标借出：记录当前位置并瞬移到目标点，返回原位坐标供归还。

        2026-08-16 用户反馈"抢鼠标"——SetCursorPos 把光标拉进游戏窗口后
        滞留，用户正在操作别处时被打断。改为"借出即还"：点击前记录原位，
        点击完成后归还。若用户中途移动了鼠标（光标不在目标点附近），
        归还时尊重用户新位置，不覆盖。

        :param x: 客户区 X 坐标
        :param y: 客户区 Y 坐标
        :return: (orig_x, orig_y, target_sx, target_sy) 或 None
        """
        try:
            orig = win32api.GetCursorPos()
            sx, sy = self._wm.client_to_screen(x, y)
            win32api.SetCursorPos((int(sx), int(sy)))
            time.sleep(0.02)  # 等光标移动生效
            return (int(orig[0]), int(orig[1]), int(sx), int(sy))
        except Exception as e:
            logger.debug(f"光标借出失败（不影响点击）: {e}")
            return None

    def _restore_cursor(self, borrowed) -> None:
        """
        光标归还：点击完成后把光标放回原位。

        若用户已移动鼠标到别处（当前位置远离目标点），则不覆盖用户操作。
        """
        if not borrowed:
            return
        try:
            orig_x, orig_y, tgt_x, tgt_y = borrowed
            cur = win32api.GetCursorPos()
            # 只有光标还停留在目标点附近（用户没动）才归还，避免抢用户正在用的鼠标
            if abs(cur[0] - tgt_x) <= 3 and abs(cur[1] - tgt_y) <= 3:
                win32api.SetCursorPos((orig_x, orig_y))
                logger.debug(f"光标已归还原位 ({orig_x},{orig_y})")
            else:
                logger.debug("用户已移动鼠标，跳过归还（尊重用户位置）")
        except Exception as e:
            logger.debug(f"光标归还失败（不影响点击）: {e}")

    def _post_click(self, x, y, button="left", press_delay=0.05):
        """
        后台点击：发送 DOWN + UP 消息。

        :param x: 客户区 X 坐标
        :param y: 客户区 Y 坐标
        :param button: "left" / "right" / "middle"
        :param press_delay: 按下→弹起保持时间（秒），默认 50ms。
            2026-08-05 支持 GUI 配置（事件编辑器"按下延迟"），
            偶发点击失效可调大到 100~300ms。
        """
        down_up = self._MOUSE_MSG_MAP.get(button.lower())
        if down_up is None:
            logger.warning(f"未知的鼠标按钮: {button!r}")
            return
        down_msg, up_msg = down_up
        lparam = self._make_mouse_lparam(x, y)
        # 2026-08-05 坐标有效性检查：点击坐标超出客户区 → 点在窗口外，
        # 游戏收不到（PostMessage 照发但无效果），提前警告避免误以为"失效"。
        try:
            cw, ch = self._wm.get_client_size()
            if cw and ch and not (0 <= int(x) < cw and 0 <= int(y) < ch):
                logger.warning(
                    f"后台点击坐标超出客户区 ({x},{y}) 客户区 {cw}x{ch}，点击将被忽略"
                )
                return
        except Exception:
            pass
        # 2026-08-16 光标借出（方案 A）：记录原位并瞬移到目标点，解决
        # GetCursorPos 命中检测失效；点击完成后归还原位。
        # ⚠️ 2026-08-16 用户硬性要求：光标绝不允许出现在游戏里（一点点都不行）。
        # 默认改为 **纯 PostMessage（cursor_sync_click=false，光标完全不动）**。
        # 仅当纯 PostMessage 在新客户端实测失效时才开启（此时光标会闪入游戏）。
        borrowed = None
        try:
            if config.get("input.cursor_sync_click", False):
                borrowed = self._borrow_cursor(x, y)
        except Exception:
            pass
        # 2026-08-05 可靠性强化（解决"偶发点击失效"）：
        # 1) MOUSEMOVE 发 2 次（间隔 10ms）——确保游戏建立 hover 状态
        #    （部分 UI 需 hover 才响应 DOWN，如传送菜单项）；
        # 2) DOWN 后按下保持 50ms —— 部分游戏要求按下时长 ≥30~50ms
        #    才判定"有效按下"，20ms 太快会被当抖动忽略；
        # 3) DOWN 发送失败自动重试 1 次（防消息偶发丢弃）。
        for _ in range(2):
            self._post_message(self.WM_MOUSEMOVE, 0, lparam)
            time.sleep(0.01)
        down_wparam = self._MOUSE_DOWN_WPARAM.get(button.lower(), 0)
        ok = self._post_message(down_msg, down_wparam, lparam)
        if not ok:
            # DOWN 失败：重试一次
            time.sleep(0.03)
            ok = self._post_message(down_msg, down_wparam, lparam)
        if ok:
            # 按下保持 press_delay 再抬起（模拟真实按住时长，可 GUI 配置）
            time.sleep(max(0.0, float(press_delay or 0.0)))
            self._post_message(up_msg, 0, lparam)
        # 光标归还原位（借出即还，不抢用户鼠标）
        if borrowed:
            self._restore_cursor(borrowed)
        logger.debug(f"后台点击 ({x},{y}) 按钮={button}")

    def _post_double_click(self, x, y):
        """后台双击：发送 DOWN -> UP -> DBLCLK -> UP 序列。"""
        lparam = self._make_mouse_lparam(x, y)
        lparam = self._make_mouse_lparam(x, y)
        # 2026-08-16 光标借出（方案 A，同单击）；双击结束后归还。
        # 默认纯 PostMessage（cursor_sync_click=false，光标完全不动）
        borrowed = None
        try:
            if config.get("input.cursor_sync_click", False):
                borrowed = self._borrow_cursor(x, y)
        except Exception:
            pass
        # 先移动鼠标到目标位置（与单击一致，部分 UI 需 hover 状态）
        self._post_message(self.WM_MOUSEMOVE, 0, lparam)
        time.sleep(0.01)
        # 双击标准序列：DOWN(MK_LBUTTON) -> UP -> DBLCLK -> UP
        self._post_message(self.WM_LBUTTONDOWN, self._MOUSE_DOWN_WPARAM["left"], lparam)
        time.sleep(0.02)
        self._post_message(self.WM_LBUTTONUP, 0, lparam)
        time.sleep(0.02)
        self._post_message(self.WM_LBUTTONDBLCLK, self._MOUSE_DOWN_WPARAM["left"], lparam)
        time.sleep(0.02)
        self._post_message(self.WM_LBUTTONUP, 0, lparam)
        if borrowed:
            self._restore_cursor(borrowed)
        logger.debug(f"后台双击 ({x},{y})")

    def _post_scroll(self, amount, x=None, y=None):
        """
        后台滚轮：发送 WM_MOUSEWHEEL。

        :param amount: 滚动量（单位为滚轮"格"，会乘以 WHEEL_DELTA=120）
        :param x: 客户区 X 坐标，可选
        :param y: 客户区 Y 坐标，可选
        """
        # wParam 高 16 位为滚动量（WHEEL_DELTA=120），低 16 位为按键状态
        wheel_delta = 120
        wparam = (int(amount) * wheel_delta) & 0xFFFF
        # lParam：低 16 位屏幕 X，高 16 位屏幕 Y
        # 注：WM_MOUSEWHEEL 的坐标是屏幕坐标，需要转换
        if x is not None and y is not None:
            sx, sy = self._wm.client_to_screen(x, y)
        else:
            # 默认使用客户区左上角
            rect = self._wm.get_client_rect()
            sx, sy = rect[0], rect[1]
        lparam = (sy << 16) | (sx & 0xFFFF)
        # 先移动鼠标到目标位置（滚轮按悬停位置滚动，需先 hover 目标）
        if x is not None and y is not None:
            self._post_message(self.WM_MOUSEMOVE, 0, self._make_mouse_lparam(x, y))
            time.sleep(0.01)
        self._post_message(self.WM_MOUSEWHEEL, wparam, lparam)
        logger.debug(f"后台滚轮 amount={amount} 屏幕({sx},{sy})")

    # ------------------------------------------------------------------
    # 键盘：按键名 -> 虚拟键码
    # ------------------------------------------------------------------
    # 特殊键名到虚拟键码的映射（按键名统一小写）
    _SPECIAL_VK = {
        "ctrl": win32con.VK_CONTROL,
        "control": win32con.VK_CONTROL,
        "alt": win32con.VK_MENU,
        "menu": win32con.VK_MENU,
        "shift": win32con.VK_SHIFT,
        "win": win32con.VK_LWIN,
        "enter": win32con.VK_RETURN,
        "return": win32con.VK_RETURN,
        "tab": win32con.VK_TAB,
        "esc": win32con.VK_ESCAPE,
        "escape": win32con.VK_ESCAPE,
        "space": win32con.VK_SPACE,
        "backspace": win32con.VK_BACK,
        "bs": win32con.VK_BACK,
        "delete": win32con.VK_DELETE,
        "del": win32con.VK_DELETE,
        "up": win32con.VK_UP,
        "down": win32con.VK_DOWN,
        "left": win32con.VK_LEFT,
        "right": win32con.VK_RIGHT,
        "home": win32con.VK_HOME,
        "end": win32con.VK_END,
        "pageup": win32con.VK_PRIOR,
        "pgup": win32con.VK_PRIOR,
        "pagedown": win32con.VK_NEXT,
        "pgdn": win32con.VK_NEXT,
        "insert": win32con.VK_INSERT,
        "ins": win32con.VK_INSERT,
        "capslock": win32con.VK_CAPITAL,
        "numlock": win32con.VK_NUMLOCK,
        "scrolllock": win32con.VK_SCROLL,
    }

    def _key_to_vk(self, key):
        """
        把按键名（小写）转换为 Windows 虚拟键码。

        :param key: 按键名，例如 "a"、"f1"、"ctrl"、"enter"
        :return: int 虚拟键码，无法识别返回 None
        """
        if not key:
            return None
        k = key.strip().lower()
        # 特殊键查表
        if k in self._SPECIAL_VK:
            return self._SPECIAL_VK[k]
        # 功能键 F1-F12
        if k.startswith("f") and k[1:].isdigit():
            n = int(k[1:])
            if 1 <= n <= 12:
                return win32con.VK_F1 + n - 1
        # 单字符
        if len(k) == 1:
            # 字母 A-Z：VK 码与大写字母 ASCII 相同
            if "a" <= k <= "z":
                return ord(k.upper())
            # 数字 0-9：VK 码与 ASCII 相同
            if "0" <= k <= "9":
                return ord(k)
            # 其他符号：用 VkKeyScan 获取
            try:
                # VkKeyScan 返回低 8 位为 VK 码，高位为 Shift/Ctrl/Alt 状态
                return win32api.VkKeyScan(k) & 0xFF
            except Exception:
                return None
        return None

    def _post_key(self, keys):
        """
        后台按键：解析 "alt+q" 这样的组合键。

        按顺序发送 KEYDOWN（带 ALT 时使用 SYSKEYDOWN），然后反序发送 KEYUP。
        组合键内各键之间留有短间隔，避免漏消息。

        :param keys: 按键字符串，例如 "alt+q"、"ctrl+shift+s"、"f1"
        """
        if not keys:
            return
        # 分割组合键
        parts = [p.strip().lower() for p in keys.split("+") if p.strip()]
        if not parts:
            logger.warning(f"_post_key 解析为空: keys={keys!r}")
            return

        # 解析每个按键的 VK 码
        vk_codes = []
        for p in parts:
            vk = self._key_to_vk(p)
            if vk is None:
                logger.warning(f"_post_key 无法识别按键: {p!r}（来源 keys={keys!r}）")
                return
            vk_codes.append(vk)

        # 是否包含 ALT 修饰键
        has_alt = win32con.VK_MENU in vk_codes

        # 按顺序发送 KEYDOWN
        n = len(vk_codes)
        for i, vk in enumerate(vk_codes):
            # 最后一键若伴随 ALT，使用 WM_SYSKEYDOWN；ALT 键本身也用 SYSKEYDOWN
            if vk == win32con.VK_MENU or (has_alt and i == n - 1):
                msg = self.WM_SYSKEYDOWN
            else:
                msg = self.WM_KEYDOWN
            # lParam：低位 16 位为重复次数（1），高位为扫描码（这里用 0 简化）。
            # 伴随 ALT 的键（非 ALT 本身）必须带 bit29=0x20000000（Alt 按下标志），
            # 否则程序按 lParam 判定"Alt 未按下"会忽略该 SYSKEYDOWN。
            lparam = 0x00000001
            if msg == self.WM_SYSKEYDOWN and vk != win32con.VK_MENU:
                lparam |= 0x20000000
            self._post_message(msg, vk, lparam)
            # 短间隔，保证目标应用按顺序处理消息
            time.sleep(0.01)

        # 反序发送 KEYUP
        for i in range(n - 1, -1, -1):
            vk = vk_codes[i]
            if vk == win32con.VK_MENU or (has_alt and i == n - 1):
                msg = self.WM_SYSKEYUP
            else:
                msg = self.WM_KEYUP
            # KEYUP 的 lParam：bit 31=1（表示从按下到释放），重复次数 1。
            # 伴随 ALT 的键 UP 同样带 bit29（Alt 仍按下直到 ALT 自身 UP）。
            lparam = 0xC0000001
            if msg == self.WM_SYSKEYUP and vk != win32con.VK_MENU:
                lparam |= 0x20000000
            self._post_message(msg, vk, lparam)
            time.sleep(0.01)
        logger.debug(f"后台按键: {keys!r} -> vk={[hex(v) for v in vk_codes]}")

    def _post_text(self, text):
        """
        后台输入文本：对每个字符发送 WM_CHAR 消息。

        WM_CHAR 的 wParam 为字符的 Unicode 码点，lParam 重复次数 1。

        :param text: 要输入的文本，支持中文
        """
        for ch in text:
            # wParam 为字符 Unicode 码点
            wparam = ord(ch)
            lparam = 0x00000001
            self._post_message(self.WM_CHAR, wparam, lparam)
            # 短间隔避免漏字符
            time.sleep(0.01)
        logger.debug(f"后台输入文本: {text!r}（{len(text)} 字符）")


# 模块级单例实例，供全局使用
input_controller = InputController()
