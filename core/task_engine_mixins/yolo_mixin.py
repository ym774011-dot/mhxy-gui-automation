# -*- coding: utf-8 -*-
"""
yolo_mixin - TaskEngine 拆分的YOLO 检测/动作方法组。

拆分自 core/task_engine.py（2026-08-10 巨型文件重构）。
方法通过 Mixin 多继承并入 TaskEngine，对外接口完全不变。
"""

import time
import re
import json
import random
from typing import Dict, List, Optional, Any, Tuple, Union

from models.event import Event, EventType
from models.task import Task
from models.task_sequence import TaskSequence
from core.location_data_container import (
    LocationDataContainer,
    get_global_location_container,
    reset_global_location_container,
    clear_global_location_container,
)
from utils.logger import logger
from utils.helpers import delay
from config.config import config


from core.input_controller import input_controller
from core.task_library_manager import task_library
from core.image_recognition import image_recognition

class YoloMixin:
    """YOLO 目标检测、选目标、动作执行、兜底。"""

    def _execute_yolo_detect(self, params):
        """
        YOLO 目标检测事件执行器。

        优先使用 YOLO 模型推理，失败时降级为模板匹配。

        params 结构：
            {"template_path": "", "threshold": 0.8,
             "action": "click"/"wait"/"record", "region": [x,y,w,h]}

        action 行为：
            - click：找到后点击目标中心
            - wait：等待目标出现（阻塞）
            - record：仅记录检测结果，不点击

        :param params: 事件参数
        :return: (success, result)
        """
        # 尝试使用YOLO模型推理
        # _get_yolo_detector 定义于主模块 core/task_engine.py（延迟导入单例）。
        # 必须运行时局部导入：① task_engine 是父模块，模块级导入会循环；
        # ② 测试通过 patch task_engine._get_yolo_detector 注入 fake，运行时取模块属性才能生效
        #    （与 click_mixin._do_click 取 input_controller 的模式一致）。
        from core.task_engine import _get_yolo_detector
        yolo = _get_yolo_detector()
        if yolo is not None and hasattr(yolo, 'model') and yolo.model is not None:
            try:
                # 延迟导入 screen_capture
                from core.screen_capture import screen_capture

                # 截取当前窗口
                screenshot = screen_capture.capture()

                if screenshot is not None:
                    # YOLO推理
                    logger.info("YOLO模型推理中...")
                    results = yolo.detect(screenshot)

                    if results:
                        # 真推理成功：按配置 action（click/wait/record）执行，
                        # 不再永远当 record 处理（P1 #2 真缺口）
                        return self._execute_yolo_action(yolo, results, params)
                    else:
                        logger.warning("YOLO推理未检测到目标，降级为模板匹配")
                else:
                    logger.warning("截图失败，无法进行YOLO推理，降级为模板匹配")

            except Exception as e:
                logger.error(f"YOLO推理失败: {e}")

        # 降级到模板匹配
        logger.warning("YOLO模型未配置或推理失败，降级为模板匹配")
        return self._execute_yolo_fallback(params)

    # ------------------------------------------------------------------
    # YOLO 真推理动作执行（与模板降级路径共用 _do_click / _do_additional_click）
    # ------------------------------------------------------------------

    def _yolo_pick_target(self, results, target_class):
        """
        从 YOLO 检测结果中选目标。

        - 指定 ``target_class`` 时只保留该类别（区分同名 NPC/物体）；
        - 否则取置信度最高者（``detect`` 已按置信度降序）。

        :return: 选中的检测字典，或 None
        """
        if not results:
            return None
        if target_class:
            filtered = [r for r in results
                        if str(r.get("class", "")) == str(target_class)]
            return filtered[0] if filtered else None
        return results[0]

    def _execute_yolo_action(self, yolo, results, params):
        """
        YOLO 真推理成功后的动作执行（让 "YOLO 事件" 名副其实）。

        与 ``_execute_yolo_fallback`` 的模板匹配动作对称：

        - action == "click"：点最佳目标中心（可选 ``target_class`` 过滤 + 附加点击）
        - action == "wait" ：轮询检测直到目标出现（可选点击），超时返回失败
        - 其它（含 "record"）：仅返回检测结果

        :param yolo: yolo_detector 单例（wait 模式需要持续检测）
        :param results: ``yolo.detect`` 的首帧结果
        :param params: 事件参数
        :return: (success, result)
        """
        action = str(params.get("action", "record")).lower()
        target_class = str(params.get("target_class", "") or "").strip()
        button = str(params.get("button", "left")).lower()
        try:
            click_delay_ms = int(params.get("click_delay", 1000) or 1000)
        except (TypeError, ValueError):
            click_delay_ms = 1000

        # 附加点击参数（与模板降级路径一致）
        additional_click_enabled = bool(params.get("additional_click_enabled", False))
        additional_mode = str(params.get("additional_mode", "direct") or "direct")
        additional_x_expr = str(params.get("additional_x", "") or "")
        additional_y_expr = str(params.get("additional_y", "") or "")
        coord_file = str(params.get("coord_file", "") or config.map_coord_file)
        match_field = str(params.get("match_field", "target_location") or "target_location")
        match_custom_field = str(params.get("match_custom_field", "") or "")
        additional_button = str(params.get("additional_button", "left") or "left")
        try:
            additional_delay_ms = int(params.get("additional_delay", 200) or 200)
        except (TypeError, ValueError):
            additional_delay_ms = 200

        if action == "click":
            target = self._yolo_pick_target(results, target_class)
            if target is None:
                msg = (f"YOLO 真推理未检测到"
                       f"{'类别=' + target_class if target_class else '目标'}，无法点击")
                logger.warning(msg)
                return False, msg
            center = target.get("center")
            if not center:
                return False, "YOLO 目标缺少 center 坐标"
            self._do_click(
                center, button,
                click_delay_ms / 1000.0 if click_delay_ms > 0 else 0.0
            )
            if additional_click_enabled:
                self._do_additional_click(
                    additional_mode, additional_x_expr, additional_y_expr,
                    coord_file, match_field, match_custom_field,
                    additional_button, additional_delay_ms
                )
            result = (f"YOLO 真推理并点击: 类别={target.get('class')} "
                      f"中心={center} 置信度={float(target.get('confidence', 0)):.3f}")
            logger.info(result)
            return True, result

        if action == "wait":
            from core.screen_capture import screen_capture
            timeout = float(params.get("timeout", 10.0))
            click_on_found = bool(params.get("click_on_found", False))
            deadline = time.time() + timeout
            while time.time() < deadline:
                if self.should_stop:
                    return False, "任务被停止"
                shot = screen_capture.capture()
                cur = yolo.detect(shot) if shot is not None else []
                target = self._yolo_pick_target(cur, target_class)
                if target is not None:
                    center = target.get("center")
                    logger.info(
                        f"YOLO 等待命中目标(类别={target_class or '任意'})"
                    )
                    if click_on_found and center:
                        self._do_click(
                            center, button,
                            click_delay_ms / 1000.0 if click_delay_ms > 0 else 0.0
                        )
                    return True, f"YOLO 等待目标出现(类别={target_class or '任意'})"
                self._interruptible_sleep(0.3)
            return False, (f"YOLO 等待超时未检测到目标"
                           f"(类别={target_class or '任意'}, {timeout}s)")

        # record 或其它：返回检测结果
        best = self._yolo_pick_target(results, target_class)
        return True, {
            "success": True,
            "targets": results,
            "best_target": best,
            "method": "yolo",
        }

    def _execute_yolo_fallback(self, params):
        """
        YOLO 检测降级执行器：使用模板匹配。

        支持单模板（template_path 字符串）和多模板（template_paths 列表）。

        :param params: 事件参数
        :return: (success, result)
        """
        # 解析模板路径列表
        template_paths = params.get("template_paths", [])
        if not template_paths:
            tpl = params.get("template_path", "")
            if isinstance(tpl, list):
                template_paths = [p for p in tpl if p]
            elif tpl:
                template_paths = [tpl]

        if not template_paths:
            msg = "YOLO 检测降级（模板匹配）缺少 template_path"
            logger.warning(msg)
            return False, msg

        try:
            threshold = float(params.get("threshold", 0.8))
        except (TypeError, ValueError):
            threshold = 0.8

        action = str(params.get("action", "click")).lower()
        region = params.get("region", None)
        # region 形如 [x, y, w, h]，转为元组并校验。
        # 关键修复（2026-08-04 user log）：GUI 默认配置 region=[0,0,0,0]，
        # 直接传 capture_region 会触发 "截图区域尺寸非法: w=0, h=0"；
        # 应自动 fallback 到 None（全客户区截图），避免任务硬失败。
        if region is not None:
            try:
                region = tuple(int(v) for v in region)
                if len(region) != 4:
                    region = None
                else:
                    _rx, _ry, _rw, _rh = region
                    if _rw <= 0 or _rh <= 0:
                        region = None
            except (TypeError, ValueError):
                region = None

        # ---- 附加点击参数解析 ----
        additional_click_enabled = bool(params.get("additional_click_enabled", False))
        additional_mode = str(params.get("additional_mode", "direct") or "direct")
        additional_x_expr = str(params.get("additional_x", "") or "")
        additional_y_expr = str(params.get("additional_y", "") or "")
        coord_file = str(params.get("coord_file", "") or config.map_coord_file)
        match_field = str(params.get("match_field", "target_location") or "target_location")
        match_custom_field = str(params.get("match_custom_field", "") or "")
        additional_button = str(params.get("additional_button", "left") or "left")
        try:
            additional_delay_ms = int(params.get("additional_delay", 200) or 200)
        except (TypeError, ValueError):
            additional_delay_ms = 200
        try:
            click_delay_ms = int(params.get("click_delay", 1000) or 1000)
        except (TypeError, ValueError):
            click_delay_ms = 1000

        try:
            if action == "wait":
                # 等待任一模板出现
                timeout = float(params.get("timeout", 10.0))
                wait_pos = None
                if len(template_paths) > 1:
                    logger.info(
                        f"等待任一模板出现(YOLO降级): {len(template_paths)} 个模板 "
                        f"(timeout={timeout}s)"
                    )
                    pos, conf, matched = image_recognition.wait_for_any_template(
                        template_paths, timeout=timeout, threshold=threshold,
                        region=region
                    )
                    if pos is None:
                        return False, f"等待模板出现超时(YOLO降级): {len(template_paths)} 个模板均未找到"
                    wait_pos = pos
                    result = (f"YOLO降级多模板出现: {matched} 位置={pos} 置信度={conf:.3f}")
                else:
                    template_path = template_paths[0]
                    logger.info(
                        f"等待模板出现(YOLO降级): {template_path} (timeout={timeout}s)"
                    )
                    pos, conf = image_recognition.wait_for_template(
                        template_path, timeout=timeout, threshold=threshold,
                        region=region
                    )
                    if pos is None:
                        return False, f"等待模板出现超时(YOLO降级): {template_path}"
                    wait_pos = pos
                    result = (f"YOLO降级模板已出现: {template_path} 位置={pos} 置信度={conf:.3f}")

                # 等待出现成功后：点击模板位置 + 附加点击
                if additional_click_enabled and wait_pos is not None:
                    button = str(params.get("button", "left")).lower()
                    self._do_click(wait_pos, button)
                    if click_delay_ms > 0:
                        time.sleep(click_delay_ms / 1000.0)
                    self._do_additional_click(
                        additional_mode, additional_x_expr, additional_y_expr,
                        coord_file, match_field, match_custom_field,
                        additional_button, additional_delay_ms
                    )
                    result += " (含附加点击)"
                logger.info(result)
                return True, result

            elif action == "wait_disappear":
                # 等待所有模板消失
                timeout = float(params.get("timeout", 10.0))
                if len(template_paths) > 1:
                    logger.info(
                        f"等待所有模板消失(YOLO降级): {len(template_paths)} 个模板 "
                        f"(timeout={timeout}s)"
                    )
                    disappeared = image_recognition.wait_for_any_template_disappear(
                        template_paths, timeout=timeout, threshold=threshold,
                        region=region
                    )
                    if not disappeared:
                        return False, f"等待所有模板消失超时(YOLO降级)"
                    result = f"YOLO降级所有模板已消失: {len(template_paths)} 个"
                else:
                    template_path = template_paths[0]
                    logger.info(
                        f"等待模板消失(YOLO降级): {template_path} (timeout={timeout}s)"
                    )
                    disappeared = image_recognition.wait_for_template_disappear(
                        template_path, timeout=timeout, threshold=threshold,
                        region=region
                    )
                    if not disappeared:
                        return False, f"等待模板消失超时(YOLO降级): {template_path}"
                    result = f"YOLO降级模板已消失: {template_path}"

                # 等待消失成功后执行附加点击
                if additional_click_enabled:
                    self._do_additional_click(
                        additional_mode, additional_x_expr, additional_y_expr,
                        coord_file, match_field, match_custom_field,
                        additional_button, additional_delay_ms
                    )
                    result += " (含附加点击)"
                logger.info(result)
                return True, result

            else:
                # click / record：多模板时找最佳匹配，单模板时直接匹配
                if len(template_paths) > 1:
                    pos, conf, matched = image_recognition.find_best_template(
                        template_paths, threshold=threshold, region=region
                    )
                    if pos is None:
                        msg = f"未匹配到任何模板(YOLO降级): {len(template_paths)} 个模板"
                        logger.warning(msg)
                        return False, msg
                    template_path = matched or "unknown"
                else:
                    template_path = template_paths[0]
                    pos, conf = image_recognition.find_template(
                        template_path, threshold=threshold, region=region
                    )
                    if pos is None:
                        msg = f"未匹配到模板(YOLO降级): {template_path}"
                        logger.warning(msg)
                        return False, msg

                # 根据动作决定后续行为
                if action == "click":
                    button = str(params.get("button", "left")).lower()
                    self._do_click(pos, button)
                    result = (f"YOLO降级模板匹配并点击: {template_path} 位置={pos} "
                              f"置信度={conf:.3f}")
                    logger.info(result)
                    return True, result
                else:  # record
                    result = (f"YOLO降级模板匹配记录: {template_path} 位置={pos} "
                              f"置信度={conf:.3f}")
                    logger.info(result)
                    return True, result
        except Exception as e:
            logger.exception(f"YOLO降级(模板匹配)执行失败: {e}")
            return False, str(e)
