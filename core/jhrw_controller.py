# -*- coding: utf-8 -*-
"""
JHRW 智能控制器 —— 统一读取、验证、检测的单一入口。

替代原先分散的方案：
  - JHRW.py（内存版，函数包内，已移除）
  - JHRWGlyphReader（字模版，独立使用）
  - ArrivalVerifier（到达验证，独立轮询）
  - task_engine._check_auto_wait_arrival（分散逻辑）

职责：
  1. 当前坐标读取（字模指纹，左上角坐标区）
  2. 任务面板读取（字模指纹，JHRW 追踪栏四通道）
  3. 到达验证（坐标比对 + 稳定性检测）
  4. 任务完成检测（进度计数 + 上限判断）
  5. 自适应轮询（状态缓存 TTL，避免冗余截图）
  6. 可取消 / 线程安全

用法::

    from core.jhrw_controller import jhrw_controller

    # 一次快照
    state = jhrw_controller.read_state()
    print(state.current_coord)     # (248, 100)
    print(state.quest_name)        # '初出江湖'
    print(state.target_location)   # '江南野外'
    print(state.progress)          # 282

    # 等待到达目标
    ok = jhrw_controller.wait_for_arrival(105, 25, timeout=30)

    # 检测任务是否完成（默认上限 30 次）
    done = jhrw_controller.is_quest_complete(max_loops=30)
"""
from __future__ import annotations

import time
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional, Tuple

from utils.logger import logger

# 延迟导入避免循环依赖（在方法中按需导入）
# from core.glyph_coord_reader import GlyphCoordReader, JHRWGlyphReader


# ======================================================================
# 数据结构
# ======================================================================

@dataclass
class JHRWState:
    """JHRW 全状态快照（单次采样）。"""

    # ---- 当前坐标（左上角坐标区）----
    current_coord: Optional[Tuple[int, int]] = None       # (x, y)
    current_map: str = ""                                  # 地图名

    # ---- 任务面板（JHRW 追踪栏）----
    quest_name: str = ""                                   # 如 '初出江湖'
    target_location: str = ""                               # 目标地图名
    target_coord: Optional[Tuple[int, int]] = None         # 目标坐标
    npc_name: str = ""
    progress: Optional[int] = None                         # 当前第 N 次
    instruction: str = ""

    # ---- 元数据 ----
    timestamp: float = 0.0                                 # 采样时间
    coord_unknown_count: int = 0                           # 坐标区未识别字符数
    quest_unknown_count: int = 0                           # 任务区未识别字符数
    raw: Dict[str, Any] = field(default_factory=dict)      # 原始识别文本

    @property
    def has_coord(self) -> bool:
        return self.current_coord is not None

    @property
    def has_quest(self) -> bool:
        return bool(self.quest_name)

    @property
    def has_target(self) -> bool:
        return self.target_coord is not None

    def __repr__(self) -> str:
        return (
            f"JHRWState(coord={self.current_coord}, map={self.current_map!r}, "
            f"quest={self.quest_name!r}, target={self.target_location!r}, "
            f"target_coord={self.target_coord}, progress={self.progress})"
        )


# ======================================================================
# 控制器主体
# ======================================================================

class JHRWController:
    """
    JHRW 智能控制器 —— 统一入口。

    设计原则：
      - 无外部可变状态：所有状态从屏幕实时读取（无内存依赖）
      - 幂等读取：相同状态多次 read_state() 返回缓存（TTL 内）
      - 阻塞操作有超时和取消机制
      - 线程安全：内部锁保护缓存和状态
    """

    def __init__(
        self,
        cache_ttl: float = 0.5,
        coord_timeout: float = 3.0,
        quest_timeout: float = 3.0,
    ):
        """
        :param cache_ttl: 状态缓存有效期（秒）。两次读取间隔 < TTL 时返回缓存。
        :param coord_timeout: 坐标读取单次超时
        :param quest_timeout: 任务面板读取单次超时
        """
        self._cache_ttl = cache_ttl
        self._coord_timeout = coord_timeout
        self._quest_timeout = quest_timeout

        # 延迟初始化（首次使用时才加载字模库）
        self._coord_reader = None   # type: Optional[GlyphCoordReader]
        self._quest_reader = None   # type: Optional[JHRWGlyphReader]

        # 缓存
        self._cache: Optional[JHRWState] = None
        self._cache_time: float = 0.0
        self._lock = threading.RLock()

        # 取消标志
        self._cancelled = threading.Event()

    # ------------------------------------------------------------------
    # 内部：延迟初始化读取器
    # ------------------------------------------------------------------

    def _get_coord_reader(self):
        from core.glyph_coord_reader import GlyphCoordReader
        if self._coord_reader is None:
            self._coord_reader = GlyphCoordReader()
        return self._coord_reader

    def _get_quest_reader(self):
        from core.glyph_coord_reader import JHRWGlyphReader
        if self._quest_reader is None:
            self._quest_reader = JHRWGlyphReader()
        return self._quest_reader

    # ------------------------------------------------------------------
    # 公共 API：状态读取
    # ------------------------------------------------------------------

    def read_state(self, force_refresh: bool = False) -> JHRWState:
        """
        读取完整 JHRW 状态（坐标 + 任务面板）。

        在 cache_ttl 内重复调用返回缓存结果，避免冗余截图。
        设置 force_refresh=True 强制重新截图。

        :return: JHRWState 快照（永远非空，字段可能为 None/空）
        """
        with self._lock:
            now = time.time()
            if (
                not force_refresh
                and self._cache is not None
                and (now - self._cache_time) < self._cache_ttl
            ):
                return self._cache

            state = self._do_read_state()
            self._cache = state
            self._cache_time = now
            return state

    def _do_read_state(self) -> JHRWState:
        """执行实际的状态采集（内部方法，已持有锁或无需锁）。"""
        state = JHRWState(timestamp=time.time())

        # 1. 读取当前坐标
        try:
            cr = self._get_coord_reader()
            loc = cr.read_location(timeout=self._coord_timeout)
            if loc:
                state.current_map = loc.get("map", "")
                state.coord_unknown_count = loc.get("unknown_count", 0)
                if "x" in loc and "y" in loc:
                    state.current_coord = (int(loc["x"]), int(loc["y"]))
        except Exception as e:
            logger.debug(f"坐标读取异常: {e}")

        # 2. 读取任务面板
        try:
            qr = self._get_quest_reader()
            quest = qr.read_quest(timeout=self._quest_timeout)
            if quest:
                state.quest_name = quest.get("quest_name", "")
                state.target_location = quest.get("target_location", "")
                state.target_coord = quest.get("target_coord")
                state.npc_name = quest.get("npc_name", "")
                state.progress = quest.get("progress")
                state.instruction = quest.get("instruction", "")
                state.quest_unknown_count = quest.get("unknown_count", 0)
                state.raw = quest.get("raw", {})
        except Exception as e:
            logger.debug(f"任务面板读取异常: {e}")

        logger.debug(f"JHRW状态: {state}")
        return state

    # ------------------------------------------------------------------
    # 公共 API：便捷访问
    # ------------------------------------------------------------------

    def current_coord(self) -> Optional[Tuple[int, int]]:
        """快速获取当前坐标（走缓存）。"""
        return self.read_state().current_coord

    def current_quest(self) -> Optional[dict]:
        """快速获取任务信息（走缓存）。"""
        s = self.read_state()
        if not s.has_quest:
            return None
        return {
            "quest_name": s.quest_name,
            "target_location": s.target_location,
            "target_coord": s.target_coord,
            "npc_name": s.npc_name,
            "progress": s.progress,
        }

    # ------------------------------------------------------------------
    # 公共 API：到达验证
    # ------------------------------------------------------------------

    def wait_for_arrival(
        self,
        target_x: int,
        target_y: int,
        tolerance: int = 5,
        timeout: float = 60.0,
        sample_interval: float = 0.5,
        stable_count: int = 3,
        should_stop_cb: Optional[Callable[[], bool]] = None,
        hide_mouse: bool = True,
    ) -> Tuple[bool, str, Optional[Tuple[int, int]]]:
        """
        阻塞等待角色到达目标坐标附近。

        实现原理：
          - 持续采样当前坐标（字模，每次强制刷新）
          - 判断 |current - target| <= tolerance
          - 连续 stable_count 次满足条件后判定为「已到达」
          - 超时或取消则返回失败

        :param target_x: 目标 X
        :param target_y: 目标 Y
        :param tolerance: 容差像素（曼哈顿距离各轴独立）
        :param timeout: 最大等待秒数
        :param sample_interval: 采样间隔
        :param stable_count: 连续几次在容差内才算稳定到达
        :param should_stop_cb: 外部停止回调（如引擎暂停/终止）
        :param hide_mouse: 等待期间把鼠标移到游戏画面 (5,5) 避免遮挡
            YOLO/模板识别目标（前台模式生效；后台模式自动跳过）。
            默认开启，可用 hide_mouse=False 关闭。
        :return: (成功?, 描述消息, 最后坐标)
        """
        self._cancelled.clear()
        start = time.time()
        last_coord = None
        stable = 0

        # 等待期间把鼠标挪开，防止光标挡住目标导致后续识别失败
        if hide_mouse:
            self._move_mouse_away()

        logger.info(
            f"开始等待到达: 目标=({target_x},{target_y}), "
            f"容差={tolerance}, 超时={timeout}s"
        )

        while True:
            # 检查取消 / 外部停止
            if self._cancelled.is_set():
                return False, "已取消", last_coord
            if should_stop_cb and should_stop_cb():
                return False, "外部停止信号", last_coord

            # 超时检查
            if time.time() - start > timeout:
                msg = (
                    f"等待到达超时({timeout}s), "
                    f"最后坐标={last_coord}"
                )
                logger.warning(msg)
                return False, msg, last_coord

            # 强制刷新坐标（不走缓存）
            state = self.read_state(force_refresh=True)
            coord = state.current_coord

            if coord is None:
                # 截图失败，跳过本次
                time.sleep(sample_interval)
                continue

            last_coord = coord
            cx, cy = coord

            # 到达判定（各轴独立容差）
            if abs(cx - target_x) <= tolerance and abs(cy - target_y) <= tolerance:
                stable += 1
                if stable >= stable_count:
                    msg = f"已到达目标 ({cx},{cy}) ±{tolerance}, 连续{stable}次稳定"
                    logger.info(msg)
                    return True, msg, coord
            else:
                stable = 0

            time.sleep(sample_interval)

    # ------------------------------------------------------------------
    # 公共 API：任务完成检测
    # ------------------------------------------------------------------

    def is_quest_complete(
        self, max_loops: int = 30, force_refresh: bool = True
    ) -> Tuple[bool, Optional[int]]:
        """
        检测当前任务是否已完成（进度达到上限）。

        :param max_loops: 任务总次数上限（初出江湖默认 30）
        :param force_refresh: 是否强制刷新（建议 True 以获取最新进度）
        :return: (是否完成?, 当前进度)
        """
        state = self.read_state(force_refresh=force_refresh)
        prog = state.progress

        if prog is None:
            return False, None

        if prog >= max_loops:
            logger.info(f"任务完成: 进度 {prog}/{max_loops}")
            return True, prog

        return False, prog

    # ------------------------------------------------------------------
    # 公共 API：控制
    # ------------------------------------------------------------------

    def _move_mouse_away(self) -> None:
        """把鼠标挪到游戏窗口客户区右下角 (996,612)，避免光标遮挡识别目标。

        - 2026-08-06 调整：隐藏位置从左上角 (5,5) 改为右下角 (996,612)
          （用户实测：右下角更不易误触发识别/遮挡）。
        - 2026-08-05 修复：**后台模式不再真实移动物理鼠标**（全后台化后
          物理鼠标应保持不动）——改为 PostMessage WM_MOUSEMOVE 模拟
          悬停到 (996,612)，游戏仍感知鼠标位置但物理光标不动。
        - 前台模式保持 pyautogui 真实移动（原始需求：防遮挡）。
        - 用 window_manager.client_to_screen 把**游戏画面内**的 (996,612)
          换算成屏幕坐标再移动 —— 注意不是屏幕绝对 (996,612)。
        - 失败静默（不阻断等待到达主流程）。
        """
        try:
            from core.window_manager import window_manager

            if not window_manager.is_valid():
                return
            from core.input_controller import input_controller
            mode = input_controller._get_mode() if hasattr(input_controller, "_get_mode") else "foreground"
            if mode == "background":
                # 后台模式：PostMessage WM_MOUSEMOVE 模拟悬停（物理鼠标不动）
                try:
                    input_controller._post_message(
                        0x0200, 0, input_controller._make_mouse_lparam(996, 612)
                    )
                    logger.debug("等待到达：后台模拟鼠标悬停到游戏画面 (996,612)（物理鼠标不动）")
                except Exception as e:
                    logger.debug(f"后台模拟鼠标悬停失败（不影响等待到达）: {e}")
                return
            try:
                import pyautogui
                pyautogui.FAILSAFE = False
                # 游戏画面 (996,612) = 客户区 (996,612) → 屏幕坐标
                sx, sy = window_manager.client_to_screen(996, 612)
                pyautogui.moveTo(sx, sy, duration=0.05)
                logger.debug(f"等待到达：已把鼠标移到游戏画面 (996,612) → 屏幕({sx},{sy}) 避免遮挡")
            except ImportError:
                logger.debug("pyautogui 未安装，跳过移鼠标")
        except Exception as e:
            logger.debug(f"移动鼠标失败（不影响等待到达）: {e}")

    def cancel(self):
        """取消正在进行的阻塞操作（wait_for_arrival 等）。"""
        self._cancelled.set()

    def reset_cache(self):
        """清除状态缓存，下次 read_state 将重新截图。"""
        with self._lock:
            self._cache = None
            self._cache_time = 0.0

    def invalidate(self):
        """别名 for reset_cache（语义更清晰：标记当前状态已过期）。"""
        self.reset_cache()


# ======================================================================
# 全局单例
# ======================================================================

_jhrw_controller_instance: Optional[JHRWController] = None
_jhrw_controller_lock = threading.Lock()


def get_jhrw_controller() -> JHRWController:
    """获取全局 JHRW 控制器单例。"""
    global _jhrw_controller_instance
    if _jhrw_controller_instance is None:
        with _jhrw_controller_lock:
            if _jhrw_controller_instance is None:
                _jhrw_controller_instance = JHRWController()
    return _jhrw_controller_instance


# 向后兼容的便捷引用
jhrw_controller = get_jhrw_controller()
