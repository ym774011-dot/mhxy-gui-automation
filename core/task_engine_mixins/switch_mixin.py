# -*- coding: utf-8 -*-
"""
switch_mixin - TaskEngine 拆分的switch 条件分支方法组。

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

class SwitchMixin:
    """switch 条件分支执行（匹配字段 -> case -> 动作序列）。"""

    def _execute_switch_condition_with_depth(self, params: dict, depth: int = 0):
        """
        switch 分支模式：按字段值匹配 case 并执行对应的动作序列。

        :param params: switch 模式参数
        :param depth: 当前嵌套深度
        :return: (success, result)
        """
        # 1. 获取要匹配的字段值
        match_field = str(params.get("match_field", "target_location") or "target_location")
        match_custom = str(params.get("match_custom_field", "") or "").strip()
        if match_field == "__custom__" and match_custom:
            match_field = match_custom

        # 可选：指定来源变量（如某个函数事件的 var_name）。
        # 明确从该变量的结果中取 match_field，避免多函数事件并存时
        # _search_var_for_field 在多个变量中"碰运气"取到错误的值。
        source_var = str(params.get("source_var", "") or "").strip()

        if source_var:
            ctx = self._var_context.get(source_var)
            if isinstance(ctx, dict) and match_field in ctx:
                match_value = ctx.get(match_field)
            else:
                # 来源变量不存在或没有该字段：回退到通用搜索（保持旧行为）
                match_value = self._search_var_for_field(match_field)
                if match_value is None and isinstance(self._last_result, dict):
                    match_value = self._last_result.get(match_field)
        else:
            match_value = self._search_var_for_field(match_field)
            if match_value is None and isinstance(self._last_result, dict):
                match_value = self._last_result.get(match_field)

        match_str = str(match_value) if match_value is not None else ""
        logger.info(
            f"开关分支：匹配字段='{match_field}', 值='{match_str}'"
        )

        # 2. 遍历 case 查找匹配
        cases = params.get("cases", []) or []
        matched_case = None
        # 候选地图集合（JHRW 返回的 target_location_candidates）用于消歧：
        # 当单值 target_location 因多开/多候选不准时，只要 case 地图在候选集合内即命中
        candidates = []
        if source_var:
            _ctx = self._var_context.get(source_var)
            if isinstance(_ctx, dict):
                candidates = _ctx.get("target_location_candidates") or []
        for case in cases:
            case_match_val = str(case.get("match_value", "") or "")
            if not case_match_val:
                continue
            # 精确匹配 / 子串包含匹配 / 命中候选集合
            via_cand = bool(candidates) and case_match_val in candidates
            if match_str == case_match_val or case_match_val in match_str or via_cand:
                matched_case = case
                logger.info(
                    f"开关分支命中: '{match_str}' -> case '{case_match_val}'"
                    + (" (via candidates)" if via_cand else "")
                )
                break

        # 3. 如果没有命中 case，使用默认动作
        action_def = matched_case
        if action_def is None:
            default_action = params.get("default_action") or {}
            if default_action and default_action.get("action", "none") != "none":
                action_def = default_action
                logger.info(
                    f"开关分支：无 case 命中，使用默认动作"
                )
            else:
                logger.info(
                    f"开关分支：无 case 命中且无默认动作，跳过"
                )
                return True, {
                    "matched": False,
                    "match_field": match_field,
                    "match_value": match_str,
                    "action": None,
                }

        # 4. 执行动作序列（支持 actions 列表）
        return self._execute_switch_actions(action_def, match_field, match_str, depth)

    def _execute_switch_actions(self, action_def: dict, match_field: str, match_str: str, depth: int = 0):
        """
        执行 switch case 对应的动作序列。

        支持两种动作定义方式：
        1. 单个动作：{"action": "click", "x": 100, "y": 200, ...}
        2. 动作序列：{"actions": [{"event_type": "click", "params": {...}}, ...]}

        :param action_def: 动作定义
        :param match_field: 匹配字段名
        :param match_str: 匹配值
        :param depth: 当前嵌套深度
        :return: (success, result)
        """
        # 检查是否有 actions 列表（动作序列）
        actions = action_def.get("actions", [])

        if actions:
            # 执行动作序列
            logger.info(
                f"开关分支执行动作序列：{len(actions)} 个动作"
            )

            executed_results = []
            for action_data in actions:
                if self.should_stop.is_set():
                    break

                # 从动作数据创建事件实例
                try:
                    action_event = Event.from_dict(action_data)
                except Exception as e:
                    logger.warning(f"动作事件反序列化失败: {e}")
                    continue

                # 递归执行事件
                success, action_result = self._execute_event_with_depth(
                    action_event, depth=depth + 1
                )
                executed_results.append({
                    "event": action_event.name,
                    "success": success,
                    "result": action_result,
                })

                # 如果动作失败且策略为 stop，中止整个序列
                if not success and action_event.on_error == "stop":
                    logger.error(
                        f"动作事件 {action_event.name!r} 失败（on_error=stop），"
                        f"中止动作序列"
                    )
                    return False, {
                        "matched": True,
                        "match_field": match_field,
                        "match_value": match_str,
                        "error": f"action_failed: {action_result}",
                    }

            return True, {
                "matched": True,
                "match_field": match_field,
                "match_value": match_str,
                "actions_executed": len(executed_results),
                "results": executed_results,
            }

        else:
            # 单个动作（向后兼容旧格式）
            return self._execute_single_switch_action(action_def, match_field, match_str)

    def _execute_single_switch_action(self, action_def: dict, match_field: str, match_str: str):
        """
        执行单个 switch 动作（向后兼容旧格式）。

        支持的 action 类型：
        - "click": 直接点击指定 (x, y)
        - "file_lookup": 从坐标文件中查找 match_field 对应的坐标并点击
        - "none": 不执行任何动作

        :param action_def: 动作定义
        :param match_field: 匹配字段名
        :param match_str: 匹配值
        :return: (success, result)
        """
        action = str(action_def.get("action", "none")).lower()
        result_info = {
            "matched": True,
            "match_field": match_field,
            "match_value": match_str,
            "action": action,
        }

        if action in ("none", "subflow"):
            # subflow 走到这里说明 actions 列表为空，等同不执行
            logger.info(f"开关分支动作: {action}（不执行）")
            return True, result_info

        if action == "click":
            # 直接点击
            try:
                x = int(action_def.get("x", 0))
                y = int(action_def.get("y", 0))
            except (TypeError, ValueError) as e:
                msg = f"开关分支点击坐标非法: {e}"
                logger.warning(msg)
                return False, msg
            button = str(action_def.get("button", "left")).lower()
            delay_ms = 0
            try:
                delay_ms = int(action_def.get("delay", 0))
            except (TypeError, ValueError):
                pass

            # 使用统一的 _do_click 方法
            self._do_click((x, y), button, delay_ms / 1000.0 if delay_ms > 0 else 0.0)
            logger.info(f"开关分支动作: 点击 ({x},{y}) button={button}")
            result_info["x"] = x
            result_info["y"] = y
            result_info["button"] = button
            return True, result_info

        if action == "file_lookup":
            # 从坐标文件中查找坐标并点击
            coord_file = str(action_def.get("coord_file", "") or "").strip()
            if not coord_file:
                # 使用事件参数里的 coord_file（如果在顶层），否则回退全局默认
                coord_file = str(
                    getattr(self, "_current_condition_coord_file", None)
                    or config.map_coord_file
                    or ""
                )
            lookup_field = str(action_def.get("lookup_field", "") or "").strip()
            if not lookup_field:
                lookup_field = match_field
            lookup_custom = str(action_def.get("lookup_custom_field", "") or "").strip()
            button = str(action_def.get("button", "left")).lower()
            delay_ms = 0
            try:
                delay_ms = int(action_def.get("delay", 0))
            except (TypeError, ValueError):
                pass

            # 使用简化后的 _lookup_coord_from_file 方法
            x, y = self._lookup_coord_from_file(coord_file, lookup_custom if lookup_custom else None)
            if x is None or y is None:
                msg = (
                    f"开关分支文件查找失败: 字段 '{lookup_field}'="
                    f"'{match_str}' 在文件中未找到对应坐标"
                )
                logger.warning(msg)
                return False, msg

            # 使用统一的 _do_click 方法
            self._do_click((x, y), button, delay_ms / 1000.0 if delay_ms > 0 else 0.0)
            logger.info(
                f"开关分支动作: 文件查找点击 ({x},{y}) "
                f"lookup_field='{lookup_field}' button={button}"
            )
            result_info["x"] = x
            result_info["y"] = y
            result_info["button"] = button
            result_info["coord_file"] = coord_file
            return True, result_info

        msg = f"开关分支: 不支持的动作类型 {action!r}"
        logger.warning(msg)
        return False, msg

    # ==================================================================
    # 内部：信号发射辅助
    # ==================================================================
