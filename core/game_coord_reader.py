# -*- coding: utf-8 -*-
"""
游戏坐标读取模块 —— 字模版（已移除全部内存读取）。

历史（2026-08-03 起不再使用）：
    本文件早期版本通过 pymem / ReadProcessMemory / VirtualQueryEx 直接扫描
    游戏进程内存读取角色坐标（候选绝对地址 / 模块基址+偏移 / 自动扫描定位）。
    经多轮实测证实：该游戏**不存在稳定的玩家坐标内存地址**——
      ① 全内存反扫无静态指针指向坐标结构（0 命中）；
      ② 实时坐标数组本会话内就 realloc；
      ③ CPlayer 结构恒为场景缓存不是活坐标；
      ④ 跨地图整体重分配使 CE 多轮过滤失效；
    内存路线已判死刑（见工作记忆「坐标/任务读取路线定论」）。

替代方案（当前实现）：
    字模指纹匹配（core.glyph_coord_reader.GlyphCoordReader）：
    - 截取游戏左上角「地图名[X,Y]」区域，按 #FFFFFF 白色字模做确定性匹配
    - 库中有对应字符时准确率 100%，无任何内存依赖

为兼容既有调用方（task_engine / arrival_verifier / GUI 配置面板），
本模块保留 GameCoordReader / get_coord_reader 的**接口签名不变**，
内部实现全部委托给字模版 GlyphCoordReader；connect() 退化为校验窗口
是否已绑定（不再打开进程句柄），find_coord_addresses 等内存扫描方法
已移除（调用方需同步清理，见 arrival_verifier / config_panel）。
"""
from __future__ import annotations

import threading
from typing import List, Optional, Tuple

from utils.logger import logger


class GameCoordReader:
    """
    字模版游戏坐标读取器（接口兼容内存版，实现已切换为字模指纹）。

    使用方式::

        reader = GameCoordReader()
        reader.connect(pid=12345)      # 校验窗口已绑定（不打开进程句柄）
        x, y = reader.read_coords()    # 委托 glyph_coord_reader
        reader.disconnect()

    :ivar int _pid: 游戏进程 PID（仅记录，供日志排查）
    :ivar bool _connected: 是否已「连接」（= 已绑定窗口，无需进程句柄）
    :ivar threading.Lock _lock: 线程锁
    """

    def __init__(self, pid: Optional[int] = None):
        """
        初始化坐标读取器。

        :param pid: 游戏进程 PID，可延迟调用 connect() 设置
        """
        self._pid: Optional[int] = pid
        self._lock = threading.Lock()
        self._connected = False
        self._module_base: Optional[int] = None
        self._x_addrs: List[int] = []
        self._y_addrs: List[int] = []
        self._module_x_offsets: List[int] = []
        self._module_y_offsets: List[int] = []

    # ------------------------------------------------------------------
    # 上下文管理器支持
    # ------------------------------------------------------------------
    def __enter__(self):
        if self._pid is not None:
            self.connect(self._pid)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
        return False

    # ------------------------------------------------------------------
    # 连接管理
    # ------------------------------------------------------------------
    def connect(self, pid: int) -> bool:
        """
        连接到游戏进程（字模版 = 校验窗口已绑定，不打开进程句柄）。

        :param pid: 游戏进程 PID
        :return: 是否连接成功
        """
        with self._lock:
            if self._connected:
                if self._pid == pid:
                    return True
                self._connected = False

            self._pid = pid
            # 字模方案不依赖进程句柄，只需窗口已绑定即可截图
            try:
                from core.window_manager import window_manager
                if window_manager.bound or window_manager.is_valid():
                    self._connected = True
                    logger.info(f"字模坐标读取器就绪（窗口已绑定）: PID={pid}")
                    return True
                logger.warning(f"字模坐标读取器: 窗口未绑定 PID={pid}")
            except Exception as e:
                logger.error(f"字模坐标读取器 connect 异常 PID={pid}: {e}")
            self._connected = False
            return False

    def disconnect(self) -> None:
        """断开与游戏进程的连接（字模版：仅清状态，无进程句柄可关）。"""
        with self._lock:
            self._connected = False
            self._module_base = None

    @property
    def is_connected(self) -> bool:
        """是否已连接（字模版 = 窗口已绑定）。"""
        return self._connected

    # ------------------------------------------------------------------
    # 坐标读取（委托字模版）
    # ------------------------------------------------------------------
    def read_coords(self) -> Optional[Tuple[float, float]]:
        """
        读取当前游戏坐标（字模指纹匹配，确定性 100%）。

        :return: (x, y) 坐标元组；读取失败返回 None
        """
        if not self.is_connected:
            logger.warning("读取坐标失败：未连接（窗口未绑定）")
            return None

        try:
            from core.glyph_coord_reader import glyph_coord_reader
            loc = glyph_coord_reader.read_location(timeout=3.0)
            if loc and "x" in loc and "y" in loc:
                return (float(loc["x"]), float(loc["y"]))
            logger.debug(f"字模坐标读取: 未识别到有效坐标 ({loc!r})")
            return None
        except Exception as e:
            logger.debug(f"字模坐标读取异常: {e}")
            return None

    # ------------------------------------------------------------------
    # 批量采样
    # ------------------------------------------------------------------
    def sample_coords(
        self, interval: float = 0.05, max_wait: float = 2.0
    ) -> List[Tuple[float, float]]:
        """
        在指定时间窗口内多次采样坐标，返回采样序列。

        :param interval: 采样间隔（秒）
        :param max_wait: 最大等待时间（秒）
        :return: [(x1,y1), (x2,y2), ...] 采样列表
        """
        import time

        samples: List[Tuple[float, float]] = []
        start_time = time.time()

        while time.time() - start_time < max_wait:
            coords = self.read_coords()
            if coords is not None:
                samples.append(coords)
            time.sleep(interval)

        return samples

    def get_status(self) -> dict:
        """
        获取读取器状态信息。

        :return: 状态字典
        """
        return {
            "connected": self._connected,
            "pid": self._pid,
            "method": "glyph_fingerprint",
            "module_base": self._module_base,
            "x_addresses": self._x_addrs[:3],
            "y_addresses": self._y_addrs[:3],
            "module_x_offsets": self._module_x_offsets,
            "module_y_offsets": self._module_y_offsets,
        }


# ------------------------------------------------------------------
# 全局单例
# ------------------------------------------------------------------
_global_reader: Optional[GameCoordReader] = None
_global_reader_lock = threading.Lock()


def get_coord_reader() -> GameCoordReader:
    """
    获取全局坐标读取器单例（字模版）。

    :return: GameCoordReader 实例
    """
    global _global_reader
    if _global_reader is None:
        with _global_reader_lock:
            if _global_reader is None:
                _global_reader = GameCoordReader()
    return _global_reader


def reset_coord_reader() -> None:
    """重置全局坐标读取器（断开连接）。"""
    global _global_reader
    if _global_reader is not None:
        _global_reader.disconnect()
        _global_reader = None