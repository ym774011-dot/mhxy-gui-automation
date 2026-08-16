# -*- coding: utf-8 -*-
"""
click_mixin - TaskEngine 拆分的点击/坐标解析方法组。

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

class ClickMixin:
    """点击、附加点击、坐标文件查找、坐标模板解析。"""

    def _do_click(self, target_coord: tuple, click_type: str = "left", delay: float = 0.0,
                  press_delay: float = 0.05) -> bool:
        """
        统一点击逻辑。

        :param target_coord: 目标坐标元组 (x, y)
        :param click_type: 点击类型 "left"/"right"/"double"/"move"（move=只移动不点击）
        :param delay: 点击后延迟(秒)
        :param press_delay: 按下→弹起保持时间(秒)，后台模式生效，可 GUI 配置
        :return: 是否成功
        """
        try:
            x, y = int(target_coord[0]), int(target_coord[1])

            # 检查窗口是否已绑定（局部 import：测试可 patch core.window_manager.window_manager）
            from core.window_manager import window_manager
            if not window_manager.is_valid():
                logger.warning(f"点击跳过: 窗口未绑定或已失效")
                return False
            # 运行时从主模块取（测试 patch core.task_engine.input_controller 生效；
            # 主模块已完全加载，无循环导入风险）
            from core.task_engine import input_controller

            if click_type == "move":
                # 鼠标移动到：只移动不点击。后台模式 move_to 无实际效果（记录日志）
                input_controller.move_to(x, y)
                logger.info(f"鼠标移动(不点击): ({x},{y})")
            elif click_type == "double":
                input_controller.double_click(x, y)
                logger.info(f"点击执行: ({x},{y}) button={click_type}")
            elif click_type == "right":
                input_controller.click(x, y, button="right", press_delay=press_delay)
                logger.info(f"点击执行: ({x},{y}) button={click_type}")
            else:
                input_controller.click(x, y, button=click_type, press_delay=press_delay)
                logger.info(f"点击执行: ({x},{y}) button={click_type}")

            # 点击后延迟
            if delay > 0:
                time.sleep(delay)

            return True
        except Exception as e:
            logger.error(f"点击失败: {e}")
            return False

    def _do_additional_click(
        self, mode, x_expr, y_expr,
        coord_file, match_field, match_custom_field,
        button="left", delay_ms=200
    ):
        """
        附加点击：在图像识别匹配点击后执行的附加坐标点击。

        支持两种模式：
        - "direct": 直接解析 x_expr/y_expr（支持模板变量）并点击
        - "file_lookup": 从坐标文件中查找匹配字段值对应的坐标并点击

        :param mode: "direct" 或 "file_lookup"
        :param x_expr: 直接模式下的 X 坐标表达式
        :param y_expr: 直接模式下的 Y 坐标表达式
        :param coord_file: 文件查找模式下的坐标文件路径
        :param match_field: 文件查找模式下用于匹配的字段名
        :param match_custom_field: 自定义匹配字段名
        :param button: 按键类型 "left"/"right"/"double"
        :param delay_ms: 点击前延迟(ms)
        """
        if mode == "file_lookup":
            # 使用简化后的 _lookup_coord_from_file 方法
            x_val, y_val = self._lookup_coord_from_file(
                coord_file, None, match_custom_field if match_custom_field else match_field
            )
            if x_val is None or y_val is None:
                logger.warning("附加点击：文件查找模式未能解析到坐标")
                return
        else:
            x_val = self._resolve_click_coord(x_expr)
            y_val = self._resolve_click_coord(y_expr)
            if x_val is None or y_val is None:
                logger.warning(
                    f"附加点击坐标解析失败: x={x_expr}->{x_val}, y={y_expr}->{y_val}"
                )
                return

        # 使用统一的 _do_click 方法
        self._do_click((x_val, y_val), button, delay_ms / 1000.0 if delay_ms > 0 else 0.0)

    def _lookup_coord_from_file(self, coord_file: str, coord_name: str = None, custom_field: str = None) -> tuple:
        """
        从坐标文件中查找坐标。

        支持两种文件格式：
        1. JSON格式：{"地图名": [x, y], ...}
        2. 文本格式：每行 "地图名  X,Y"（空格或Tab分隔）

        :param coord_file: 坐标文件路径
        :param coord_name: 坐标名称（可选，如不提供则从变量上下文查找）
        :param custom_field: 自定义字段名（用于从变量上下文查找）
        :return: (x, y) 或 (None, None)
        """
        import os
        if not coord_file or not os.path.isfile(coord_file):
            logger.warning(f"坐标文件不存在: {coord_file}")
            return None, None

        # 如果没有提供坐标名称，从变量上下文获取
        if coord_name is None:
            field_name = custom_field if custom_field else "target_location"
            coord_name = self._search_var_for_field(field_name)
            if coord_name is None:
                logger.warning(f"坐标文件查找：字段 '{field_name}' 在变量上下文中未找到值")
                return None, None

        lookup_str = str(coord_name).strip()
        logger.info(f"坐标文件查找：在 {coord_file} 中查找 '{lookup_str}'")

        # 尝试读取文件并判断格式
        try:
            with open(coord_file, "r", encoding="utf-8") as f:
                content = f.read().strip()

            # 判断是否为 JSON 格式
            if content.startswith("{") and content.endswith("}"):
                # JSON 格式
                import json
                coords = json.loads(content)
                if lookup_str in coords:
                    coord = coords[lookup_str]
                    if isinstance(coord, (list, tuple)) and len(coord) >= 2:
                        x, y = int(coord[0]), int(coord[1])
                        logger.info(f"坐标文件查找成功(JSON): {lookup_str} -> ({x},{y})")
                        return x, y
                logger.warning(f"坐标文件(JSON)中未找到 '{lookup_str}'")
                return None, None

            # 文本格式（每行 "地图名 X,Y"）
            for line in content.split("\n"):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue

                # 支持多种分隔符：空格、Tab
                parts = line.split()
                if len(parts) < 2:
                    # 尝试逗号分隔（地图名,X,Y 格式）
                    parts = line.split(",")
                    if len(parts) < 2:
                        continue

                # 第一部分是地图名
                map_name = parts[0].strip()

                # 检查是否匹配（支持包含匹配）
                if lookup_str == map_name or lookup_str in map_name:
                    # 尝试解析坐标
                    coord_str = parts[1].strip()
                    # 处理 "X,Y" 或 "X Y" 格式
                    if "," in coord_str:
                        coord_parts = coord_str.split(",")
                    elif len(parts) >= 3:
                        coord_parts = [parts[1], parts[2]]
                    else:
                        continue

                    try:
                        x = int(coord_parts[0].strip())
                        y = int(coord_parts[1].strip())
                        logger.info(f"坐标文件查找成功(文本): {map_name} -> ({x},{y})")
                        return x, y
                    except (ValueError, IndexError):
                        logger.warning(f"坐标解析失败: {coord_str}")
                        continue

            logger.warning(f"坐标文件(文本)中未找到 '{lookup_str}' 对应的条目")
            return None, None

        except Exception as e:
            logger.warning(f"读取坐标文件失败: {e}")
            return None, None

    def _resolve_click_coord(self, expr):
        """
        解析坐标表达式为整数值。

        支持：
        - 纯数字: "100" → 100
        - 模板变量: "${JHRW.target_coord.0}" → 从上下文取值
        - 变量引用: "100+${offset}" → 简单算术（扩展预留）
        """
        if not expr:
            return None

        expr = str(expr).strip()

        # 尝试直接转换为整数
        try:
            return int(expr)
        except (TypeError, ValueError):
            pass

        # 尝试解析模板变量
        # 支持 ${xxx.yyy.zzz} 格式
        value = self._resolve_template_value(expr)
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                logger.warning(f"变量值无法转为整数: {expr} → {value}")
                return None

        logger.warning(f"无法解析坐标表达式: {expr}")
        return None

    def _resolve_template_value(self, expr):
        """
        从模板变量表达式 ${xxx} 中解析实际值。

        :param expr: 可能包含 ${var.path} 的表达式
        :return: 解析后的值，未找到返回 None
        """
        import re
        # 匹配 ${...} 部分
        matches = re.findall(r'\$\{([^}]+)\}', expr)
        if not matches:
            return None

        # 仅处理单个变量的情况
        if len(matches) == 1 and expr.strip() == f"${{{matches[0]}}}":
            var_path = matches[0].strip()
            # 尝试通过 _resolve_value 获取
            value = self._resolve_value(var_path)
            if value is not None:
                return value
            # 尝试在所有变量中搜索
            return self._search_var_for_path(var_path)

        # 多变量或混合表达式暂不支持
        return None
