# -*- coding: utf-8 -*-
"""
窗口管理器模块。

提供 ``WindowManager`` 类（单例模式），负责：
    - 按标题 / PID 查找游戏窗口
    - 绑定窗口并维护客户区矩形（client_rect）与尺寸（client_size）
    - 客户区坐标 ↔ 屏幕坐标 转换
    - 将窗口置前
    - 检查窗口有效性

底层使用 pywin32（win32gui / win32con / win32process）实现。

client_rect 约定：tuple (left, top, right, bottom)，屏幕绝对坐标。
client_size 约定：tuple (width, height)。

使用方式::

    from core.window_manager import window_manager

    if window_manager.bind(title="梦幻西游"):
        window_manager.set_foreground()
        rect = window_manager.get_client_rect()      # (left, top, right, bottom)
        size = window_manager.get_client_size()      # (width, height)
"""
import threading
from ctypes import WINFUNCTYPE, wintypes

import win32gui
import win32con
import win32process

# WNDENUMPROC 回调类型（EnumWindows / EnumChildWindows 需要）
WNDENUMPROC = WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

from config.config import config
from utils.logger import logger


class WindowManager:
    """
    窗口管理器（单例模式）。

    通过 ``_instance`` 与 ``_lock`` 实现线程安全的单例。
    使用时直接 ``from core.window_manager import window_manager`` 即可拿到全局实例。
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
        # 当前绑定的窗口句柄（0 表示未绑定）
        self.hwnd = 0
        # 窗口标题
        self.window_title = ""
        # 进程 ID（0 表示未绑定）
        self.pid = 0
        # 客户区矩形 (left, top, right, bottom)，屏幕绝对坐标
        self.client_rect = (0, 0, 0, 0)
        # 客户区尺寸 (width, height)
        self.client_size = (0, 0)
        self._initialized = True

    # ------------------------------------------------------------------
    # 查找与绑定
    # ------------------------------------------------------------------
    def _find_pid_windows(self, pid, matched):
        """
        内部：按 PID 收集所有候选窗口到 matched 列表。

        两轮扫描：
          1. 顶层可见且有标题的窗口（传统独立客户端结构）。
          2. 若第 1 轮无命中，遍历所有顶层窗口的**子窗口**（含隐藏）。
             ★ 多开器结构（如 十年一梦多开器.exe）：游戏主窗口
             ``Galaxy2DEngine`` 是多开器空标题 ``WTWindow`` 容器的子窗口，
             但归属游戏进程自己的 PID，只有靠子窗口枚举才能找到。

        :param pid: 进程 ID
        :param matched: 输出列表 [(hwnd, title, client_area), ...]
        """
        def _match_one(hwnd, allow_child=False):
            """匹配单个窗口，命中返回 (hwnd, title, area)，否则 None。"""
            try:
                _, win_pid = win32process.GetWindowThreadProcessId(hwnd)
            except Exception:
                return None
            if win_pid != pid:
                return None
            try:
                win_title = win32gui.GetWindowText(hwnd)
            except Exception:
                win_title = ""
            # 顶层窗口要求非空标题；子窗口（多开器内嵌）不要求
            if not allow_child and not win_title:
                return None
            if not allow_child and not win32gui.IsWindowVisible(hwnd):
                return None
            try:
                rect = win32gui.GetClientRect(hwnd)
                w = rect[2] - rect[0]
                h = rect[3] - rect[1]
                area = w * h
            except Exception:
                area = 0
            return (int(hwnd), win_title, int(area))

        # 第 1 轮：顶层窗口
        top_hwnds = []

        def _enum_top(hwnd, _):
            top_hwnds.append(hwnd)
            return True

        try:
            win32gui.EnumWindows(WNDENUMPROC(_enum_top), 0)
        except Exception as e:
            logger.error(f"EnumWindows 枚举顶层窗口失败: {e}")
            return

        for hwnd in top_hwnds:
            m = _match_one(hwnd, allow_child=False)
            if m:
                matched.append(m)

        if matched:
            return

        # 第 2 轮：子窗口回退（多开器容器结构）
        for parent in top_hwnds:
            def _enum_child(child, _lp):
                m = _match_one(child, allow_child=True)
                if m:
                    matched.append(m)
                return True
            try:
                win32gui.EnumChildWindows(parent, WNDENUMPROC(_enum_child), 0)
            except Exception:
                continue
            if matched:
                # 同一容器的子树已找到目标，无需继续扫描其余容器
                break

    def find_by_title(self, title):
        """
        按标题子串查找窗口并绑定。

        使用 EnumWindows 遍历所有可见窗口，进行子串模糊匹配，
        取第一个匹配的窗口绑定。

        :param title: 窗口标题子串
        :return: bool，是否找到并绑定成功。
        """
        if not title:
            logger.error("find_by_title 未提供 title 参数")
            return False

        matched = []

        def _enum_cb(hwnd, _):
            # 仅处理可见窗口（回调必须返回 True 继续枚举）
            if not win32gui.IsWindowVisible(hwnd):
                return True
            try:
                win_title = win32gui.GetWindowText(hwnd)
            except Exception:
                win_title = ""
            # 标题为空的窗口直接跳过
            if not win_title:
                return True
            if title in win_title:
                matched.append((hwnd, win_title))
            return True

        try:
            win32gui.EnumWindows(_enum_cb, None)
        except Exception as e:
            logger.error(f"EnumWindows 枚举窗口失败: {e}")
            return False

        if not matched:
            logger.error(f"未找到标题包含 {title!r} 的窗口")
            return False

        hwnd, win_title = matched[0]
        logger.info(f"find_by_title 命中: hwnd=0x{hwnd:X}, title={win_title!r}")
        return self._bind_hwnd(hwnd)

    def find_by_pid(self, pid):
        """
        按 PID 查找窗口并绑定。

        使用 EnumWindows + GetWindowThreadProcessId 遍历所有可见窗口，
        匹配指定进程 ID。同一进程可能有多个窗口（游戏主窗口、聊天窗口等），
        此时会选择客户区面积最大的窗口作为游戏主窗口。

        :param pid: 进程 ID
        :return: bool，是否找到并绑定成功。
        """
        if not pid:
            logger.error("find_by_pid 未提供有效的 pid 参数")
            return False

        # 先检查进程是否仍在运行
        if not self.is_process_running(pid):
            logger.warning(f"PID={pid} 进程不存在或已退出")
            return False

        matched = []
        self._find_pid_windows(pid, matched)

        if not matched:
            logger.error(f"未找到 PID={pid} 的窗口")
            return False

        # 按客户区面积降序排列，选择面积最大的窗口（游戏主窗口）
        # 面积为 0 的窗口（最小化或不可绘制）排到最后
        matched.sort(key=lambda x: x[2], reverse=True)

        hwnd, win_title, area = matched[0]
        logger.info(
            f"find_by_pid 命中: hwnd=0x{hwnd:X}, title={win_title!r}, "
            f"pid={pid}, client_area={area}"
        )
        if len(matched) > 1:
            other_titles = [f"{t!r}(area={a})" for _, t, a in matched[1:]]
            logger.info(
                f"同 PID 下还有 {len(matched) - 1} 个窗口: {', '.join(other_titles)}，"
                f"已选择面积最大的作为主窗口"
            )
        return self._bind_hwnd(hwnd)

    def bind(self, title=None, pid=None):
        """
        绑定窗口（综合入口，优先 PID，其次 title）。

        - 同时提供 pid 与 title 时，优先使用 pid 查找。
        - 仅提供 title 时按标题子串查找。
        - 两者均未提供则尝试从 config 读取上次绑定的 title / pid。
        - 绑定成功后会更新 client_rect 与 client_size，并同步到 config。

        :param title: 窗口标题子串（可选）
        :param pid: 进程 ID（可选）
        :return: bool，是否绑定成功。
        """
        # 若未显式传参，尝试从配置恢复
        if not title and not pid:
            cfg_title = config.get("window.title")
            cfg_pid = config.get("window.pid")
            if cfg_title:
                title = cfg_title
            elif cfg_pid:
                try:
                    pid = int(cfg_pid)
                except (TypeError, ValueError):
                    pid = None

        # 任务约定：优先 PID，其次 title
        if pid:
            success = self.find_by_pid(pid)
        elif title:
            success = self.find_by_title(title)
        else:
            logger.error("bind 需要提供 title 或 pid 参数")
            return False

        if success:
            # 同步到 config，便于下次启动恢复
            try:
                if self.window_title:
                    config.set("window.title", self.window_title)
                if self.pid:
                    config.set("window.pid", self.pid)
            except Exception:
                # config 写入失败不应影响绑定结果
                pass
        return success

    @property
    def bound(self) -> bool:
        """是否已绑定有效窗口（hwnd 非零）。"""
        return bool(self.hwnd)

    def unbind(self) -> None:
        """
        解除当前绑定（GUI "解锁" / "解除绑定" 按钮调用）。

        清空 hwnd / pid / title / client_rect 状态，并清除 config 中持久化的
        window.title / window.pid，防止下次启动自动恢复绑定到旧窗口。
        """
        if self.hwnd or self.pid:
            logger.info(
                f"解除绑定: hwnd=0x{self.hwnd:X}, pid={self.pid}, "
                f"title={self.window_title!r}"
            )
        self.hwnd = 0
        self.pid = 0
        self.window_title = ""
        self.client_rect = (0, 0, 0, 0)
        self.client_size = (0, 0)
        try:
            config.set("window.pid", None)
            config.set("window.title", None)
        except Exception:
            pass

    @staticmethod
    def list_game_windows():
        """
        列出所有游戏窗口（支持多开器子窗口），供 GUI 列表选择。

        识别两种结构：
          1. 独立运行的游戏窗口（顶层窗口，class=Galaxy2DEngine 或标题含关键字）
          2. 多开器子窗口（嵌套在多开器里的 Galaxy2DEngine 子窗口，有独立 PID）

        注意：多开器可能同时打开多个游戏窗口，但只有当前选中的可见，
        其他被隐藏（IsWindowVisible=False）。本函数返回所有窗口（含隐藏），
        用 visible 字段标记，方便用户在 GUI 中选择。

        与 yolo_auto_train/capture.py 的 list_game_windows 对齐，保证
        两个工具的窗口绑定行为一致。

        :return: [(hwnd, title, pid, visible), ...] 按 PID 升序
        """
        from core.window_manager import window_manager as _wm
        try:
            wm = _wm()
        except Exception:
            wm = None
        results = []
        seen_hwnd: set = set()

        # 关键字（与 yolo_auto_train/capture.py 对齐）
        GAME_WINDOW_CLASS = "Galaxy2DEngine"
        GAME_WINDOW_KEYWORDS = ("梦幻西游", "梦幻", "MHXY", "鲜衣怒马")

        def _is_game_window(hwnd: int, title: str) -> bool:
            """按窗口类名优先、老关键字兼容识别游戏窗口。"""
            if not title:
                return False
            # 排除多开器本身
            if "多开" in title:
                return False
            try:
                cls = win32gui.GetClassName(hwnd)
            except Exception:
                cls = ""
            if cls == GAME_WINDOW_CLASS:
                return True
            for kw in GAME_WINDOW_KEYWORDS:
                if kw.lower() in title.lower():
                    return True
            return False

        def _add_if_game(hwnd: int, allow_hidden: bool = False):
            if hwnd in seen_hwnd:
                return
            try:
                visible = bool(win32gui.IsWindowVisible(hwnd))
            except Exception:
                visible = False
            if not visible and not allow_hidden:
                return
            try:
                title = win32gui.GetWindowText(hwnd)
            except Exception:
                title = ""
            if not _is_game_window(hwnd, title):
                return
            try:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
            except Exception:
                pid = 0
            results.append((int(hwnd), title, int(pid), visible))
            seen_hwnd.add(hwnd)

        multi_opener_hwnds: list = []

        # ★ 多开器容器类名（如 十年一梦多开器.exe 的 WTWindow/Comet.Shadow）：
        #   每个游戏实例是一个空标题 WTWindow 顶层容器，
        #   内嵌归属游戏进程的 Galaxy2DEngine 子窗口。
        MULTI_OPENER_CLASSES = ("WTWindow", "Comet.Shadow")

        def _enum_top(hwnd, _lp):
            # ctypes 回调必须返回整数（True=继续枚举，False=停止）。
            # 若某分支返回 None，ctypes 转换 BOOL 失败抛
            # 'NoneType' object cannot be interpreted as an integer。
            if not win32gui.IsWindowVisible(hwnd):
                return True
            try:
                title = win32gui.GetWindowText(hwnd)
            except Exception:
                title = ""
            try:
                cls = win32gui.GetClassName(hwnd)
            except Exception:
                cls = ""
            if _is_game_window(hwnd, title):
                _add_if_game(hwnd, allow_hidden=False)
                return True
            # 空标题的 WTWindow 容器（十年一梦多开器实例窗口）也纳入子窗口枚举
            if cls in MULTI_OPENER_CLASSES:
                multi_opener_hwnds.append(hwnd)
                return True
            if not title:
                return True
            if "多开" in title or "multi" in title.lower() or "十年" in title:
                multi_opener_hwnds.append(hwnd)
            return True

        try:
            win32gui.EnumWindows(WNDENUMPROC(_enum_top), 0)
        except Exception as e:
            logger.error(f"list_game_windows 枚举顶层窗口失败: {e}")

        for parent_hwnd in multi_opener_hwnds:
            def _enum_child(child_hwnd, _lp):
                _add_if_game(child_hwnd, allow_hidden=True)
                return True
            try:
                win32gui.EnumChildWindows(parent_hwnd, WNDENUMPROC(_enum_child), 0)
            except Exception as e:
                logger.error(f"枚举多开器子窗口失败: {e}")

        results.sort(key=lambda x: x[2])
        return results

    def _bind_hwnd(self, hwnd):
        """
        内部：直接绑定句柄，更新标题 / PID / 客户区矩形。

        :param hwnd: 窗口句柄（int）
        :return: bool
        """
        if not hwnd:
            return False
        try:
            if not win32gui.IsWindow(hwnd):
                logger.error(f"句柄 0x{hwnd:X} 不是有效窗口")
                return False
        except Exception as e:
            logger.error(f"检查窗口有效性失败: {e}")
            return False

        self.hwnd = int(hwnd)
        try:
            self.window_title = win32gui.GetWindowText(hwnd)
        except Exception:
            self.window_title = ""
        try:
            _, self.pid = win32process.GetWindowThreadProcessId(hwnd)
            self.pid = int(self.pid)
        except Exception as e:
            logger.error(f"获取窗口 PID 失败: {e}")
            self.pid = 0

        # 绑定后立即更新一次客户区矩形
        self.update_rect()
        logger.info(
            f"已绑定窗口 hwnd=0x{self.hwnd:X}, title={self.window_title!r}, pid={self.pid}"
        )
        return True

    # ------------------------------------------------------------------
    # 矩形与坐标
    # ------------------------------------------------------------------
    def update_rect(self):
        """
        重新获取客户区坐标（窗口移动 / 缩放后调用）。

        实现要点：
            - ``GetClientRect(hwnd)`` 返回相对于窗口左上角的 (0, 0, width, height)。
            - ``ClientToScreen(hwnd, (0, 0))`` 把客户区左上角转换为屏幕坐标。
            - 客户区屏幕坐标 = (client_left + x, client_top + y)。

        结果存入：
            - ``client_rect``：(left, top, right, bottom) 屏幕绝对坐标。
            - ``client_size``：(width, height)。
        """
        if not self.hwnd:
            logger.error("update_rect 未绑定窗口")
            return

        try:
            # GetClientRect 返回相对于窗口左上角的坐标 (0, 0, width, height)
            left, top, right, bottom = win32gui.GetClientRect(self.hwnd)
            # ClientToScreen 把客户区左上角 (left, top) 转换为屏幕坐标
            sx, sy = win32gui.ClientToScreen(self.hwnd, (left, top))
            width = right - left
            height = bottom - top
            # 存为 (left, top, right, bottom) 屏幕绝对坐标
            self.client_rect = (sx, sy, sx + width, sy + height)
            self.client_size = (width, height)
        except Exception as e:
            logger.error(f"获取客户区矩形失败: {e}")
            self.client_rect = (0, 0, 0, 0)
            self.client_size = (0, 0)

    def get_client_rect(self):
        """
        返回客户区矩形 (left, top, right, bottom)（屏幕绝对坐标）。

        若已绑定窗口但尚未更新矩形，会自动获取一次。

        :return: tuple (left, top, right, bottom)，未绑定或失败返回 (0, 0, 0, 0)。
        """
        if not self.hwnd:
            return (0, 0, 0, 0)
        # 若尚未计算过，则实时获取一次
        if not self.client_rect or self.client_rect == (0, 0, 0, 0):
            self.update_rect()
        return self.client_rect

    def get_client_size(self):
        """
        返回客户区尺寸 (width, height)。

        :return: tuple (width, height)，未绑定或失败返回 (0, 0)。
        """
        if not self.hwnd:
            return (0, 0)
        # 若尚未计算过，则实时获取一次
        if not self.client_size or self.client_size == (0, 0):
            self.update_rect()
        return self.client_size

    def client_to_screen(self, x, y):
        """
        客户区坐标转屏幕坐标。

        :param x: 客户区 X 坐标
        :param y: 客户区 Y 坐标
        :return: tuple (screen_x, screen_y)，未绑定或失败时返回 (x, y) 原值。
        """
        if not self.hwnd:
            return (x, y)
        try:
            return win32gui.ClientToScreen(self.hwnd, (x, y))
        except Exception as e:
            logger.error(f"client_to_screen 转换失败: {e}")
            return (x, y)

    # ------------------------------------------------------------------
    # 窗口操作
    # ------------------------------------------------------------------
    def is_valid(self):
        """
        检查当前绑定的窗口是否仍然有效（IsWindow）。

        :return: bool，窗口有效返回 True。
        """
        if not self.hwnd:
            return False
        try:
            return bool(win32gui.IsWindow(self.hwnd))
        except Exception:
            return False

    def set_foreground(self):
        """
        将窗口置前。

        使用 ``AttachThreadInput`` 技巧绕过 SetForegroundWindow 的限制
        （调用方必须拥有输入焦点才能切换前台窗口）。
        最小化的窗口会先恢复。

        :return: bool，是否成功置前。
        """
        if not self.hwnd:
            logger.error("set_foreground 未绑定窗口")
            return False
        try:
            # ★ 多开器内嵌子窗口：SetForegroundWindow 只对顶层窗口有效，
            #   取 GA_ROOT 根窗口（如 多开器 WTWindow 容器）执行置前。
            fg_target = self.hwnd
            try:
                root = win32gui.GetAncestor(self.hwnd, win32con.GA_ROOT)
                if root:
                    fg_target = root
            except Exception:
                pass

            # 先恢复（如果窗口被最小化）
            try:
                win32gui.ShowWindow(fg_target, win32con.SW_RESTORE)
            except Exception:
                pass

            # AttachThreadInput 技巧：将当前前台线程的输入处理附加到目标窗口线程，
            # 使 SetForegroundWindow 可以正常工作。
            try:
                fg_hwnd = win32gui.GetForegroundWindow()
                fg_tid = win32process.GetWindowThreadProcessId(fg_hwnd)[0]
                target_tid = win32process.GetWindowThreadProcessId(fg_target)[0]
            except Exception:
                fg_tid, target_tid = 0, 0

            if fg_tid and target_tid and fg_tid != target_tid:
                try:
                    win32process.AttachThreadInput(fg_tid, target_tid, True)
                except Exception:
                    pass
                try:
                    win32gui.SetForegroundWindow(fg_target)
                finally:
                    try:
                        win32process.AttachThreadInput(fg_tid, target_tid, False)
                    except Exception:
                        pass
            else:
                win32gui.SetForegroundWindow(fg_target)

            # 置前后重新更新一次矩形，避免位置已变化
            self.update_rect()
            return True
        except Exception as e:
            logger.error(f"set_foreground 失败: {e}")
            return False

    # ------------------------------------------------------------------
    # 静态：枚举所有窗口（供 GUI 选择目标窗口）
    # ------------------------------------------------------------------
    @staticmethod
    def get_all_windows():
        """
        枚举系统中所有可见且具有标题的窗口。

        用于 GUI 中下拉选择目标窗口。

        :return: list[(hwnd, title, pid)]，按标题排序。
        """
        results = []

        def _enum_cb(hwnd, _):
            if not win32gui.IsWindowVisible(hwnd):
                return True
            try:
                title = win32gui.GetWindowText(hwnd)
            except Exception:
                return True
            if not title:
                return True
            try:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
            except Exception:
                pid = 0
            results.append((hwnd, title, pid))
            return True

        try:
            win32gui.EnumWindows(_enum_cb, None)
        except Exception as e:
            logger.error(f"get_all_windows 枚举失败: {e}")
            return []

        # 按标题排序，便于 GUI 中查找
        results.sort(key=lambda item: item[1])
        return results

    # ------------------------------------------------------------------
    # 进程检查与自动绑定
    # ------------------------------------------------------------------
    @staticmethod
    def is_process_running(pid: int) -> bool:
        """
        检查指定 PID 的进程是否仍在运行。

        使用 Windows API OpenProcess + GetExitCodeProcess 判断。
        无需安装 psutil 等第三方库。

        :param pid: 进程 ID
        :return: bool，进程存在且未退出返回 True
        """
        if not pid or pid <= 0:
            return False
        try:
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

            handle = kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION, False, pid
            )
            if not handle:
                return False

            exit_code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(
                handle, ctypes.byref(exit_code)
            ):
                kernel32.CloseHandle(handle)
                return False

            kernel32.CloseHandle(handle)
            # STILL_ACTIVE = 259
            return exit_code.value == 259
        except Exception:
            # 如果 OpenProcess 失败（权限不足等），用 EnumWindows 兜底
            return False

    def try_restore_last_binding(self) -> bool:
        """
        尝试恢复上次绑定的窗口（按 PID）。

        从 config 读取上次绑定的 PID，检查进程是否仍在运行。
        若进程存在则重新绑定窗口；否则不绑定（保持未绑定状态）。

        设计意图：
        - 用户上次绑定了游戏窗口，关闭程序后重新打开
        - 若游戏仍在运行，自动绑定无需用户重新操作
        - 若游戏已退出，不绑定（避免绑定到错误窗口）

        :return: bool，是否成功恢复绑定
        """
        # 读取上次绑定的 PID
        last_pid = config.get("window.pid")
        if not last_pid:
            logger.info("无上次绑定的 PID，跳过自动恢复")
            return False

        try:
            last_pid = int(last_pid)
        except (TypeError, ValueError):
            logger.warning(f"上次绑定的 PID 无效: {last_pid!r}")
            return False

        if last_pid <= 0:
            return False

        # 检查进程是否仍在运行
        if not self.is_process_running(last_pid):
            logger.info(
                f"上次绑定的 PID={last_pid} 进程已退出，不再自动绑定"
            )
            # 清理已保存的无效 PID
            try:
                config.set("window.pid", None)
            except Exception:
                pass
            return False

        # 进程存在，尝试绑定
        logger.info(f"尝试恢复上次绑定: PID={last_pid}")
        success = self.find_by_pid(last_pid)
        if success:
            logger.info(
                f"自动恢复绑定成功: hwnd=0x{self.hwnd:X}, pid={self.pid}"
            )
        else:
            logger.info(
                f"自动恢复绑定失败: PID={last_pid} 进程存在但未找到窗口"
            )
        return success


# 模块级单例实例，供全局使用
window_manager = WindowManager()
