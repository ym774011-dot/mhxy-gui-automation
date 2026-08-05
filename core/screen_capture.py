# -*- coding: utf-8 -*-
"""
屏幕捕获模块。

提供 ``ScreenCapture`` 类（单例模式），负责：
    - 截取当前绑定窗口的客户区，返回 OpenCV 兼容的 BGR numpy 数组
    - 截取客户区内指定子区域
    - 截图保存到文件
    - 截取全屏（备用方案）

底层使用 ``mss`` 库进行高效屏幕捕获。
依赖 ``core.window_manager.window_manager`` 获取窗口客户区位置。

重要约定：``window_manager.get_client_rect()`` 返回 (left, top, right, bottom)，
本模块据此计算 width = right - left, height = bottom - top。

使用方式::

    from core.window_manager import window_manager
    from core.screen_capture import screen_capture

    if window_manager.bind(title="梦幻西游"):
        img = screen_capture.capture()
        if img is not None:
            cv2.imshow("capture", img)
"""
import os
import threading

import mss
import numpy as np
import cv2

from core.window_manager import window_manager
from utils.logger import logger


class ScreenCapture:
    """
    屏幕捕获器（单例模式）。

    通过 ``_instance`` 与 ``_lock`` 实现线程安全的单例。
    使用时直接 ``from core.screen_capture import screen_capture`` 即可。
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        # mss 实例：mss 内部使用 threading.local() 保存 DC 句柄（srcdc），
        # 不同线程无法共享同一个 mss 实例。改为按线程创建独立实例。
        self._sct_local = threading.local()
        self._sct_lock = threading.Lock()
        self._initialized = True

    @property
    def _sct(self):
        """
        获取当前线程的 mss 实例（线程隔离）。

        mss 在 Windows 上使用 threading.local 保存屏幕 DC 句柄，
        在创建实例的线程之外调用 grab 会因 srcdc 缺失而失败。
        此属性为每个线程懒加载独立的 mss 实例。
        """
        sct = getattr(self._sct_local, "instance", None)
        if sct is None:
            sct = mss.mss()
            self._sct_local.instance = sct
        return sct

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------
    def _grab(self, left, top, width, height):
        """
        使用 mss 截取指定屏幕区域，返回 BGR numpy 数组。

        mss 的 ``grab`` 返回的对象通过 ``np.asarray`` 可转为 (height, width, 4)
        的 BGRA 数组，再通过 ``cv2.cvtColor`` 转为 BGR（OpenCV 标准）。

        实现说明：
            不同 mss 版本中 ``raw.rgb`` 属性的通道数（3 或 4 字节 / 像素）不一致，
            直接 ``frombuffer(raw.rgb)`` 并按固定通道数 reshape 容易失败。
            ``np.asarray(raw)`` 走 mss 的 ``__array_interface__``，始终返回
            (height, width, 4) 的 BGRA 数组，是最稳健的转换方式。

        :param left: 屏幕左上角 X
        :param top: 屏幕左上角 Y
        :param width: 截图宽度
        :param height: 截图高度
        :return: np.ndarray (height, width, 3)，BGR 通道顺序。
        """
        if width <= 0 or height <= 0:
            raise ValueError(f"截图区域尺寸非法: width={width}, height={height}")

        monitor = {
            "left": int(left),
            "top": int(top),
            "width": int(width),
            "height": int(height),
        }
        # mss.grab 线程安全性未知，使用锁串行化以保险
        with self._sct_lock:
            raw = self._sct.grab(monitor)
        # np.asarray(raw) 利用 mss 的 __array_interface__，得到 (height, width, 4) BGRA 数组
        img = np.asarray(raw)
        # BGRA -> BGR（OpenCV 标准），丢弃 Alpha 通道
        img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
        # 拷贝为连续数组，避免后续 OpenCV 操作因非连续内存报错
        return np.ascontiguousarray(img)

    def _ensure_bound(self):
        """
        检查窗口是否已绑定且仍然有效。

        未绑定或无效时记录错误日志并返回 False。
        """
        if not window_manager.hwnd or not window_manager.is_valid():
            logger.error("未绑定有效窗口，无法截图")
            return False
        return True

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------
    def capture(self):
        """
        截取当前绑定窗口的客户区。

        截图前会先调用 ``window_manager.update_rect()`` 获取最新客户区位置，
        然后用 mss 截取客户区对应的屏幕区域，返回 BGR numpy 数组。

        :return: BGR numpy 数组 (height, width, 3)；
                 窗口未绑定 / 无效或截图失败时返回 None。
        """
        if not self._ensure_bound():
            return None
        try:
            # 截图前更新坐标，避免窗口移动导致截图位置错误
            window_manager.update_rect()
            rect = window_manager.get_client_rect()
            if not rect:
                logger.error("无法获取客户区矩形")
                return None
            # client_rect = (left, top, right, bottom)
            left, top, right, bottom = rect
            width = right - left
            height = bottom - top
            if width <= 0 or height <= 0:
                logger.error(
                    f"客户区尺寸非法: width={width}, height={height}，窗口可能已最小化"
                )
                return None
            return self._grab(left, top, width, height)
        except Exception as e:
            logger.error(f"capture 截图失败: {e}")
            return None

    def capture_region(self, x, y, w, h):
        """
        截取客户区内指定子区域。

        坐标 (x, y) 为客户区内的坐标（左上角为 0,0），
        函数内部通过 ``window_manager.client_to_screen`` 转换为屏幕坐标。
        若指定区域超出客户区，会自动裁剪到客户区范围内。

        :param x: 客户区内 X 坐标
        :param y: 客户区内 Y 坐标
        :param w: 截图宽度
        :param h: 截图高度
        :return: BGR numpy 数组；未绑定 / 无效或失败时返回 None。
        """
        if not self._ensure_bound():
            return None
        if w <= 0 or h <= 0:
            logger.error(f"截图区域尺寸非法: w={w}, h={h}")
            return None

        try:
            # 截图前更新坐标
            window_manager.update_rect()
            rect = window_manager.get_client_rect()
            if not rect:
                logger.error("无法获取客户区矩形")
                return None
            # client_rect = (left, top, right, bottom)
            client_left, client_top, client_right, client_bottom = rect
            client_w = client_right - client_left
            client_h = client_bottom - client_top

            # 边界检查，超出客户区时自动裁剪
            if x < 0 or y < 0 or x + w > client_w or y + h > client_h:
                logger.warning(
                    f"截取区域 ({x},{y},{w},{h}) 超出客户区 "
                    f"({client_w}x{client_h})，将自动裁剪"
                )
                x = max(0, x)
                y = max(0, y)
                w = min(w, client_w - x)
                h = min(h, client_h - y)
                if w <= 0 or h <= 0:
                    logger.error("裁剪后区域为空")
                    return None

            # 客户区坐标转屏幕坐标
            screen_x, screen_y = window_manager.client_to_screen(x, y)
            return self._grab(screen_x, screen_y, w, h)
        except Exception as e:
            logger.error(f"capture_region 截图失败: {e}")
            return None

    def capture_to_file(self, path):
        """
        截图并保存为文件。

        内部调用 ``capture()`` 获取 BGR 图像，再用 ``cv2.imwrite`` 保存
        （支持 png / jpg 等格式）。相对路径会相对于项目根目录解析。

        :param path: 保存路径。
        :return: bool，是否保存成功。
        """
        img = self.capture()
        if img is None:
            logger.error("capture_to_file 截图失败，无法保存")
            return False

        try:
            # 相对路径解析到项目根目录
            if not os.path.isabs(path):
                project_root = os.path.dirname(
                    os.path.dirname(os.path.abspath(__file__))
                )
                path = os.path.join(project_root, path)

            # 确保目录存在
            save_dir = os.path.dirname(path)
            if save_dir:
                os.makedirs(save_dir, exist_ok=True)

            # img 已是 BGR 顺序，直接 imwrite
            result = cv2.imwrite(path, img)
            if not result:
                logger.error("cv2.imwrite 返回 False")
                return False
            logger.info(f"截图已保存: {path}")
            return True
        except Exception as e:
            logger.error(f"capture_to_file 保存失败: {e}")
            return False

    def capture_full_screen(self):
        """
        截取整个屏幕（备用方案，不依赖窗口绑定）。

        使用 mss 的虚拟屏幕（monitors[0]，覆盖所有显示器）。

        :return: BGR numpy 数组；失败时返回 None。
        """
        try:
            with self._sct_lock:
                monitors = self._sct.monitors
            if not monitors:
                logger.error("未检测到显示器")
                return None
            # monitors[0] 是所有显示器的合并区域（虚拟屏幕）
            mon = monitors[0]
            return self._grab(mon["left"], mon["top"], mon["width"], mon["height"])
        except Exception as e:
            logger.error(f"capture_full_screen 截图失败: {e}")
            return None


# 模块级单例实例，供全局使用
screen_capture = ScreenCapture()
