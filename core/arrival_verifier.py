# -*- coding: utf-8 -*-
"""
到达验证模块。

通过轮询字模坐标，验证角色是否已经到达指定目标位置。
用于"点击前往按钮 → 等待角色移动 → 确认到达"的精确控制流程。

核心特性：
    - 字模指纹读取坐标（glyph_coord_reader），确定性 100%，无内存依赖
      （2026-08-03 起内存坐标路线已判死刑，见 game_coord_reader 模块头）
    - 坐标对比容差可配置（默认 ≤2 像素）
    - 快速响应：成功到达时 ≤300ms 内返回
    - 完整的错误处理与重试机制
    - 线程安全，支持多个并发验证

设计要点：
    - 验证成功需要连续 N 次（默认 2 次）坐标落在容差范围内，
      避免刚好路过目标点造成的"假到达"
    - 超时后返回失败，携带最后一次读取到的坐标
    - 所有时间均使用 time.time()，精度 ~1ms
"""
import time
import threading
from typing import Callable, Optional, Tuple, List, Dict, Any

from utils.logger import logger
from core.game_coord_reader import GameCoordReader, get_coord_reader


# ------------------------------------------------------------------
# 默认配置
# ------------------------------------------------------------------
DEFAULT_TOLERANCE = 2.0          # 坐标容差（游戏坐标单位，浮点）
DEFAULT_TIMEOUT = 5.0            # 最大等待时间（秒）
DEFAULT_POLL_INTERVAL = 0.05     # 坐标轮询间隔（秒）
DEFAULT_STABLE_COUNT = 2         # 连续命中次数（用于防抖）
DEFAULT_READ_RETRIES = 2         # 单次坐标读取的重试次数
MIN_POLL_INTERVAL = 0.01         # 最小轮询间隔（防止 CPU 过载）
MAX_POLL_INTERVAL = 2.0          # 最大轮询间隔

# 新方案：等待移动停止 + 坐标对比
DEFAULT_MOVE_SAMPLE_INTERVAL = 0.2   # 检测移动状态的采样间隔（秒）
DEFAULT_MOVE_STABLE_COUNT = 5        # 连续N次坐标不变判定为停止（保留兼容，新逻辑用秒数）
DEFAULT_MOVE_TOLERANCE = 3.0         # 停止后坐标与目标的容差
DEFAULT_WAIT_TIMEOUT = 30.0          # 等待到达的总超时（秒，新逻辑中仅作移动兜底上限）
DEFAULT_STOP_CONFIRM_S = 1.0         # 坐标静止持续秒数 → 判定"角色已停止"（事件驱动核心）
DEFAULT_STOP_FAIL_CONFIRM_S = 2.0    # 停止但未到达后观察秒数 → 判定失败
MOVE_SPEED_LOWER_BOUND = 6.0         # 移动兜底超时估算的速度下限（单位/秒）


class ArrivalVerifier:
    """
    到达验证器。

    使用方式::

        verifier = ArrivalVerifier()
        ok, msg, current = verifier.verify_arrival(
            target_x=56.0, target_y=92.0, pid=12345
        )
        if ok:
            print(f"已到达: {current}")

    :ivar float tolerance: 坐标容差（像素）
    :ivar float timeout: 最大等待时间（秒）
    :ivar float poll_interval: 坐标轮询间隔（秒）
    :ivar int stable_count: 连续命中次数
    :ivar int read_retries: 单次读取重试次数
    :ivar GameCoordReader _reader: 坐标读取器实例
    :ivar threading.Lock _lock: 线程锁
    """

    def __init__(
        self,
        tolerance: float = DEFAULT_TOLERANCE,
        timeout: float = DEFAULT_TIMEOUT,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        stable_count: int = DEFAULT_STABLE_COUNT,
        read_retries: int = DEFAULT_READ_RETRIES,
        stop_confirm_s: float = DEFAULT_STOP_CONFIRM_S,
        stop_fail_confirm_s: float = DEFAULT_STOP_FAIL_CONFIRM_S,
    ):
        """
        初始化到达验证器。

        :param tolerance: 坐标容差（默认 2 像素）
        :param timeout: 最大等待时间（默认 5 秒）
        :param poll_interval: 坐标轮询间隔（默认 50ms）
        :param stable_count: 连续命中次数（默认 2 次，用于防抖）
        :param read_retries: 单次坐标读取重试次数（默认 2 次）
        :param stop_confirm_s: 坐标静止持续秒数判定"停止"（默认 1.0）
        :param stop_fail_confirm_s: 停止但未到达后观察秒数判定失败（默认 2.0）
        """
        self.tolerance = float(tolerance)
        self.timeout = float(timeout)
        # 限制轮询间隔在合理范围内
        self.poll_interval = max(MIN_POLL_INTERVAL, min(poll_interval, MAX_POLL_INTERVAL))
        self.stable_count = max(1, int(stable_count))
        self.read_retries = max(0, int(read_retries))
        self.stop_confirm_s = float(stop_confirm_s)
        self.stop_fail_confirm_s = float(stop_fail_confirm_s)
        self._reader: Optional[GameCoordReader] = None
        self._lock = threading.Lock()
        self._stop_flag = False

    # ------------------------------------------------------------------
    # 配置更新
    # ------------------------------------------------------------------
    def configure(
        self,
        tolerance: Optional[float] = None,
        timeout: Optional[float] = None,
        poll_interval: Optional[float] = None,
        stable_count: Optional[int] = None,
    ) -> None:
        """
        动态更新验证参数。

        :param tolerance: 坐标容差
        :param timeout: 最大等待时间
        :param poll_interval: 轮询间隔
        :param stable_count: 连续命中次数
        """
        if tolerance is not None:
            self.tolerance = float(tolerance)
        if timeout is not None:
            self.timeout = float(timeout)
        if poll_interval is not None:
            self.poll_interval = max(MIN_POLL_INTERVAL, min(poll_interval, MAX_POLL_INTERVAL))
        if stable_count is not None:
            self.stable_count = max(1, int(stable_count))

    # ------------------------------------------------------------------
    # 核心：到达验证
    # ------------------------------------------------------------------
    def verify_arrival(
        self,
        target_x: float,
        target_y: float,
        pid: Optional[int] = None,
        should_stop_cb: Optional[Callable[[], bool]] = None,
    ) -> Tuple[bool, str, Optional[Tuple[float, float]]]:
        """
        验证角色是否已到达目标坐标。

        流程：
            1. 连接游戏进程（如需）
            2. 开始轮询当前坐标
            3. 每次读取后判断是否在容差范围内
            4. 连续命中 stable_count 次则判定到达
            5. 超时则判定失败

        :param target_x: 目标 X 坐标（游戏逻辑坐标）
        :param target_y: 目标 Y 坐标（游戏逻辑坐标）
        :param pid: 游戏进程 PID（若未指定则使用已连接的读取器）
        :param should_stop_cb: 外部停止信号回调，返回 True 表示应停止
        :return: (is_arrived, message, current_coords)
        """
        target_x = float(target_x)
        target_y = float(target_y)

        # 连接坐标读取器
        with self._lock:
            if self._reader is None:
                self._reader = get_coord_reader()

        if pid is not None and not self._reader.is_connected:
            if not self._reader.connect(pid):
                msg = f"连接游戏进程 PID={pid} 失败"
                logger.error(msg)
                return False, msg, None

        if not self._reader.is_connected:
            msg = "坐标读取器未连接，无法验证到达"
            logger.error(msg)
            return False, msg, None

        self._stop_flag = False
        start_time = time.time()
        last_coords: Optional[Tuple[float, float]] = None
        stable_hits = 0
        sample_count = 0
        fail_count = 0  # 连续读取失败计数（用于诊断）

        logger.info(
            f"开始到达验证: 目标=({target_x:.1f}, {target_y:.1f}), "
            f"容差={self.tolerance:.1f}px, 超时={self.timeout}s, "
            f"PID={pid}"
        )

        while True:
            # 检查外部停止信号
            if self._stop_flag:
                return False, "验证已被外部停止", last_coords

            if should_stop_cb and should_stop_cb():
                return False, "验证被停止信号中断", last_coords

            # 超时检查
            elapsed = time.time() - start_time
            if elapsed >= self.timeout:
                if fail_count > 0 and last_coords is None:
                    # 全程未能读取到任何坐标
                    msg = (
                        f"到达验证超时（{self.timeout}s），"
                        f"全程未能读取到角色坐标"
                        f"（连续失败 {fail_count} 次）。"
                        f"可能原因：游戏窗口被遮挡或未绑定，"
                        f"字模识别无法截取坐标区域。"
                    )
                else:
                    msg = (
                        f"到达验证超时（{self.timeout}s），"
                        f"最后坐标={last_coords}"
                    )
                logger.warning(msg)
                return False, msg, last_coords

            # 读取当前坐标
            current = self._read_coords_with_retry()
            sample_count += 1

            if current is None:
                # 读取失败，等待下一轮
                fail_count += 1
                if fail_count == 1:
                    logger.warning(
                        f"字模坐标读取失败（首次），目标=({target_x:.1f},"
                        f" {target_y:.1f})，将重试..."
                    )
                elif fail_count % 10 == 0:
                    logger.warning(
                        f"字模坐标读取已连续失败 {fail_count} 次，"
                        f"窗口可能被遮挡或未绑定"
                    )
                time.sleep(self.poll_interval)
                continue

            # 读取成功，重置失败计数
            if fail_count > 0:
                logger.info(f"坐标读取恢复（此前失败 {fail_count} 次）")
            fail_count = 0

            last_coords = current
            cur_x, cur_y = current

            # 坐标对比
            dist = self._calc_distance(cur_x, cur_y, target_x, target_y)

            if dist <= self.tolerance:
                stable_hits += 1
                if stable_hits >= self.stable_count:
                    elapsed_ms = (time.time() - start_time) * 1000
                    msg = (
                        f"到达验证通过: 坐标=({cur_x:.1f}, {cur_y:.1f}), "
                        f"偏差={dist:.2f}px, 耗时={elapsed_ms:.0f}ms"
                    )
                    logger.info(msg)
                    return True, msg, current
            else:
                # 偏离目标，重置连续命中计数
                stable_hits = 0

            # 分段睡眠，响应及时
            self._interruptible_sleep(self.poll_interval)

    def wait_for_arrival(
        self,
        target_x: float,
        target_y: float,
        pid: Optional[int] = None,
        should_stop_cb: Optional[Callable[[], bool]] = None,
        stable_count: int = DEFAULT_MOVE_STABLE_COUNT,
        sample_interval: float = DEFAULT_MOVE_SAMPLE_INTERVAL,
        tolerance: float = DEFAULT_MOVE_TOLERANCE,
        timeout: float = DEFAULT_WAIT_TIMEOUT,
        stop_confirm_s: Optional[float] = None,
        stop_fail_confirm_s: Optional[float] = None,
        hide_mouse: bool = True,
    ) -> Tuple[bool, str, Optional[Tuple[float, float]]]:
        """
        等待角色移动到目标位置（事件驱动版，2026-08-05 重构）。

        核心变化：到达/未到达由**角色移动状态**决定，不再由时间决定。
          - 坐标在移动 → 继续等待（记录最后移动时间）
          - 坐标静止持续 stop_confirm_s → 判定"角色已停止"，立即对比目标：
              偏差 ≤ 容差 → 到达成功（不管耗时多久）
              偏差 > 容差 → 再观察 stop_fail_confirm_s，仍未移动 → 失败
          - 任何采样偏差 ≤ 容差 → 立即成功（角色路过/站在目标点）

        超时（timeout）仅作异常兜底，且**按距离自动估算**（用户 2026-08-05
        需求：不再输入特定时间扫描识别）：
          - 自动估算 = 起点→目标距离 / 速度下限 × 1.5 + 5s 缓冲；
          - 调用方传入的 timeout 仅作为上限约束（auto 优先）；
          - 触发条件：从开始持续移动超过估算值（疑似寻路死循环/被卡住）。

        :param target_x: 目标 X 坐标
        :param target_y: 目标 Y 坐标
        :param pid: 游戏进程 PID
        :param should_stop_cb: 外部停止信号回调
        :param stable_count: 保留参数（兼容旧调用），事件驱动版不再使用
        :param sample_interval: 采样间隔秒数（默认 0.2）
        :param tolerance: 与目标坐标的容差（默认 3px）
        :param timeout: 移动兜底超时上限（默认 30s；实际按距离自动估算）
        :param stop_confirm_s: 坐标静止持续秒数判定"停止"（默认 1.0）
        :param stop_fail_confirm_s: 停止但未到达后观察秒数判定失败（默认 2.0）
        :param hide_mouse: 等待期间把鼠标移到游戏画面 (5,5)，避免光标遮挡
            YOLO/模板识别目标。默认开启；后台输入模式自动跳过。
        :return: (是否到达, 消息, 当前坐标)
        """
        target_x = float(target_x)
        target_y = float(target_y)

        # 未显式传入时回退到构造器配置的实例属性
        if stop_confirm_s is None:
            stop_confirm_s = self.stop_confirm_s
        if stop_fail_confirm_s is None:
            stop_fail_confirm_s = self.stop_fail_confirm_s

        # 等待期间把鼠标挪开，防止光标挡住目标导致后续识别失败
        if hide_mouse:
            self._move_mouse_away()

        # 连接坐标读取器
        with self._lock:
            if self._reader is None:
                self._reader = get_coord_reader()

        if pid is not None and not self._reader.is_connected:
            if not self._reader.connect(pid):
                msg = f"连接游戏进程 PID={pid} 失败"
                logger.error(msg)
                return False, msg, None

        if not self._reader.is_connected:
            msg = "坐标读取器未连接，无法等待到达"
            logger.error(msg)
            return False, msg, None

        self._stop_flag = False
        start_time = time.time()
        last_coords: Optional[Tuple[float, float]] = None
        fail_count = 0

        # ---- 事件驱动状态 ----
        prev_coords: Optional[Tuple[float, float]] = None
        moved_detected = False          # 是否检测到过移动
        last_move_time = start_time     # 最后检测到移动的时间
        stop_confirm_start: Optional[float] = None   # 静止计时起点
        stop_fail_deadline: Optional[float] = None   # 停止未到达的失败观察截止
        start_coords: Optional[Tuple[float, float]] = None  # 首个坐标（估算距离）
        move_timeout: Optional[float] = None         # 移动兜底超时（自动估算）

        logger.info(
            f"开始等待到达: 目标=({target_x:.1f}, {target_y:.1f}), "
            f"静止确认={stop_confirm_s}s, 停止失败观察={stop_fail_confirm_s}s, "
            f"采样间隔={sample_interval}s, 容差={tolerance:.1f}px"
        )

        while True:
            # 外部停止信号
            if self._stop_flag:
                return False, "等待已被外部停止", last_coords
            if should_stop_cb and should_stop_cb():
                return False, "等待被停止信号中断", last_coords

            # 读取当前坐标
            current = self._read_coords_with_retry()

            if current is None:
                fail_count += 1
                if fail_count == 1:
                    logger.warning("等待到达：字模坐标读取失败（首次）")
                elif fail_count % 10 == 0:
                    logger.warning(
                        f"等待到达：字模坐标读取已连续失败 {fail_count} 次"
                    )
                # 连续30次读取失败（约6秒），判定为识别不可用，快速退出
                if fail_count >= 30:
                    msg = (
                        f"字模坐标读取连续失败 {fail_count} 次，"
                        f"窗口可能被遮挡或未绑定，需要重新绑定窗口"
                    )
                    logger.error(msg)
                    return False, msg, last_coords
                self._interruptible_sleep(sample_interval)
                continue

            # 读取成功
            if fail_count > 0:
                logger.info(f"等待到达：字模坐标读取恢复（此前失败 {fail_count} 次）")
            fail_count = 0
            last_coords = current
            cur_x, cur_y = current

            # 首次读到坐标：记录起点，自动估算移动兜底超时
            if start_coords is None:
                start_coords = current
                dist_total = self._calc_distance(
                    start_coords[0], start_coords[1], target_x, target_y
                )
                move_timeout = (
                    dist_total / MOVE_SPEED_LOWER_BOUND * 1.5 + 5.0
                )
                # 调用方传入 timeout 仅作上限（auto 优先，防止任务想快点失败）
                if timeout > 0 and timeout < move_timeout:
                    move_timeout = timeout
                logger.info(
                    f"等待到达: 起点=({start_coords[0]:.0f}, {start_coords[1]:.0f}), "
                    f"距离目标 {dist_total:.0f} 单位, "
                    f"移动兜底超时={move_timeout:.0f}s（自动估算）"
                )

            # 到达即时命中：任何采样偏差 ≤ 容差 → 直接成功
            dist = self._calc_distance(cur_x, cur_y, target_x, target_y)
            if dist <= tolerance:
                elapsed_ms = (time.time() - start_time) * 1000
                msg = (
                    f"到达成功：坐标=({cur_x:.1f}, {cur_y:.1f}), "
                    f"偏差={dist:.2f}px, 耗时={elapsed_ms:.0f}ms"
                )
                logger.info(msg)
                return True, msg, current

            now = time.time()

            # ---- 移动检测（事件驱动核心） ----
            if prev_coords is not None:
                move_dist = self._calc_distance(
                    prev_coords[0], prev_coords[1], cur_x, cur_y
                )
                if move_dist > 0.5:
                    # 角色在移动：记录时间，重置静止计时与失败观察
                    moved_detected = True
                    last_move_time = now
                    stop_confirm_start = None
                    stop_fail_deadline = None

                    # 移动超长兜底（防寻路死循环/被卡住来回走）
                    if move_timeout is not None and (
                        now - start_time > move_timeout
                    ):
                        msg = (
                            f"到达失败：角色持续移动超过 {move_timeout:.0f}s "
                            f"仍未停止（疑似寻路死循环或被卡住），"
                            f"最后坐标=({cur_x:.1f}, {cur_y:.1f}), "
                            f"目标=({target_x:.1f}, {target_y:.1f})"
                        )
                        logger.warning(msg)
                        return False, msg, current
                else:
                    # 坐标静止：累计静止时长
                    if stop_confirm_start is None:
                        stop_confirm_start = now

                    # 静止持续达标 → 停止确认，立即做到达判定
                    if now - stop_confirm_start >= stop_confirm_s:
                        if stop_fail_deadline is None:
                            stop_fail_deadline = now + stop_fail_confirm_s
                            logger.warning(
                                f"角色已停止移动但不在目标附近"
                                f"（偏差 {dist:.2f}px > 容差 {tolerance:.1f}px），"
                                f"观察 {stop_fail_confirm_s:.0f}s "
                                f"确认未再移动后判定失败..."
                            )
                        elif now >= stop_fail_deadline:
                            msg = (
                                f"到达失败：角色停止后 {stop_fail_confirm_s:.0f}s "
                                f"未再移动，且偏差 {dist:.2f}px > 容差 "
                                f"{tolerance:.1f}px。"
                                f"坐标=({cur_x:.1f}, {cur_y:.1f}), "
                                f"目标=({target_x:.1f}, {target_y:.1f})。"
                                f"角色很可能是寻路被挡停在错误位置。"
                            )
                            logger.warning(msg)
                            return False, msg, current
            else:
                # 首个采样点，仅记录
                pass

            # 更新上一次坐标
            prev_coords = current

            # 等待下一次采样（分段睡眠，响应及时）
            self._interruptible_sleep(sample_interval)

    def stop(self) -> None:
        """请求停止当前验证。"""
        self._stop_flag = True

    # ------------------------------------------------------------------
    # 内部工具方法
    # ------------------------------------------------------------------
    def _read_coords_with_retry(self) -> Optional[Tuple[float, float]]:
        """
        读取坐标，支持多次重试（纯字模方案）。

        2026-08-03 起该游戏内存坐标路线已判死刑（见 game_coord_reader 模块头
        注释），故移除 GameCoordReader 内存兜底，只保留字模指纹读取器。

        :return: (x, y) 坐标或 None
        """
        try:
            from core.glyph_coord_reader import glyph_coord_reader
            last = None
            for _ in range(max(1, self.read_retries + 1)):
                loc = glyph_coord_reader.read_location(
                    timeout=1.5, retry_interval=0.1
                )
                if loc and "x" in loc and "y" in loc:
                    return (float(loc["x"]), float(loc["y"]))
                last = loc
                time.sleep(0.02)
            if last is not None:
                logger.debug(f"字模坐标读取: 未识别到有效坐标 ({last!r})")
        except Exception as e:
            logger.debug(f"字模坐标读取异常: {e}")
        return None

    def _verify_with_ocr(
        self, target_x: float, target_y: float, tolerance: float
    ) -> Optional[Tuple[bool, str]]:
        """
        使用 OCR 识别游戏左上角坐标，验证是否到达目标位置。

        当字模坐标读取可能失效（偏差较大）时，用 OCR 作为辅助验证。

        :param target_x: 目标 X 坐标
        :param target_y: 目标 Y 坐标
        :param tolerance: 容差范围
        :return: (是否到达, 消息) 或 None（OCR 不可用）
        """
        # 2026-08-05 10:47：OCR 整体包线程超时（OCR_TIMEOUT 秒）。
        # easyocr 首次使用会下载模型（可能几分钟），同步调用会把等待到达流程
        # 堵死；超时后视为 OCR 不可用返回 None，流程继续走字模/失败路径。
        OCR_TIMEOUT = 8.0
        try:
            from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutTimeout

            def _do_ocr():
                from core.ocr_coord_reader import read_coord_ocr, is_ocr_available
                if not is_ocr_available():
                    logger.debug("OCR引擎不可用（请安装 easyocr 或 pytesseract）")
                    return None
                return read_coord_ocr(timeout=2.0, retry_interval=0.3)

            with ThreadPoolExecutor(max_workers=1) as _pool:
                try:
                    ocr_coord = _pool.submit(_do_ocr).result(timeout=OCR_TIMEOUT)
                except FutTimeout:
                    logger.warning(
                        f"OCR 最终验证超时（>{OCR_TIMEOUT}s，可能首次下载模型），"
                        f"视为不可用"
                    )
                    return None
            if ocr_coord is None:
                return (False, "OCR 无法识别坐标")

            ocr_x, ocr_y = float(ocr_coord[0]), float(ocr_coord[1])
            dist = self._calc_distance(ocr_x, ocr_y, target_x, target_y)

            if dist <= tolerance:
                return (
                    True,
                    f"OCR验证通过：坐标=({ocr_x:.1f}, {ocr_y:.1f}), "
                    f"偏差={dist:.2f}px"
                )
            else:
                return (
                    False,
                    f"OCR坐标=({ocr_x:.1f}, {ocr_y:.1f}), "
                    f"目标=({target_x:.1f}, {target_y:.1f}), "
                    f"偏差={dist:.2f}px > 容差={tolerance:.1f}px"
                )
        except ImportError as e:
            logger.debug(f"OCR模块导入失败: {e}")
            return None
        except Exception as e:
            logger.debug(f"OCR验证异常: {e}")
            return (False, f"OCR验证异常: {e}")

    @staticmethod
    def _calc_distance(
        x1: float, y1: float, x2: float, y2: float
    ) -> float:
        """
        计算两点之间的曼哈顿距离（绝对值差之和）。

        使用曼哈顿距离而非欧几里得距离，更适合游戏坐标场景。

        :param x1: 点1 X
        :param y1: 点1 Y
        :param x2: 点2 X
        :param y2: 点2 Y
        :return: 距离（浮点）
        """
        return abs(x1 - x2) + abs(y1 - y2)

    def _interruptible_sleep(self, seconds: float) -> None:
        """
        可中断的 sleep，每 20ms 检查一次停止标志。

        :param seconds: 睡眠时间
        """
        step = 0.02
        elapsed = 0.0
        while elapsed < seconds and not self._stop_flag:
            time.sleep(min(step, seconds - elapsed))
            elapsed += step

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

    # ------------------------------------------------------------------
    # 批量验证（用于多点路径）
    # ------------------------------------------------------------------
    def verify_waypoints(
        self,
        waypoints: List[Tuple[float, float]],
        pid: Optional[int] = None,
        stop_on_fail: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        批量验证多个路径点的到达情况。

        :param waypoints: [(x1,y1), (x2,y2), ...] 路径点列表
        :param pid: 游戏进程 PID
        :param stop_on_fail: 失败时是否立即停止
        :return: 每个点的验证结果列表
        """
        results = []
        for i, (wx, wy) in enumerate(waypoints):
            ok, msg, current = self.verify_arrival(wx, wy, pid=pid)
            result = {
                "index": i,
                "target": (wx, wy),
                "success": ok,
                "message": msg,
                "current": current,
            }
            results.append(result)
            if not ok and stop_on_fail:
                logger.warning(f"路径点 {i} 验证失败，停止继续: {msg}")
                break
            # 短暂间隔
            time.sleep(0.1)
        return results


# ------------------------------------------------------------------
# 便捷函数：单次验证
# ------------------------------------------------------------------
def quick_verify_arrival(
    target_x: float,
    target_y: float,
    pid: int,
    tolerance: float = DEFAULT_TOLERANCE,
    timeout: float = DEFAULT_TIMEOUT,
) -> Tuple[bool, str, Optional[Tuple[float, float]]]:
    """
    便捷函数：快速验证是否到达目标坐标。

    :param target_x: 目标 X 坐标
    :param target_y: 目标 Y 坐标
    :param pid: 游戏进程 PID
    :param tolerance: 坐标容差
    :param timeout: 超时时间
    :return: (is_arrived, message, current_coords)
    """
    verifier = ArrivalVerifier(
        tolerance=tolerance,
        timeout=timeout,
    )
    return verifier.verify_arrival(target_x, target_y, pid)
