# -*- coding: utf-8 -*-
"""
图像识别模块。

提供 ``ImageRecognition`` 类（单例模式），基于 OpenCV 模板匹配实现：
    - 单模板查找（``find_template``）
    - 多实例查找 + 非极大值抑制去重（``find_all_templates``）
    - 多尺度模板匹配（``find_template_multiscale``）
    - 等待模板出现（``wait_for_template``）
    - 指定位置匹配（``match_at``）

坐标约定：所有对外返回的坐标均为客户区坐标（左上角为 0,0），
与 ``core.screen_capture.screen_capture.capture_region`` 的坐标体系一致。

使用方式::

    from core.image_recognition import image_recognition

    # 在全屏查找模板
    pos, conf = image_recognition.find_template("assets/button.png")
    if pos is not None:
        print(f"找到模板，中心坐标 {pos}，置信度 {conf}")

依赖：``core.screen_capture.screen_capture`` 提供截图，
``config.config.config`` 提供默认阈值，
``utils.logger.logger`` 提供日志。
"""
import os
import time
import threading
from typing import Any, Callable, Dict, Optional, List, Tuple, Union

import cv2
import numpy as np
from numpy import ndarray

from core.screen_capture import screen_capture
from config.config import config
from utils.logger import logger


class ImageRecognition:
    """
    图像识别器（单例模式）。

    通过 ``_instance`` 与 ``_lock`` 实现线程安全的单例，
    与 ``ScreenCapture`` 保持一致的单例实现风格。
    使用时直接 ``from core.image_recognition import image_recognition`` 即可。
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
        # 默认匹配阈值，供未显式传入 threshold 时使用
        # config.get 第二个参数为兜底默认值，确保配置缺失时仍为 0.8
        self._default_threshold = float(
            config.get("recognition.template_threshold", 0.8)
        )
        self._initialized = True

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------
    def _load_template(self, path: str) -> Optional[ndarray]:
        """
        加载模板图片为 BGR numpy 数组。

        支持相对路径（相对于项目根目录解析，与 screen_capture.capture_to_file 一致）。
        路径不存在或读取失败时返回 None 并记录错误日志。

        :param path: 模板图片路径（绝对或相对）
        :return: np.ndarray (H, W, 3) BGR；失败返回 None。
        """
        if not path or not isinstance(path, str):
            logger.error(f"模板路径非法: {path!r}")
            return None

        # 相对路径解析到项目根目录（config 已暴露 project_root 属性）
        abs_path = path
        if not os.path.isabs(path):
            abs_path = os.path.join(config.project_root, path)

        if not os.path.exists(abs_path):
            logger.error(f"模板文件不存在: {path}")
            return None

        try:
            # cv2.imread 不支持包含中文的路径（Windows 下会读取失败）。
            # 改用 np.fromfile + cv2.imdecode，绕过路径编码问题。
            img_array = np.fromfile(abs_path, dtype=np.uint8)
            if img_array.size == 0:
                logger.error(f"文件为空或读取失败: {path}")
                return None
            img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
            if img is None:
                logger.error(f"cv2.imdecode 解码失败（格式不支持或文件损坏）: {path}")
                return None
            return img
        except Exception as e:
            logger.error(f"加载模板异常 {path}: {e}")
            return None

    def _get_screenshot(
        self,
        region: Optional[Tuple[int, int, int, int]] = None
    ) -> Optional[ndarray]:
        """
        获取当前客户区截图。

        :param region: (x, y, w, h) 客户区内的子区域；None 表示截取整个客户区。
        :return: BGR np.ndarray；截图失败返回 None。
        """
        try:
            if region is None:
                return screen_capture.capture()
            # region 为 (x, y, w, h)，均为客户区坐标
            x, y, w, h = region
            return screen_capture.capture_region(x, y, w, h)
        except Exception as e:
            logger.error(f"获取截图失败: {e}")
            return None

    def _resolve_threshold(self, threshold: Optional[float]) -> float:
        """
        解析匹配阈值：显式传入优先，否则使用默认值。
        """
        if threshold is None:
            return self._default_threshold
        return float(threshold)

    # ------------------------------------------------------------------
    # 核心识别方法
    # ------------------------------------------------------------------
    def find_template(
        self,
        template_path: str,
        threshold: Optional[float] = None,
        region: Optional[Tuple[int, int, int, int]] = None
    ) -> Tuple[Optional[Tuple[int, int]], float]:
        """
        在当前截图中查找模板图片，返回最佳匹配位置（中心坐标）。

        使用 ``cv2.matchTemplate`` + ``TM_CCOEFF_NORMED`` 进行归一化相关系数匹配。
        匹配得到的最大值位置为匹配框的左上角，加上模板宽高的一半得到中心点。

        :param template_path: 模板图片路径
        :param threshold: 匹配阈值 [0,1]，None 时使用 config 默认值（0.8）
        :param region: (x, y, w, h) 限定搜索区域（客户区坐标）；
                      None 表示全屏（整个客户区）搜索
        :return: ``((x, y), confidence)`` 或 ``(None, 0.0)``（未找到 / 出错时）。
                 x, y 为客户区坐标下的匹配中心点。
        """
        template = self._load_template(template_path)
        if template is None:
            return (None, 0.0)

        screenshot = self._get_screenshot(region)
        if screenshot is None:
            logger.error("find_template: 获取截图失败")
            return (None, 0.0)

        th, tw = template.shape[:2]
        sh, sw = screenshot.shape[:2]
        # 模板大于截图时无法匹配
        if th > sh or tw > sw:
            logger.warning(
                f"模板尺寸 ({tw}x{th}) 大于截图尺寸 ({sw}x{sh})，无法匹配"
            )
            return (None, 0.0)

        thr = self._resolve_threshold(threshold)
        try:
            result = cv2.matchTemplate(screenshot, template, cv2.TM_CCOEFF_NORMED)
            # minMaxLoc 返回 (min_val, max_val, min_loc, max_loc)
            _, max_val, _, max_loc = cv2.minMaxLoc(result)
            if max_val < thr:
                logger.warning(
                    f"模板匹配分数过低: {max_val:.3f} < 阈值 {thr:.3f} "
                    f"(模板: {template_path}, 模板尺寸: {tw}x{th}, "
                    f"截图尺寸: {sw}x{sh})"
                )
                return (None, 0.0)

            # max_loc 为匹配框左上角 (x, y)，加上模板宽高一半得到中心点
            top_left_x, top_left_y = max_loc
            center_x = top_left_x + tw // 2
            center_y = top_left_y + th // 2

            # 若限定了搜索区域，需将局部坐标还原为客户区坐标
            if region is not None:
                rx, ry = region[0], region[1]
                center_x += rx
                center_y += ry

            return ((int(center_x), int(center_y)), float(max_val))
        except Exception as e:
            logger.error(f"find_template 匹配异常: {e}")
            return (None, 0.0)

    def find_all_templates(
        self,
        template_path: str,
        threshold: Optional[float] = None,
        region: Optional[Tuple[int, int, int, int]] = None
    ) -> List[Tuple[Tuple[int, int], float]]:
        """
        查找所有匹配位置（多实例匹配）。

        对 matchTemplate 结果矩阵使用非极大值抑制（NMS）去重：
        每次取全局最大值作为候选，并将其周围一个模板大小的区域置零，
        重复直到剩余最大值低于阈值。

        :param template_path: 模板图片路径
        :param threshold: 匹配阈值，None 时使用 config 默认值
        :param region: (x, y, w, h) 限定搜索区域；None 表示全屏搜索
        :return: ``[((x, y), confidence), ...]``，按置信度降序排列；
                 未找到返回空列表。
        """
        template = self._load_template(template_path)
        if template is None:
            return []

        screenshot = self._get_screenshot(region)
        if screenshot is None:
            logger.error("find_all_templates: 获取截图失败")
            return []

        th, tw = template.shape[:2]
        sh, sw = screenshot.shape[:2]
        if th > sh or tw > sw:
            logger.warning(
                f"模板尺寸 ({tw}x{th}) 大于截图尺寸 ({sw}x{sh})，无法匹配"
            )
            return []

        thr = self._resolve_threshold(threshold)
        try:
            result = cv2.matchTemplate(screenshot, template, cv2.TM_CCOEFF_NORMED)
        except Exception as e:
            logger.error(f"find_all_templates 匹配异常: {e}")
            return []

        # 非极大值抑制：拷贝结果矩阵，反复取最大值并抑制邻域
        result_copy = result.copy()
        matches = []
        while True:
            _, max_val, _, max_loc = cv2.minMaxLoc(result_copy)
            if max_val < thr:
                break

            top_left_x, top_left_y = max_loc
            center_x = top_left_x + tw // 2
            center_y = top_left_y + th // 2

            # 局部坐标还原为客户区坐标
            if region is not None:
                rx, ry = region[0], region[1]
                center_x += rx
                center_y += ry

            matches.append(((int(center_x), int(center_y)), float(max_val)))

            # 将当前峰值周围一个模板大小的区域置零，避免重复检测
            x1 = max(0, top_left_x - tw // 2)
            x2 = min(result_copy.shape[1], top_left_x + tw // 2 + 1)
            y1 = max(0, top_left_y - th // 2)
            y2 = min(result_copy.shape[0], top_left_y + th // 2 + 1)
            result_copy[y1:y2, x1:x2] = 0.0

        # matches 已按发现顺序（即置信度降序）排列
        return matches

    def find_template_multiscale(
        self,
        template_path: str,
        threshold: Optional[float] = None,
        scales: Optional[List[float]] = None
    ) -> Tuple[Optional[Tuple[int, int]], float, Optional[float]]:
        """
        多尺度模板匹配。

        对模板按不同缩放比例进行缩放后分别执行 matchTemplate，
        返回所有尺度中的最佳匹配。适用于模板与目标存在尺寸差异的场景。

        :param template_path: 模板图片路径
        :param threshold: 匹配阈值，None 时使用 config 默认值
        :param scales: 缩放比例列表，默认 [0.8, 0.9, 1.0, 1.1, 1.2]
        :return: ``((x, y), confidence, scale)``；
                 未找到时返回 ``(None, 0.0, None)``。
        """
        if scales is None:
            scales = [0.8, 0.9, 1.0, 1.1, 1.2]

        template = self._load_template(template_path)
        if template is None:
            return (None, 0.0, None)

        screenshot = self._get_screenshot()
        if screenshot is None:
            logger.error("find_template_multiscale: 获取截图失败")
            return (None, 0.0, None)

        thr = self._resolve_threshold(threshold)
        sh, sw = screenshot.shape[:2]

        best_pos = None
        best_val = 0.0
        best_scale = None

        try:
            for scale in scales:
                if scale <= 0:
                    continue

                # 按比例缩放模板
                th, tw = template.shape[:2]
                new_w = max(1, int(round(tw * scale)))
                new_h = max(1, int(round(th * scale)))
                scaled_template = cv2.resize(
                    template, (new_w, new_h), interpolation=cv2.INTER_AREA
                )

                # 缩放后模板大于截图则跳过
                if new_h > sh or new_w > sw:
                    continue

                result = cv2.matchTemplate(
                    screenshot, scaled_template, cv2.TM_CCOEFF_NORMED
                )
                _, max_val, _, max_loc = cv2.minMaxLoc(result)

                if max_val > best_val:
                    best_val = max_val
                    top_left_x, top_left_y = max_loc
                    # 中心点需用缩放后模板的宽高计算
                    center_x = top_left_x + new_w // 2
                    center_y = top_left_y + new_h // 2
                    best_pos = (int(center_x), int(center_y))
                    best_scale = float(scale)
        except Exception as e:
            logger.error(f"find_template_multiscale 匹配异常: {e}")
            return (None, 0.0, None)

        # 未达到阈值视为未找到
        if best_pos is None or best_val < thr:
            return (None, 0.0, None)

        return (best_pos, float(best_val), best_scale)

    def find_best_template(
        self,
        template_paths: List[str],
        threshold: Optional[float] = None,
        region: Optional[Tuple[int, int, int, int]] = None
    ) -> Tuple[Optional[Tuple[int, int]], float, Optional[str]]:
        """
        在当前截图中查找多个模板中的最佳匹配。

        对每个模板逐一匹配，返回置信度最高的那个。
        仅一次截图，所有模板复用同一张截图，减少 I/O 开销。

        :param template_paths: 模板图片路径列表
        :param threshold: 匹配阈值，None 时使用 config 默认值
        :param region: (x, y, w, h) 限定搜索区域
        :return: ``((x, y), confidence, template_path)``；
                 全部未找到返回 ``(None, 0.0, None)``。
        """
        if not template_paths:
            return (None, 0.0, None)

        thr = self._resolve_threshold(threshold)
        screenshot = self._get_screenshot(region)
        if screenshot is None:
            logger.error("find_best_template: 获取截图失败")
            return (None, 0.0, None)

        best_pos = None
        best_val = 0.0
        best_path = None

        for path in template_paths:
            template = self._load_template(path)
            if template is None:
                continue

            th, tw = template.shape[:2]
            sh, sw = screenshot.shape[:2]
            if th > sh or tw > sw:
                logger.debug(
                    f"模板 {path} 尺寸 ({tw}x{th}) > 截图尺寸 ({sw}x{sh})，跳过"
                )
                continue

            try:
                result = cv2.matchTemplate(
                    screenshot, template, cv2.TM_CCOEFF_NORMED
                )
                _, max_val, _, max_loc = cv2.minMaxLoc(result)

                if max_val >= thr and max_val > best_val:
                    top_left_x, top_left_y = max_loc
                    center_x = top_left_x + tw // 2
                    center_y = top_left_y + th // 2
                    if region is not None:
                        center_x += region[0]
                        center_y += region[1]
                    best_pos = (int(center_x), int(center_y))
                    best_val = float(max_val)
                    best_path = path
            except Exception as e:
                logger.error(f"find_best_template 匹配 {path} 异常: {e}")

        if best_pos is None:
            return (None, 0.0, None)
        return (best_pos, best_val, best_path)

    def wait_for_any_template(
        self,
        template_paths: List[str],
        timeout: float = 10.0,
        interval: float = 0.5,
        threshold: Optional[float] = None,
        region: Optional[Tuple[int, int, int, int]] = None
    ) -> Tuple[Optional[Tuple[int, int]], float, Optional[str]]:
        """
        等待多个模板中的任意一个出现。

        每轮截图后遍历所有模板，返回第一个匹配成功的。

        :param template_paths: 模板图片路径列表
        :param timeout: 超时时间（秒）
        :param interval: 轮询间隔（秒）
        :param threshold: 匹配阈值
        :param region: 限定搜索区域
        :return: ``((x, y), confidence, template_path)``；超时返回 ``(None, 0.0, None)``
        """
        if not template_paths:
            return (None, 0.0, None)

        # 预加载所有模板
        loaded = []
        for path in template_paths:
            tpl = self._load_template(path)
            if tpl is not None:
                loaded.append((path, tpl))
        if not loaded:
            return (None, 0.0, None)

        thr = self._resolve_threshold(threshold)
        start_time = time.time()

        while True:
            elapsed = time.time() - start_time
            if elapsed >= timeout:
                logger.info(
                    f"wait_for_any_template 超时 ({timeout}s): "
                    f"共 {len(template_paths)} 个模板"
                )
                return (None, 0.0, None)

            screenshot = self._get_screenshot(region)
            if screenshot is not None:
                for path, template in loaded:
                    th, tw = template.shape[:2]
                    sh, sw = screenshot.shape[:2]
                    if th > sh or tw > sw:
                        continue
                    try:
                        result = cv2.matchTemplate(
                            screenshot, template, cv2.TM_CCOEFF_NORMED
                        )
                        _, max_val, _, max_loc = cv2.minMaxLoc(result)
                        if max_val >= thr:
                            top_left_x, top_left_y = max_loc
                            center_x = top_left_x + tw // 2
                            center_y = top_left_y + th // 2
                            if region is not None:
                                center_x += region[0]
                                center_y += region[1]
                            return (
                                (int(center_x), int(center_y)),
                                float(max_val),
                                path,
                            )
                    except Exception as e:
                        logger.error(
                            f"wait_for_any_template 匹配 {path} 异常: {e}"
                        )

            remaining = timeout - (time.time() - start_time)
            if remaining <= 0:
                return (None, 0.0, None)
            time.sleep(min(interval, remaining))

    def wait_for_any_template_disappear(
        self,
        template_paths: List[str],
        timeout: float = 10.0,
        interval: float = 0.5,
        threshold: Optional[float] = None,
        region: Optional[Tuple[int, int, int, int]] = None
    ) -> bool:
        """
        等待所有模板都从屏幕上消失。

        只要有一个模板仍匹配，就继续等待；全部消失才算成功。

        :param template_paths: 模板图片路径列表
        :param timeout: 超时时间（秒）
        :param interval: 轮询间隔（秒）
        :param threshold: 匹配阈值
        :param region: 限定搜索区域
        :return: 全部消失返回 True；超时仍有存在返回 False
        """
        if not template_paths:
            return True

        start_time = time.time()

        while True:
            elapsed = time.time() - start_time
            if elapsed >= timeout:
                logger.info(
                    f"wait_for_any_template_disappear 超时 ({timeout}s)"
                )
                return False

            any_visible = False
            for path in template_paths:
                pos, _ = self.find_template(
                    path, threshold=threshold, region=region
                )
                if pos is not None:
                    any_visible = True
                    break

            if not any_visible:
                logger.info("所有模板已消失")
                return True

            remaining = timeout - (time.time() - start_time)
            if remaining <= 0:
                return False
            time.sleep(min(interval, remaining))

    def wait_for_template(
        self,
        template_path: str,
        timeout: float = 10.0,
        interval: float = 0.5,
        threshold: Optional[float] = None,
        region: Optional[Tuple[int, int, int, int]] = None,
        should_stop_cb: Optional[Callable[[], bool]] = None,
    ) -> Tuple[Optional[Tuple[int, int]], float]:
        """
        等待模板在屏幕上出现。

        每隔 interval 秒截图并匹配一次，直到匹配成功或超时。

        :param template_path: 模板图片路径
        :param timeout: 超时时间（秒），默认 10.0
        :param interval: 轮询间隔（秒），默认 0.5
        :param threshold: 匹配阈值，None 时使用 config 默认值
        :param region: (x, y, w, h) 限定搜索区域（客户区坐标）；
                      None 表示全屏（整个客户区）搜索
        :param should_stop_cb: 外部停止回调（任务引擎停止时置 True），
                      返回 True 立即中止等待（2026-08-05 10:35 新增，
                      修复"停止后任务引擎卡在正在停止"问题）。
        :return: 出现时返回 ``((x, y), confidence)``；
                 超时返回 ``(None, 0.0)``。
        """
        # 预加载模板一次，避免每次轮询都重新读盘
        template = self._load_template(template_path)
        if template is None:
            return (None, 0.0)

        thr = self._resolve_threshold(threshold)
        start_time = time.time()

        while True:
            # 外部停止信号检查（可中断等待）
            if should_stop_cb is not None and should_stop_cb():
                logger.info(
                    f"wait_for_template 被外部停止信号中断: {template_path}"
                )
                return (None, 0.0)

            elapsed = time.time() - start_time
            if elapsed >= timeout:
                logger.info(
                    f"wait_for_template 超时 ({timeout}s): {template_path}"
                )
                return (None, 0.0)

            screenshot = self._get_screenshot(region)
            if screenshot is not None:
                th, tw = template.shape[:2]
                sh, sw = screenshot.shape[:2]
                if th <= sh and tw <= sw:
                    try:
                        result = cv2.matchTemplate(
                            screenshot, template, cv2.TM_CCOEFF_NORMED
                        )
                        _, max_val, _, max_loc = cv2.minMaxLoc(result)
                        if max_val >= thr:
                            top_left_x, top_left_y = max_loc
                            center_x = top_left_x + tw // 2
                            center_y = top_left_y + th // 2
                            # 若限定了搜索区域，需将局部坐标还原为客户区坐标
                            if region is not None:
                                center_x += region[0]
                                center_y += region[1]
                            return (
                                (int(center_x), int(center_y)),
                                float(max_val),
                            )
                    except Exception as e:
                        logger.error(f"wait_for_template 匹配异常: {e}")

            # 等待下一轮（注意：剩余等待时间不超过 timeout - elapsed，避免超时后多睡）
            remaining = timeout - (time.time() - start_time)
            if remaining <= 0:
                return (None, 0.0)
            time.sleep(min(interval, remaining))

    def wait_for_template_disappear(
        self,
        template_path: str,
        timeout: float = 10.0,
        interval: float = 0.5,
        threshold: Optional[float] = None,
        region: Optional[Tuple[int, int, int, int]] = None,
        should_stop_cb: Optional[Callable[[], bool]] = None,
    ) -> bool:
        """
        等待模板从屏幕上消失。

        每隔 interval 秒截图并匹配一次，直到模板不再匹配（已消失）或超时。
        与 :meth:`wait_for_template` 互为对偶：前者等“出现”，本方法等“消失”。

        :param template_path: 模板图片路径
        :param timeout: 超时时间（秒），默认 10.0
        :param interval: 轮询间隔（秒），默认 0.5
        :param threshold: 匹配阈值，None 时使用 config 默认值
        :param region: (x, y, w, h) 限定搜索区域（客户区坐标）；
                      None 表示全屏（整个客户区）搜索
        :param should_stop_cb: 外部停止回调（2026-08-05 10:35 新增，
                      可中断等待，修复任务引擎停止卡住）。
        :return: 模板已消失返回 ``True``；超时仍存在返回 ``False``。
        """
        start_time = time.time()

        while True:
            # 外部停止信号检查（可中断等待）
            if should_stop_cb is not None and should_stop_cb():
                logger.info(
                    f"wait_for_template_disappear 被外部停止信号中断: "
                    f"{template_path}"
                )
                return False

            elapsed = time.time() - start_time
            if elapsed >= timeout:
                logger.info(
                    f"wait_for_template_disappear 超时 ({timeout}s)，"
                    f"模板仍存在: {template_path}"
                )
                return False

            # 复用 find_template：返回 None 即表示当前帧未匹配到（已消失）
            pos, _ = self.find_template(
                template_path, threshold=threshold, region=region
            )
            if pos is None:
                logger.info(f"模板已消失: {template_path}")
                return True

            # 等待下一轮（剩余等待时间不超过 timeout - elapsed，避免超时后多睡）
            remaining = timeout - (time.time() - start_time)
            if remaining <= 0:
                return False
            time.sleep(min(interval, remaining))

    def find_text_by_color(
        self,
        template_path: str,
        source_color: str = "ffffff",
        target_color: str = "ff0000",
        color_tolerance: int = 15,
        threshold: float = 0.6,
        region: Optional[Tuple[int, int, int, int]] = None,
    ) -> Tuple[Optional[Tuple[int, int]], float]:
        """
        基于颜色的文本检测：在截图中找到目标颜色（如红色）的文本，
        其形状与模板中源颜色（如白色）的文本相似。

        核心思路：
        1. 从模板图中提取源颜色（source_color）像素的二值掩码
        2. 从截图中提取目标颜色（target_color）像素的二值掩码
        3. 对两个二值掩码做形状匹配（cv2.matchTemplate）
        4. 返回匹配位置和置信度

        颜色容差说明：
        - 白色(#FFFFFF)检测：低饱和度+高亮度，BGR范围约 [240,240,240]~[255,255,255]
        - 红色(#FF0000)检测：红色色相，BGR范围约 [0,0,240]~[20,20,255]
        - color_tolerance 用于扩展颜色范围，处理抗锯齿、渐变等

        :param template_path: 模板图片路径（包含源颜色文本）
        :param source_color: 模板中源文本颜色（hex，如 "ffffff"）
        :param target_color: 截图中目标文本颜色（hex，如 "ff0000"）
        :param color_tolerance: 颜色容差（0-255，越大范围越宽）
        :param threshold: 形状匹配阈值 [0,1]，默认 0.6（部分匹配即可）
        :param region: (x, y, w, h) 限定搜索区域；None 表示全屏
        :return: ``((x, y), confidence)`` 或 ``(None, 0.0)``
        """
        template = self._load_template(template_path)
        if template is None:
            return (None, 0.0)

        screenshot = self._get_screenshot(region)
        if screenshot is None:
            logger.error("find_text_by_color: 获取截图失败")
            return (None, 0.0)

        try:
            # 提取源颜色掩码（模板中）
            source_mask = self._extract_color_mask(
                template, source_color, color_tolerance
            )
            # 提取目标颜色掩码（截图中）
            target_mask = self._extract_color_mask(
                screenshot, target_color, color_tolerance
            )

            if source_mask is None or target_mask is None:
                logger.error("find_text_by_color: 颜色掩码提取失败")
                return (None, 0.0)

            # 膨胀掩码使形状匹配更宽容
            kernel = np.ones((2, 2), np.uint8)
            source_mask = cv2.dilate(source_mask, kernel, iterations=1)
            target_mask = cv2.dilate(target_mask, kernel, iterations=1)

            # 对掩码做形状匹配
            sh, sw = source_mask.shape[:2]
            th, tw = target_mask.shape[:2]

            if sh > th or sw > tw:
                logger.warning(
                    f"源掩码尺寸 ({sw}x{sh}) 大于目标掩码尺寸 ({tw}x{th})"
                )
                return (None, 0.0)

            result = cv2.matchTemplate(
                target_mask, source_mask, cv2.TM_CCOEFF_NORMED
            )
            _, max_val, _, max_loc = cv2.minMaxLoc(result)

            if max_val < threshold:
                return (None, 0.0)

            # 计算匹配中心点
            top_left_x, top_left_y = max_loc
            center_x = top_left_x + sw // 2
            center_y = top_left_y + sh // 2

            # 还原为客户区坐标
            if region is not None:
                rx, ry = region[0], region[1]
                center_x += rx
                center_y += ry

            return ((int(center_x), int(center_y)), float(max_val))
        except Exception as e:
            logger.error(f"find_text_by_color 异常: {e}")
            return (None, 0.0)

    def find_all_by_color(
        self,
        template_path: str,
        source_color: str = "ffffff",
        target_color: str = "ff0000",
        color_tolerance: int = 15,
        threshold: float = 0.6,
        region: Optional[Tuple[int, int, int, int]] = None,
    ) -> List[Tuple[Tuple[int, int], float]]:
        """
        查找所有匹配的彩色文本位置（多实例）。

        与 ``find_text_by_color`` 类似，但返回所有匹配位置。

        :param template_path: 模板图片路径
        :param source_color: 源文本颜色（hex）
        :param target_color: 目标文本颜色（hex）
        :param color_tolerance: 颜色容差
        :param threshold: 匹配阈值
        :param region: 限定搜索区域
        :return: ``[((x, y), confidence), ...]``
        """
        template = self._load_template(template_path)
        if template is None:
            return []

        screenshot = self._get_screenshot(region)
        if screenshot is None:
            return []

        try:
            source_mask = self._extract_color_mask(
                template, source_color, color_tolerance
            )
            target_mask = self._extract_color_mask(
                screenshot, target_color, color_tolerance
            )

            if source_mask is None or target_mask is None:
                return []

            # 膨胀
            kernel = np.ones((2, 2), np.uint8)
            source_mask = cv2.dilate(source_mask, kernel, iterations=1)
            target_mask = cv2.dilate(target_mask, kernel, iterations=1)

            sh, sw = source_mask.shape[:2]
            th, tw = target_mask.shape[:2]

            if sh > th or sw > tw:
                return []

            result = cv2.matchTemplate(
                target_mask, source_mask, cv2.TM_CCOEFF_NORMED
            )

            # 非极大值抑制
            result_copy = result.copy()
            matches = []
            while True:
                _, max_val, _, max_loc = cv2.minMaxLoc(result_copy)
                if max_val < threshold:
                    break

                top_left_x, top_left_y = max_loc
                center_x = top_left_x + sw // 2
                center_y = top_left_y + sh // 2

                if region is not None:
                    rx, ry = region[0], region[1]
                    center_x += rx
                    center_y += ry

                matches.append(((int(center_x), int(center_y)), float(max_val)))

                # 抑制邻域
                x1 = max(0, top_left_x - sw // 2)
                x2 = min(result_copy.shape[1], top_left_x + sw // 2 + 1)
                y1 = max(0, top_left_y - sh // 2)
                y2 = min(result_copy.shape[0], top_left_y + sh // 2 + 1)
                result_copy[y1:y2, x1:x2] = 0.0

            return matches
        except Exception as e:
            logger.error(f"find_all_by_color 异常: {e}")
            return []

    # ------------------------------------------------------------------
    # 颜色提取辅助方法
    # ------------------------------------------------------------------
    @staticmethod
    def _hex_to_bgr(hex_color: str) -> Tuple[int, int, int]:
        """
        将十六进制颜色代码转换为 BGR 元组。

        :param hex_color: 十六进制颜色（如 "ffffff" 或 "#ffffff"）
        :return: (B, G, R) 元组
        """
        hex_str = hex_color.lstrip("#")
        r = int(hex_str[0:2], 16)
        g = int(hex_str[2:4], 16)
        b = int(hex_str[4:6], 16)
        return (b, g, r)

    @staticmethod
    def _extract_color_mask(
        image: ndarray,
        hex_color: str,
        tolerance: int = 15
    ) -> Optional[ndarray]:
        """
        从图像中提取指定颜色的掩码。

        通过颜色容差范围匹配，处理抗锯齿和渐变。
        - 白色：BGR 各通道接近 255
        - 红色：R 通道高，G/B 通道低
        - 其他颜色：使用 HSV 颜色空间匹配

        :param image: BGR numpy 数组
        :param hex_color: 目标颜色（hex）
        :param tolerance: 颜色容差
        :return: 二值掩码（0/255），失败返回 None
        """
        try:
            b, g, r = ImageRecognition._hex_to_bgr(hex_color)

            # 白色检测：所有通道都高
            if r >= 240 and g >= 240 and b >= 240:
                lower = np.array([max(0, b - tolerance), max(0, g - tolerance), max(0, r - tolerance)])
                upper = np.array([255, 255, 255])
                mask = cv2.inRange(image, lower, upper)
                return mask

            # 红色检测：R 通道高，G/B 通道低
            if r > 200 and g < 100 and b < 100:
                # 在 HSV 空间检测红色
                hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
                # 红色在 HSV 中的范围（两个区间）
                lower_red1 = np.array([0, 100, max(100, 255 - tolerance)])
                upper_red1 = np.array([10, 255, 255])
                lower_red2 = np.array([160, 100, max(100, 255 - tolerance)])
                upper_red2 = np.array([180, 255, 255])
                mask1 = cv2.inRange(hsv, lower_red1, upper_red1)
                mask2 = cv2.inRange(hsv, lower_red2, upper_red2)
                mask = cv2.bitwise_or(mask1, mask2)
                return mask

            # 其他颜色：使用 BGR 范围匹配
            lower = np.array([max(0, b - tolerance), max(0, g - tolerance), max(0, r - tolerance)])
            upper = np.array([min(255, b + tolerance), min(255, g + tolerance), min(255, r + tolerance)])
            mask = cv2.inRange(image, lower, upper)
            return mask
        except Exception as e:
            logger.error(f"_extract_color_mask 异常: {e}")
            return None

    def match_at(
        self,
        template_path: str,
        x: int,
        y: int,
        threshold: Optional[float] = None
    ) -> bool:
        """
        检查指定位置是否匹配模板。

        截取以 (x, y) 为中心、模板大小的区域，与模板进行匹配，
        判断该位置是否就是模板对应的内容。

        :param template_path: 模板图片路径
        :param x: 客户区 X 坐标（中心点）
        :param y: 客户区 Y 坐标（中心点）
        :param threshold: 匹配阈值，None 时使用 config 默认值
        :return: bool，是否匹配成功。
        """
        template = self._load_template(template_path)
        if template is None:
            return False

        th, tw = template.shape[:2]
        # 计算以 (x, y) 为中心的截取区域左上角
        crop_x = int(x - tw // 2)
        crop_y = int(y - th // 2)

        screenshot = self._get_screenshot((crop_x, crop_y, tw, th))
        if screenshot is None:
            logger.error("match_at: 获取截图失败")
            return False

        # 截取区域可能因边界裁剪而尺寸不足，无法直接与模板比较
        if screenshot.shape[0] < th or screenshot.shape[1] < tw:
            logger.warning(
                f"match_at: 截取区域 ({screenshot.shape[1]}x{screenshot.shape[0]}) "
                f"小于模板 ({tw}x{th})，可能越出客户区边界"
            )
            return False

        thr = self._resolve_threshold(threshold)
        try:
            result = cv2.matchTemplate(screenshot, template, cv2.TM_CCOEFF_NORMED)
            # 截取区域与模板同尺寸时，result 为 1x1 矩阵
            _, max_val, _, _ = cv2.minMaxLoc(result)
            return max_val >= thr
        except Exception as e:
            logger.error(f"match_at 匹配异常: {e}")
            return False

    # ------------------------------------------------------------------
    # 黄色任务追踪点检测
    # ------------------------------------------------------------------
    def find_yellow_regions(
        self,
        screenshot: Optional[ndarray] = None,
        region: Optional[Tuple[int, int, int, int]] = None,
        min_area: int = 50,
        yellow_h_range: Tuple[int, int] = (15, 35),
        yellow_s_min: int = 100,
        yellow_v_min: int = 100,
        merge_overlapping: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        检测屏幕上的黄色区域（用于识别游戏任务追踪点）。

        梦幻西游的任务追踪面板通常使用黄色字体显示目标地点和坐标。
        本方法通过 HSV 颜色空间检测高饱和度的黄色区域。

        :param screenshot: 可选，输入图像；None 则自动截取当前屏幕
        :param region: 可选，限定检测区域 (x, y, w, h)
        :param min_area: 最小区域面积（像素），过滤噪点
        :param yellow_h_range: 黄色色相范围 (H_min, H_max)，默认 (15, 35)
        :param yellow_s_min: 最小饱和度，默认 100
        :param yellow_v_min: 最小亮度，默认 100
        :param merge_overlapping: 是否合并重叠区域
        :return: 检测到的黄色区域列表
            [{"x": int, "y": int, "w": int, "h": int, "center": (cx, cy), "area": int}, ...]
            按面积降序排列
        """
        # 获取截图
        if screenshot is None:
            screenshot = self._get_screenshot(region)
        if screenshot is None:
            logger.error("find_yellow_regions: 获取截图失败")
            return []

        # 转换到 HSV 颜色空间
        hsv = cv2.cvtColor(screenshot, cv2.COLOR_BGR2HSV)

        # 提取 H、S、V 通道
        h_channel = hsv[:, :, 0]
        s_channel = hsv[:, :, 1]
        v_channel = hsv[:, :, 2]

        # 黄色掩码：H 在范围内 + 高饱和度 + 适度亮度
        h_min, h_max = yellow_h_range
        mask = (
            (h_channel >= h_min) & (h_channel <= h_max) &
            (s_channel >= yellow_s_min) &
            (v_channel >= yellow_v_min)
        ).astype(np.uint8) * 255

        # 形态学处理：去噪 + 填充
        kernel = np.ones((3, 3), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)

        # 查找连通区域
        contours, _ = cv2.findContours(
            mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )

        # 提取区域信息
        regions = []
        for contour in contours:
            area = cv2.contourArea(contour)
            if area < min_area:
                continue
            x, y, w, h = cv2.boundingRect(contour)
            cx, cy = x + w // 2, y + h // 2
            regions.append({
                "x": int(x),
                "y": int(y),
                "w": int(w),
                "h": int(h),
                "center": (int(cx), int(cy)),
                "area": int(area),
            })

        # 按面积降序排列
        regions.sort(key=lambda r: r["area"], reverse=True)

        if merge_overlapping and regions:
            regions = self._merge_overlapping_regions(regions)

        return regions

    def _merge_overlapping_regions(
        self, regions: List[Dict[str, Any]], overlap_threshold: float = 0.3
    ) -> List[Dict[str, Any]]:
        """
        合并重叠的矩形区域。

        :param regions: 区域列表
        :param overlap_threshold: 重叠阈值（IoU），超过则合并
        :return: 合并后的区域列表
        """
        if len(regions) <= 1:
            return regions

        merged = []
        used = [False] * len(regions)

        for i, r1 in enumerate(regions):
            if used[i]:
                continue
            current = r1.copy()
            for j in range(i + 1, len(regions)):
                if used[j]:
                    continue
                r2 = regions[j]
                # 计算 IoU (Intersection over Union)
                intersection = self._compute_intersection(current, r2)
                if intersection > 0:
                    area1 = current["area"]
                    area2 = r2["area"]
                    iou = intersection / min(area1, area2)
                    if iou >= overlap_threshold:
                        # 合并区域
                        used[j] = True
                        current = self._merge_two_regions(current, r2)
            merged.append(current)

        # 重新计算面积并排序
        for r in merged:
            r["area"] = r["w"] * r["h"]
            r["center"] = (r["x"] + r["w"] // 2, r["y"] + r["h"] // 2)
        merged.sort(key=lambda r: r["area"], reverse=True)

        return merged

    def _compute_intersection(
        self, r1: Dict[str, Any], r2: Dict[str, Any]
    ) -> int:
        """计算两个矩形的交集面积。"""
        x1 = max(r1["x"], r2["x"])
        y1 = max(r1["y"], r2["y"])
        x2 = min(r1["x"] + r1["w"], r2["x"] + r2["w"])
        y2 = min(r1["y"] + r1["h"], r2["y"] + r2["h"])
        if x1 < x2 and y1 < y2:
            return (x2 - x1) * (y2 - y1)
        return 0

    def _merge_two_regions(
        self, r1: Dict[str, Any], r2: Dict[str, Any]
    ) -> Dict[str, Any]:
        """合并两个矩形为包含两者的最小矩形。"""
        x1 = min(r1["x"], r2["x"])
        y1 = min(r1["y"], r2["y"])
        x2 = max(r1["x"] + r1["w"], r2["x"] + r2["w"])
        y2 = max(r1["y"] + r1["h"], r2["y"] + r2["h"])
        return {
            "x": x1,
            "y": y1,
            "w": x2 - x1,
            "h": y2 - y1,
            "center": ((x1 + x2) // 2, (y1 + y2) // 2),
            "area": (x2 - x1) * (y2 - y1),
        }

    def find_yellow_task_tracker(
        self,
        region: Optional[Tuple[int, int, int, int]] = None,
        min_area: int = 100,
        task_keywords: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        查找游戏任务追踪面板（黄色区域）。

        梦幻西游的任务追踪面板通常显示在屏幕右侧，包含：
        - 任务名称（黄色）
        - 目标地点和坐标（黄色）
        - 进度信息（黄色）

        :param region: 限定搜索区域，None 则全屏
        :param min_area: 最小区域面积
        :param task_keywords: 任务关键词列表（用于过滤）
        :return: 找到的任务追踪面板信息
            {"center": (x, y), "bounds": (x, y, w, h), "confidence": float}
            未找到返回 None
        """
        # 检测黄色区域
        yellow_regions = self.find_yellow_regions(
            region=region, min_area=min_area
        )

        if not yellow_regions:
            logger.debug("未检测到黄色区域")
            return None

        # 过滤出较大的黄色区域（任务面板通常比较大）
        large_regions = [r for r in yellow_regions if r["area"] >= min_area * 5]

        if not large_regions:
            large_regions = yellow_regions

        # 返回最大的黄色区域（最可能是任务面板）
        best = large_regions[0]

        logger.info(
            f"检测到黄色任务追踪点: 中心={best['center']}, "
            f"边界=({best['x']},{best['y']},{best['w']},{best['h']}), "
            f"面积={best['area']}"
        )

        return {
            "center": best["center"],
            "bounds": (best["x"], best["y"], best["w"], best["h"]),
            "area": best["area"],
            "all_regions": yellow_regions,
        }


# 模块级单例实例，供全局使用
image_recognition = ImageRecognition()
