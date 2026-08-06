# -*- coding: utf-8 -*-
"""
任务执行引擎模块。

提供 ``TaskEngine`` 类（单例模式），负责：
    - 在独立线程中按顺序执行 TaskSequence 中的 Task / Event
    - 支持启动、暂停、恢复、停止控制
    - 根据 Event.event_type 分发到对应执行器（鼠标、键盘、等待、
      图像识别、YOLO 检测、函数调用、条件分支）
    - 按 on_error 策略（retry / skip / stop）处理事件执行异常
    - 通过 PyQt5 信号通知 GUI 线程更新进度、日志、状态、完成情况

使用方式::

    from core.task_engine import task_engine
    from models.task_sequence import TaskSequence

    task_engine.start(task_sequence)   # 启动（异步，在子线程执行）
    task_engine.pause()                # 暂停
    task_engine.resume()               # 恢复
    task_engine.stop()                 # 停止

坐标约定：所有坐标均为客户区坐标，与 input_controller / image_recognition
等模块保持一致。
"""
import os
import time
import re
import json
import random
import threading
from typing import Dict, List, Optional, Any, Tuple, Union

from PyQt5.QtCore import QObject, pyqtSignal

from models.event import Event, EventType
from models.task import Task
from models.task_sequence import TaskSequence
from core.input_controller import input_controller
from core.image_recognition import image_recognition
from core.task_library_manager import task_library
from core.location_data_container import (
    LocationDataContainer,
    get_global_location_container,
    reset_global_location_container,
    clear_global_location_container,
)
from utils.logger import logger
from utils.helpers import delay
from config.config import config

# yolo_detector 采用延迟导入：其依赖 ultralytics / torch 较重，
# 且部分环境下可能因 DLL/驱动问题导致 import 时抛 OSError（而非 ImportError）。
# 为避免影响整个引擎模块的加载，仅在真正执行 YOLO 事件时才导入。
yolo_detector = None


def _summarize_event_params(event) -> str:
    """事件参数的简短摘要字符串（用于日志"开始执行"行）。

    格式：按事件类型展示关键字段，便于卡住时一眼定位在做什么。
    """
    p = event.params or {}
    t = event.event_type
    if t == EventType.CLICK:
        return f"x={p.get('x')}, y={p.get('y')}, button={p.get('button')}, background={p.get('background')}"
    if t == EventType.KEY:
        return f"keys={p.get('keys')!r}, text={p.get('text')!r}"
    if t == EventType.WAIT:
        return f"duration={p.get('duration')}, wait_for_image={p.get('wait_for_image')}, image_path={p.get('image_path')!r}, timeout={p.get('timeout')}"
    if t == EventType.IMAGE:
        return f"action={p.get('action')}, template={p.get('template_path') or p.get('source_image')!r}, threshold={p.get('threshold')}"
    if t == EventType.YOLO:
        return f"action={p.get('action')}, target={p.get('target_class')!r}, confidence={p.get('confidence')}"
    if t == EventType.FUNCTION:
        return f"name={p.get('function_name') or p.get('name')!r}, args={p.get('args')}"
    return json.dumps(p, ensure_ascii=False)[:200] if p else "{}"


def _get_yolo_detector():
    """
    延迟导入并返回 yolo_detector 单例。

    :return: yolo_detector 单例；导入失败返回 None
    """
    global yolo_detector
    if yolo_detector is None:
        try:
            from core.yolo_detector import yolo_detector as _yd
            yolo_detector = _yd
        except Exception as e:
            # 捕获所有异常（含 OSError），避免 DLL 初始化失败导致崩溃
            logger.warning(f"yolo_detector 导入失败，YOLO 事件将不可用: {e}")
            return None
    return yolo_detector


class TaskEngine(QObject):
    """
    任务执行引擎。

    继承自 QObject 以支持 PyQt5 信号。所有状态切换均通过简单标志位实现，
    执行线程在合适的时机轮询这些标志位以响应控制指令。

    信号：
        - progress_signal(int, int, str)：(当前事件下标, 总事件数, 事件名称)
        - log_signal(str, str)：(日志级别, 消息内容)
        - status_signal(str)：状态文本
        - finished_signal(bool, str)：(是否成功, 完成消息)
    """

    # ==================================================================
    # PyQt5 信号定义（GUI 线程订阅这些信号以更新界面）
    # ==================================================================
    # 进度信号：(当前事件下标, 总事件数, 事件名称)
    progress_signal = pyqtSignal(int, int, str)
    # 日志信号：(级别字符串, 消息字符串)
    log_signal = pyqtSignal(str, str)
    # 状态信号：状态文本（如 "运行中"、"已暂停"、"已停止"）
    status_signal = pyqtSignal(str)
    # 完成信号：(是否成功, 完成消息)
    finished_signal = pyqtSignal(bool, str)
    # 任务详情信号：(dict) 函数事件成功返回的游戏任务信息，推送给主面板做 IPC 导出。
    # 字段约定见 StatusPanel.set_quest_detail：map_name / coord / npc / loops / task
    quest_detail_signal = pyqtSignal(dict)

    def __init__(self) -> None:
        super().__init__()
        # 运行状态标志
        self.is_running: bool = False
        self.is_paused: bool = False
        self.should_stop: bool = False
        # 当前执行上下文（供 GUI 查询）
        self.current_task: Optional[Task] = None
        self.current_event: Optional[Event] = None
        self.current_event_index: int = 0
        self.current_loop: int = 0
        # 工作线程
        self._thread: Optional[threading.Thread] = None
        # 上一次事件的执行结果，供 CONDITION 事件做简单条件判断使用
        self._last_result: Optional[Any] = None
        # 变量上下文：用于 ${var} 模板替换
        # 键 -> 值，例如 {"JHRW": {...}, "result": ...}
        self._var_context: Dict[str, Any] = {}
        # 全局位置数据容器：存储地图位置信息
        self._location_container: LocationDataContainer = get_global_location_container()

    # ==================================================================
    # 控制接口
    # ==================================================================
    def start(self, task_sequence: TaskSequence) -> bool:
        """
        启动任务序列执行（在独立线程中运行）。

        :param task_sequence: TaskSequence 实例
        :return: bool，是否成功启动。若引擎已在运行则返回 False。
        """
        # 已在运行则拒绝重复启动
        if self.is_running:
            logger.warning("任务引擎已在运行，无法重复启动")
            return False

        # 校验任务序列合法性
        if task_sequence is None or not isinstance(task_sequence, TaskSequence):
            logger.error("启动失败：task_sequence 非法")
            return False
        if not task_sequence.tasks:
            logger.warning("启动失败：任务序列为空")
            self._emit_log("warning", "任务序列为空，无需执行")
            self.finished_signal.emit(False, "任务序列为空")
            return False

        # 重置状态
        self.is_running = True
        self.is_paused = False
        self.should_stop = False
        self.current_task = None
        self.current_event = None
        self.current_event_index = 0
        self.current_loop = 0
        self._last_result = None
        self._var_context = {}
        # 重置位置数据容器
        self._location_container = reset_global_location_container(
            supported_maps=["江南野外", "建邺城", "东海湾"]
        )

        # 启动工作线程
        self._thread = threading.Thread(
            target=self._run_sequence,
            args=(task_sequence,),
            name="TaskEngine-Worker",
            daemon=True,  # 守护线程，主进程退出时自动结束
        )
        self._thread.start()

        logger.info(f"任务引擎已启动，序列名: {task_sequence.name!r}")
        self._emit_status("运行中")
        self._emit_log("info", f"开始执行任务序列: {task_sequence.name}")
        return True

    def pause(self) -> None:
        """暂停执行（在下一个事件边界生效）。"""
        if self.is_running and not self.is_paused:
            self.is_paused = True
            logger.info("任务引擎已暂停")
            self._emit_status("已暂停")
            self._emit_log("info", "任务已暂停")

    def resume(self) -> None:
        """恢复执行。"""
        if self.is_running and self.is_paused:
            self.is_paused = False
            logger.info("任务引擎已恢复")
            self._emit_status("运行中")
            self._emit_log("info", "任务已恢复")

    def stop(self) -> None:
        """停止执行(在下一个事件边界生效)。

        2026-08-05 10:35 加固：工作线程若卡在不可中断的阻塞调用（如模板匹配
        wait_for_template 旧版本 / 函数库调用），可能长时间不退出导致状态停在
        "正在停止"。stop 在请求停止后等待少量时间，若工作线程仍未结束则强制
        复位运行状态（守护线程不会阻塞主进程，但 is_running 必须复位才能重启）。
        """
        if self.is_running:
            self.should_stop = True
            self.is_paused = False  # 解除暂停,让工作线程能跑出去
            logger.info("任务引擎请求停止")
            self._emit_status("正在停止")
            self._emit_log("info", "任务请求停止")

            # 等待工作线程结束（最多 3 秒），超时强制复位，避免"正在停止"卡死
            try:
                thread = getattr(self, "_thread", None)
                if thread is not None and thread.is_alive():
                    thread.join(timeout=3.0)
                if thread is not None and thread.is_alive():
                    # 线程仍卡住：强制复位运行状态（守护线程继续运行但不再占用
                    # 引擎状态；后续若其 finally 执行会再次 emit 已停止）
                    logger.warning(
                        "任务引擎工作线程 3 秒未退出，强制复位状态（避免卡在"
                        "正在停止）。如旧线程仍在操作，请勿立即重复启动。"
                    )
                    self.is_running = False
                    self.is_paused = False
                    self._emit_status("已停止")
            except Exception as e:
                logger.warning(f"停止等待线程异常: {e}")
                self.is_running = False
                self.is_paused = False
                self._emit_status("已停止")

    def get_location_container(self) -> LocationDataContainer:
        """
        获取全局位置数据容器。

        :return: LocationDataContainer 实例
        """
        return self._location_container

    def get_location(self, location: str) -> Optional[Dict[str, Any]]:
        """
        获取指定地图的位置数据。

        :param str location: 地图名称
        :return: 位置数据字典或 None
        """
        return self._location_container.get_location(location)

    def get_location_coordinates(self, location: str) -> Optional[Tuple[int, int]]:
        """
        获取指定地图的坐标。

        :param str location: 地图名称
        :return: (x, y) 元组或 None
        """
        return self._location_container.get_coordinates(location)

    def get_all_locations(self) -> Dict[str, Dict[str, Any]]:
        """
        获取所有位置数据。

        :return: 所有位置数据的副本
        """
        return self._location_container.get_all_locations()

    # ==================================================================
    # 内部：工作线程主循环
    # ==================================================================
    def _run_sequence(self, task_sequence: TaskSequence) -> None:
        """
        工作线程主入口，遍历任务序列中的每个任务并按 loop_count 循环执行。

        支持两级循环：
            - 序列级循环：``task_sequence.loop_count`` 控制整个序列重复执行
              的次数，0 表示无限循环（依赖 should_stop 退出），默认 1（执行
              一遍不循环）；``task_sequence.loop_delay`` 控制每轮之间的间隔。
            - 任务级循环：每个 Task 自身的 ``loop_count`` / ``loop_delay``
              在 ``_run_task`` 中处理。

        :param task_sequence: TaskSequence 实例
        """
        success = True
        message = "任务序列执行完成"

        # 序列级循环：0=无限循环，依赖 should_stop 退出；默认 1（执行一遍不循环）
        seq_loop_count = (task_sequence.loop_count
                          if task_sequence.loop_count > 0
                          else float("inf"))
        seq_loop_index = 0

        try:
            total_tasks = len(task_sequence.tasks)
            while seq_loop_index < seq_loop_count:
                # 暂停等待：在暂停期间循环 sleep，直到恢复或停止
                while self.is_paused and not self.should_stop:
                    time.sleep(0.1)
                # 停止信号检查
                if self.should_stop:
                    message = "任务序列已被停止"
                    success = False
                    break

                # 每轮序列循环开始时重置位置数据容器，保证每轮都是干净状态
                self._location_container = reset_global_location_container(
                    supported_maps=["江南野外", "建邺城", "东海湾"]
                )

                # 输出序列循环进度
                if seq_loop_count == float("inf"):
                    loop_desc = f"第 {seq_loop_index + 1} 轮（无限循环）"
                else:
                    loop_desc = (
                        f"第 {seq_loop_index + 1}/{int(seq_loop_count)} 轮"
                    )
                logger.info(
                    f"序列 {task_sequence.name!r} {loop_desc} 开始，"
                    f"共 {total_tasks} 个任务"
                )
                self._emit_log(
                    "info",
                    f"序列循环 {loop_desc}，共 {total_tasks} 个任务"
                )

                # 逐个任务执行
                for task_idx, task in enumerate(task_sequence.tasks):
                    # 暂停等待
                    while self.is_paused and not self.should_stop:
                        time.sleep(0.1)
                    # 停止信号检查
                    if self.should_stop:
                        message = "任务序列已被停止"
                        success = False
                        break

                    self.current_task = task
                    logger.info(
                        f"开始执行任务 [{task_idx + 1}/{total_tasks}]: "
                        f"{task.name!r}"
                    )
                    self._emit_log(
                        "info",
                        f"开始任务 [{task_idx + 1}/{total_tasks}]: {task.name}"
                    )

                    # 执行单个任务（含任务级循环）
                    task_ok, task_msg = self._run_task(task)
                    if not task_ok:
                        # 任务被停止或出现 stop 策略错误
                        success = False
                        message = task_msg or "任务被中止"
                        break

                # 内层 for 因停止/失败而 break 时，跳出 while 进入 finally
                if not success:
                    break

                # 本轮序列循环完成
                seq_loop_index += 1
                # 若还需要下一轮，按 loop_delay 间隔等待
                if seq_loop_index < seq_loop_count:
                    if task_sequence.loop_delay and task_sequence.loop_delay > 0:
                        self._emit_log(
                            "info",
                            f"序列循环等待 {task_sequence.loop_delay} 秒后"
                            f"开始下一轮"
                        )
                        # 分段 sleep，便于及时响应停止/暂停
                        self._interruptible_sleep(task_sequence.loop_delay)

            if success:
                logger.info(f"任务序列执行完成: {task_sequence.name!r}")
        except Exception as e:
            # 兜底异常保护，防止工作线程静默崩溃
            logger.exception(f"任务序列执行异常: {e}")
            success = False
            message = f"任务序列执行异常: {e}"
        finally:
            # 清理状态
            self.is_running = False
            self.is_paused = False
            self.current_task = None
            self.current_event = None
            # 清理位置数据容器
            clear_global_location_container()
            self._location_container = get_global_location_container()
            self._emit_status("已停止" if not success else "已完成")
            self._emit_log("info" if success else "error", message)
            self.finished_signal.emit(success, message)

    def _run_task(self, task: Task) -> Tuple[bool, str]:
        """
        执行单个任务（按 loop_count 循环）。

        :param task: Task 实例
        :return: (success: bool, message: str)
        """
        # loop_count = 0 表示无限循环，依赖 should_stop 退出
        loop_count = task.loop_count if task.loop_count > 0 else float("inf")
        loop_index = 0

        while loop_index < loop_count:
            # 暂停等待：在暂停期间循环 sleep，直到恢复或停止
            while self.is_paused and not self.should_stop:
                time.sleep(0.1)
            # 停止信号检查
            if self.should_stop:
                return False, "任务被停止"

            self.current_loop = loop_index + 1
            total_events = len(task.events)
            logger.info(
                f"任务 {task.name!r} 第 {loop_index + 1} 轮循环开始，"
                f"共 {total_events} 个事件"
            )
            self._emit_log(
                "info",
                f"任务 {task.name} 第 {loop_index + 1} 轮，共 {total_events} 个事件"
            )

            # 逐个事件执行
            for event_idx, event in enumerate(task.events):
                # 暂停等待
                while self.is_paused and not self.should_stop:
                    time.sleep(0.1)
                # 停止信号检查
                if self.should_stop:
                    return False, "任务被停止"

                self.current_event = event
                self.current_event_index = event_idx

                # 发射进度信号
                event_name = event.name or event.event_type
                self.progress_signal.emit(event_idx, total_events, event_name)

                # 执行事件
                success, result = self._execute_event(event)
                self._last_result = result

                if not success:
                    # 事件最终执行失败
                    # - on_error=stop：立即停止整个序列
                    # - on_error=retry：重试耗尽后停止整个序列
                    #   （用户选 retry 而非 skip，说明事件重要，重试还失败应停止）
                    # - on_error=skip：_dispatch_with_retry 内部已转成
                    #   (True, "skipped: ...")，不会进入此分支
                    if event.on_error in ("stop", "retry"):
                        msg = (f"事件 {event.name!r} 失败 "
                               f"(on_error={event.on_error})，"
                               f"停止整个序列: {result}")
                        logger.error(msg)
                        self._emit_log("error", msg)
                        return False, msg
                    # 其他情况（理论上不会到这里）继续下一个事件
                # 成功或 skip 均继续下一个事件

            # 本轮循环完成
            loop_index += 1
            # 若还需要下一轮，按 loop_delay 间隔等待
            if loop_index < loop_count:
                if task.loop_delay and task.loop_delay > 0:
                    # 分段 sleep，便于及时响应停止
                    self._interruptible_sleep(task.loop_delay)

        return True, "任务执行完成"

    def _interruptible_sleep(self, seconds: float) -> None:
        """
        可中断的 sleep：以 0.1 秒为粒度轮询 should_stop / is_paused。

        :param seconds: 总睡眠秒数
        """
        elapsed = 0.0
        step = 0.1
        while elapsed < seconds:
            if self.should_stop:
                return
            # 暂停期间也暂停 loop_delay 计时
            if self.is_paused:
                time.sleep(0.1)
                continue
            time.sleep(min(step, seconds - elapsed))
            elapsed += step

    # ==================================================================
    # 模板变量解析 ${var.path}
    # ==================================================================

    # 匹配 ${var} 或 ${var.key} 或 ${var.key.sub} 等
    _TEMPLATE_RE = re.compile(r"\$\{([^}]+)\}")

    def _resolve_value(self, expr: str) -> Optional[Any]:
        """
        根据变量表达式从上下文取值。

        支持的语法：
            ${last_result}                 -> 上一步完整结果
            ${result}                      -> 同上（别名）
            ${result.key}                  -> 上一步结果的 key 字段
            ${result.key.sub}              -> 嵌套访问
            ${result.target_coord.0}       -> 元组/列表索引
            ${变量名.key}                   -> 从 _var_context 中取
            ${location.地图名}             -> 从位置数据容器取完整数据
            ${location.地图名.x}           -> 获取位置的 X 坐标
            ${location.地图名.y}           -> 获取位置的 Y 坐标
            ${location.地图名.location}    -> 获取地图名称

        :param expr: 变量表达式字符串（不含 ${}）
        :return: 解析后的值（可能是任意类型）
        """
        parts = expr.strip().split(".")
        if not parts:
            return None

        # 确定根对象
        root_key = parts[0]

        # === 位置数据容器支持 ===
        if root_key == "location":
            if len(parts) < 2:
                logger.warning(f"模板变量 '${expr}' 缺少地图名")
                return None
            map_name = parts[1]
            location_data = self._location_container.get_location(map_name)
            if location_data is None:
                logger.warning(
                    f"模板变量 '${expr}' 未找到位置数据: {map_name}"
                )
                return None
            # 如果只有 location.地图名，返回完整数据
            if len(parts) == 2:
                return location_data
            # 继续访问子字段
            obj = location_data
            for part in parts[2:]:
                if obj is None:
                    return None
                if isinstance(obj, dict):
                    if part not in obj:
                        logger.warning(
                            f"模板变量 '${expr}' 中键 '{part}' 不存在"
                        )
                        return None
                    obj = obj[part]
                elif isinstance(obj, (list, tuple)):
                    try:
                        idx = int(part)
                        obj = obj[idx]
                    except (ValueError, IndexError):
                        return None
                else:
                    return None
            return obj

        if root_key in ("last_result", "result"):
            obj = self._last_result
        elif root_key in self._var_context:
            obj = self._var_context[root_key]
        else:
            # 尝试从位置数据容器中查找
            if self._location_container.has_location(root_key):
                obj = self._location_container.get_location(root_key)
            else:
                logger.warning(f"模板变量 '${expr}' 未找到根对象: {root_key}")
                return None

        # 逐级访问
        for part in parts[1:]:
            if obj is None:
                return None
            if isinstance(obj, dict):
                if part not in obj:
                    logger.warning(
                        f"模板变量 '${expr}' 中键 '{part}' 不存在"
                    )
                    return None
                obj = obj[part]
            elif isinstance(obj, (list, tuple)):
                try:
                    idx = int(part)
                    obj = obj[idx]
                except (ValueError, IndexError):
                    logger.warning(
                        f"模板变量 '${expr}' 中索引 '{part}' 无法访问"
                    )
                    return None
            elif hasattr(obj, part):
                obj = getattr(obj, part)
            else:
                logger.warning(
                    f"模板变量 '${expr}' 无法访问属性 '{part}'"
                )
                return None
        return obj

    def _resolve_template_params(self, params: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """
        解析参数中的 ${var} 模板变量，替换为实际值。

        支持的参数值类型：
            - 字符串：内部有 ${var} 则替换；整个字符串就是 ${var} 则返回原始类型
            - 整数/浮点数/布尔/None：原样返回
            - 列表/元组：递归处理每个元素
            - 字典：递归处理每个 value

        :param params: 原始参数字典
        :return: 替换后的参数字典（新对象，不修改原字典）
        """
        if not params or not isinstance(params, dict):
            return params

        def _resolve_value_string(s):
            """解析字符串中的模板变量。"""
            if not isinstance(s, str):
                return s

            # 检查整个字符串是否就是单个变量 ${...}
            m_full = self._TEMPLATE_RE.fullmatch(s.strip())
            if m_full:
                val = self._resolve_value(m_full.group(1))
                # 变量不存在时保留原占位符
                if val is None:
                    return s
                return val

            # 否则替换字符串中所有 ${...}，将结果转为字符串
            def _replace(m):
                val = self._resolve_value(m.group(1))
                if val is None:
                    return m.group(0)  # 保留原占位符
                return str(val)

            return self._TEMPLATE_RE.sub(_replace, s)

        def _resolve_any(obj):
            if isinstance(obj, dict):
                return {k: _resolve_any(v) for k, v in obj.items()}
            elif isinstance(obj, (list, tuple)):
                return type(obj)(_resolve_any(v) for v in obj)
            elif isinstance(obj, str):
                return _resolve_value_string(obj)
            else:
                return obj

        return _resolve_any(params)

    def _resolve_single_value(self, value: Any) -> Any:
        """
        解析单个字符串值中的 ${var} 模板变量。
        如果整个字符串就是 ${...}，返回原始类型值；否则做字符串替换。
        """
        if not isinstance(value, str):
            return value
        return self._resolve_template_params(value)

    def _save_to_context(self, event: Event, result: Any) -> None:
        """
        将事件执行结果存入变量上下文，供后续事件模板引用。

        使用事件的 var_name 作为 key（若无则自动从事件名生成）。

        :param event: Event 实例
        :param result: 执行结果
        """
        # 使用 var_name 或从事件名生成
        var_name = event.var_name
        if not var_name:
            var_name = event.name.replace(" ", "").replace("_", "")

        # 存入变量上下文
        self._var_context[var_name] = result

        # 同时以事件名（清理版）作为别名
        clean_name = event.name.replace(" ", "").replace("_", "")
        if clean_name and clean_name != var_name:
            self._var_context[clean_name] = result

        # 如果结果是 dict，存入 last_result
        if isinstance(result, dict):
            self._last_result = result
        else:
            self._last_result = result

    def _maybe_emit_quest_detail(self, result: Any) -> None:
        """
        从函数调用结果中抽取游戏任务详情，通过 ``quest_detail_signal`` 推送给主面板，
        由 StatusPanel 落盘到 ``data/current_quest.json``，供外部进程稳定读取
        （彻底替代「内存逆向 / 反 CE」方案）。

        兼容多套命名约定（JHRW 与地图函数包返回结构略有差异）：

            - 地图名 map   : target_location / map / map_name / location
            - 坐标 coord   : target_coord / coord / coordinate
            - NPC   npc    : target_npc / npc / npc_name
            - 循环次数 loops: progress_num / loops / loop_count / times
            - 任务名 task  : quest_name / task / task_name

        只抽取存在且非空的字段；坐标会被规整为 ``(int, int)`` 元组。
        若结果不是 dict 或无可提取字段，静默跳过。

        :param result: 函数调用返回结果
        """
        if not isinstance(result, dict):
            return

        detail: Dict[str, Any] = {}

        map_name = (
            result.get("target_location")
            or result.get("map")
            or result.get("map_name")
            or result.get("location")
        )
        coord = (
            result.get("target_coord")
            or result.get("coord")
            or result.get("coordinate")
        )
        npc = (
            result.get("target_npc")
            or result.get("npc")
            or result.get("npc_name")
        )
        loops = (
            result.get("progress_num")
            or result.get("loops")
            or result.get("loop_count")
            or result.get("times")
        )
        task = (
            result.get("quest_name")
            or result.get("task")
            or result.get("task_name")
        )

        if map_name:
            detail["map_name"] = str(map_name)
        if coord:
            try:
                detail["coord"] = (int(coord[0]), int(coord[1]))
            except (TypeError, ValueError, IndexError):
                pass
        if npc:
            detail["npc"] = str(npc)
        if loops is not None:
            try:
                detail["loops"] = int(loops)
            except (TypeError, ValueError):
                pass
        if task:
            detail["task"] = str(task)

        if detail:
            self.quest_detail_signal.emit(detail)

    # ==================================================================
    # 内部：事件分发与执行
    # ==================================================================
    def _execute_event(self, event: Event) -> Tuple[bool, Any]:
        """
        执行单个事件：检查启用状态、pre_delay、分发到执行器、post_delay、
        异常处理。自动解析 ${var} 模板变量。

        :param event: Event 实例
        :return: (success: bool, result: any)
        """
        # 未启用则跳过
        if not event.enabled:
            logger.debug(f"事件未启用，跳过: {event.name!r}")
            return True, "skipped"

        # 执行前延迟
        if event.pre_delay and event.pre_delay > 0:
            logger.debug(f"事件 {event.name!r} pre_delay={event.pre_delay}s")
            self._interruptible_sleep(event.pre_delay)
            if self.should_stop:
                return False, "任务被停止"

        # 分发执行（带重试逻辑）
        success, result = self._dispatch_with_retry(event)

        # 保存结果到变量上下文（供后续事件模板引用）
        if success:
            self._save_to_context(event, result)
            # 注：函数调用事件的任务详情推送已在 _execute_function_call 内
            #     完成（验证前 emit，避免被验证失败/重试耗尽门控），此处不重复。

        # 执行后延迟（即使失败也执行 post_delay，保证节奏一致）
        if event.post_delay and event.post_delay > 0 and not self.should_stop:
            logger.debug(f"事件 {event.name!r} post_delay={event.post_delay}s")
            self._interruptible_sleep(event.post_delay)

        return success, result

    def _dispatch_with_retry(self, event: Event) -> Tuple[bool, Any]:
        """
        根据 on_error 策略分发执行事件，必要时重试。
        执行成功则返回结果。

        :param event: Event 实例
        :return: (success: bool, result: any)
        """
        max_attempts = 1
        if event.on_error == "retry":
            # retry 策略：初始 1 次 + max_retries 次重试
            max_attempts = 1 + max(0, event.max_retries)

        last_success = False
        last_result = None
        last_error = None

        for attempt in range(1, max_attempts + 1):
            # 停止信号检查
            if self.should_stop:
                return False, "任务被停止"

            # 2026-08-05 增强：事件执行前打印"开始执行"+参数摘要，
            # 卡住时日志能直接看到最后一个"开始执行"的事件是哪一条
            # （没有"完成"日志对应 = 卡在那里没返回），便于定位死等/死循环。
            if attempt == 1:
                params_summary = _summarize_event_params(event)
                logger.info(
                    f"开始执行事件 {event.name!r} [{event.event_type}] "
                    f"params={params_summary}"
                )

            try:
                success, result = self._dispatch(event)
                if success:
                    if attempt > 1:
                        logger.info(
                            f"事件 {event.name!r} 在第 {attempt} 次尝试成功"
                        )
                    return True, result
                # 执行返回失败
                last_success = False
                last_result = result
                last_error = str(result) if result is not None else "执行失败"
            except Exception as e:
                # 执行器抛出异常
                last_success = False
                last_result = None
                last_error = str(e)
                logger.exception(
                    f"事件 {event.name!r} 第 {attempt} 次执行异常: {e}"
                )

            # 判断是否还能重试
            if attempt < max_attempts:
                logger.warning(
                    f"事件 {event.name!r} 第 {attempt} 次失败，"
                    f"准备重试（共 {max_attempts} 次）: {last_error}"
                )
                self._emit_log(
                    "warning",
                    f"事件 {event.name} 第 {attempt}/{max_attempts} 次失败，"
                    f"将重试: {last_error}"
                )
                # 使用 retry_interval 作为重试间隔
                retry_interval = event.retry_interval if hasattr(event, 'retry_interval') else 1.0
                time.sleep(retry_interval)
            else:
                # 重试耗尽
                if event.on_error == "retry":
                    msg = (f"事件 {event.name!r} 重试 {max_attempts} 次后仍失败: "
                           f"{last_error}")
                    logger.error(msg)
                    self._emit_log("error", msg)
                    # retry 耗尽后返回失败，由 _run_task 决定停止序列
                    return False, last_error or "重试耗尽"

        # on_error=skip：记录警告后返回失败但允许继续
        if event.on_error == "skip":
            msg = (f"事件 {event.name!r} 执行失败，on_error=skip，跳过: "
                   f"{last_error}")
            logger.warning(msg)
            self._emit_log("warning", msg)
            # 返回 True 表示流程可以继续；result 为错误信息
            return True, f"skipped: {last_error}"

        # on_error=stop：返回 False，由上层中止序列
        return False, last_error or "执行失败"

    def _dispatch(self, event: Event) -> Tuple[bool, Any]:
        """
        根据 event.event_type 分发到对应的执行器。
        自动解析参数中的 ${var} 模板变量。

        :param event: Event 实例
        :return: (success: bool, result: any)
        """
        et = event.event_type
        raw_params = event.params or {}
        # 解析模板变量
        params = self._resolve_template_params(raw_params)

        # 如果原始参数中有模板变量，记录调试日志
        if self._TEMPLATE_RE.search(str(raw_params)):
            logger.debug(
                f"事件 {event.name!r} 模板变量替换: "
                f"{raw_params} -> {params}"
            )

        if et == EventType.CLICK:
            return self._execute_mouse_click(params)
        elif et == EventType.KEY:
            return self._execute_key_input(params)
        elif et == EventType.WAIT:
            return self._execute_wait(params)
        elif et == EventType.IMAGE:
            return self._execute_image_match(params)
        elif et == EventType.YOLO:
            return self._execute_yolo_detect(params)
        elif et == EventType.FUNCTION:
            return self._execute_function_call(params)
        elif et == EventType.CONDITION:
            return self._execute_condition(event)
        else:
            msg = f"未知事件类型: {et!r}"
            logger.error(msg)
            return False, msg

    # ==================================================================
    # 各事件类型执行器
    # ==================================================================
    def _execute_mouse_click(self, params: Dict[str, Any]) -> Tuple[bool, str]:
        """
        鼠标点击事件执行器。

        params 结构：
            {"x": int, "y": int,
             "button": "left"/"right"/"double", "background": bool}

        :param params: 事件参数
        :return: (success, result)
        """
        try:
            # 2026-08-05 修复：x/y 可能是 ${var.path} 模板字符串，先做变量替换
            # 再转 int（之前 int("${...}") 直接 ValueError 抛异常，事件被 on_error 吞掉）
            x_raw = params.get("x", 0)
            y_raw = params.get("y", 0)
            x_val = self._resolve_value(str(x_raw)) if isinstance(x_raw, str) and "${" in str(x_raw) else x_raw
            y_val = self._resolve_value(str(y_raw)) if isinstance(y_raw, str) and "${" in str(y_raw) else y_raw
            x = int(x_val) if not isinstance(x_val, (list, tuple)) else int(x_val[0])
            y = int(y_val) if not isinstance(y_val, (list, tuple)) else int(y_val[0])
            button = str(params.get("button", "left")).lower()
            # 点击后等待：默认 0，由用户在事件自身的 post_delay 控制。
            # 之前默认 1.0 干扰了用户已有的 pre/post delay 配置（已撤回）。
            click_delay = float(params.get("click_delay", 0.0))
            # 按下→弹起保持时间（秒）：GUI 事件编辑器"按下延迟"配置，默认 50ms。
            # 偶发点击失效（角色没动）时可调大到 100~300ms。
            press_delay = float(params.get("press_delay", 0.05))
        except (TypeError, ValueError) as e:
            return False, f"鼠标点击参数非法: {e}"

        # 使用统一的 _do_click 方法
        success = self._do_click((x, y), button, click_delay, press_delay)
        if success:
            result = f"点击 ({x},{y}) button={button}"
            return True, result
        else:
            return False, f"点击执行失败"

    def _execute_key_input(self, params: Dict[str, Any]) -> Tuple[bool, str]:
        """
        键盘输入事件执行器。

        params 结构：
            {"keys": "alt+q", "text": "", "duration": float}

        当 text 非空时输入文本，否则按组合键。

        :param params: 事件参数
        :return: (success, result)
        """
        keys = params.get("keys", "")
        text = params.get("text", "")

        try:
            if text:
                # 优先输入文本
                input_controller.type_text(str(text))
                result = f"输入文本: {text!r}"
                logger.info(result)
                return True, result
            elif keys:
                input_controller.press_key(str(keys))
                result = f"按键: {keys!r}"
                logger.info(result)
                return True, result
            else:
                msg = "键盘输入事件缺少 keys 与 text 参数"
                logger.warning(msg)
                return False, msg
        except Exception as e:
            logger.exception(f"键盘输入执行失败: {e}")
            return False, str(e)

    def _execute_wait(self, params: Dict[str, Any]) -> Tuple[bool, str]:
        """
        等待事件执行器。

        params 结构：
            {"duration": float, "wait_for_image": bool,
             "image_path": "", "timeout": float}

        当 wait_for_image=True 时等待指定模板出现，否则按 duration 延时。

        :param params: 事件参数
        :return: (success, result)
        """
        try:
            duration = float(params.get("duration", 0.0))
        except (TypeError, ValueError) as e:
            return False, f"等待 duration 参数非法: {e}"

        wait_for_image = bool(params.get("wait_for_image", False))

        try:
            if wait_for_image:
                image_path = params.get("image_path", "")
                timeout = float(params.get("timeout", 10.0))
                if not image_path:
                    msg = "wait_for_image=True 但未提供 image_path"
                    logger.warning(msg)
                    return False, msg
                # 解析搜索区域（客户区坐标，宽高为0表示全屏）
                region = params.get("region")
                if region and len(region) == 4:
                    try:
                        rx, ry, rw, rh = [int(v) for v in region]
                        if rw > 0 and rh > 0:
                            region_tuple = (rx, ry, rw, rh)
                        else:
                            region_tuple = None
                    except (TypeError, ValueError):
                        region_tuple = None
                else:
                    region_tuple = None

                region_info = (
                    f"区域={region_tuple}" if region_tuple else "全屏"
                )
                logger.info(
                    f"等待图像出现: {image_path} (timeout={timeout}s, {region_info})"
                )
                pos, conf = image_recognition.wait_for_template(
                    image_path, timeout=timeout, region=region_tuple
                )
                if pos is not None:
                    result = (f"图像出现: {image_path} 位置={pos} "
                              f"置信度={conf:.3f}")
                    logger.info(result)
                    return True, result
                else:
                    msg = f"等待图像超时未出现: {image_path}"
                    logger.warning(msg)
                    return False, msg
            else:
                # 普通延时
                if duration > 0:
                    logger.info(f"等待 {duration}s")
                    self._interruptible_sleep(duration)
                result = f"已等待 {duration}s"
                return True, result
        except Exception as e:
            logger.exception(f"等待事件执行失败: {e}")
            return False, str(e)

    def _execute_image_match(self, params: Dict[str, Any]) -> Tuple[bool, str]:
        """
        图像识别事件执行器。

        params 结构（增强版）：
                {
                    // 基础
                    "source_mode": "direct"/"dynamic"/"batch",
                    "template_path": "",
                    "threshold": 0.8,
                    "action": "click"/"wait"/"record",
                    "button": "left"/"right"/"double",
                    "region": [x,y,w,h],
                    // 动态构建
                    "prefix": "", "dir_path": "", "suffix": "",
                    "dyn_field": "target_location",
                    "dyn_custom_field": "",
                    // 批量识别
                    "batch_dir": "", "batch_ext": ".bmp",
                    "batch_use_var": false,
                    "batch_var_field": "target_location",
                    "batch_sort": "name"/"random"/"score",
                    "batch_click_mode": "all"/"first"/"each_wait",
                    // 附加点击（图像识别点击后执行）
                    "additional_click_enabled": false,
                    "additional_x": "",   // 支持 ${var} 模板变量
                    "additional_y": "",   // 支持 ${var} 模板变量
                    "additional_button": "left",
                    "additional_delay": 200,
                }

        :param params: 事件参数
        :return: (success, result)
        """
        try:
            threshold = float(params.get("threshold", 0.8))
        except (TypeError, ValueError):
            threshold = 0.8

        action = str(params.get("action", "record")).lower()
        button = str(params.get("button", "left")).lower()
        region = params.get("region", None)
        if region is not None:
            try:
                region = tuple(int(v) for v in region)
                if len(region) != 4:
                    region = None
            except (TypeError, ValueError):
                region = None

        source_mode = str(params.get("source_mode", "direct")).lower()

        # ---- 点击延迟（每次点击后等待，避免点击太快游戏反应不过来） ----
        try:
            click_delay_ms = int(params.get("click_delay", 1000))
        except (TypeError, ValueError):
            click_delay_ms = 1000

        # ---- 附加点击参数 ----
        additional_click_enabled = bool(params.get("additional_click_enabled", False))
        additional_mode = str(params.get("additional_mode", "direct")).lower()
        additional_x_expr = str(params.get("additional_x", "") or "").strip()
        additional_y_expr = str(params.get("additional_y", "") or "").strip()
        coord_file = str(params.get("coord_file", "") or config.map_coord_file).strip()
        match_field = str(params.get("match_field", "target_location") or "target_location")
        match_custom_field = str(params.get("match_custom_field", "") or "").strip()
        additional_button = str(params.get("additional_button", "left")).lower()
        try:
            additional_delay_ms = int(params.get("additional_delay", 200))
        except (TypeError, ValueError):
            additional_delay_ms = 200

        # ---- 根据 source_mode 获取模板路径列表 ----
        template_paths = self._resolve_image_template_paths(params, source_mode)
        if not template_paths:
            # 空模板路径：可能是地图白名单过滤或文件不存在
            # 配置了 allowed_maps 时，空模板表示地图不在白名单中，应跳过而非失败
            if params.get("allowed_maps", None):
                # 获取当前识别值用于日志
                dyn_field = str(params.get("dyn_field", "target_location") or "target_location")
                current_value = self._search_var_for_field(dyn_field)
                value_desc = f"'{current_value}'" if current_value is not None else "未知"
                msg = f"地图 {value_desc} 不在有效地图列表中，跳过识别"
                logger.info(msg)
                return True, msg  # 跳过视为成功，不触发重试
            else:
                msg = "图像识别事件：未解析到任何模板路径"
                logger.warning(msg)
                return False, msg

        logger.info(
            f"图像识别: source_mode={source_mode}, "
            f"共 {len(template_paths)} 个模板待匹配"
        )

        # ---- 识别重试配置 ----
        recognize_retries = int(params.get("recognize_retries", 2))
        recognize_retry_interval = float(params.get("recognize_retry_interval", 0.5))

        # ---- 逐个模板匹配并点击 ----
        matched_results = []
        for tpl_path in template_paths:
            if self.should_stop:
                break

            pos, conf = None, 0.0

            # ---- 识别重试循环 ----
            for attempt in range(1 + recognize_retries):
                if self.should_stop:
                    break

                try:
                    if action == "wait":
                        timeout = float(params.get("timeout", 10.0))
                        pos, conf = image_recognition.wait_for_template(
                            tpl_path, timeout=timeout, threshold=threshold,
                            region=region, should_stop_cb=lambda: self.should_stop
                        )
                    elif action == "wait_disappear":
                        # 等待模板从画面消失（与“等待出现”对偶）
                        timeout = float(params.get("timeout", 10.0))
                        disappeared = image_recognition.wait_for_template_disappear(
                            tpl_path, timeout=timeout, threshold=threshold,
                            region=region, should_stop_cb=lambda: self.should_stop
                        )
                        if disappeared:
                            matched_results.append({
                                "path": tpl_path,
                                "pos": None,
                                "conf": 0.0,
                                "disappeared": True,
                            })
                            logger.info(f"模板已消失: {tpl_path}")
                        else:
                            logger.warning(
                                f"等待模板消失超时: {tpl_path} ({timeout}s)"
                            )
                        # 等待消失为一次性阻塞等待，无需重试，跳出重试循环
                        break
                    else:
                        pos, conf = image_recognition.find_template(
                            tpl_path, threshold=threshold, region=region
                        )
                except Exception as e:
                    logger.warning(f"模板 {tpl_path} 第 {attempt+1} 次匹配异常: {e}")
                    if attempt < recognize_retries:
                        time.sleep(recognize_retry_interval)
                    continue

                if pos is not None:
                    break  # 匹配成功，跳出重试循环
                elif attempt < recognize_retries:
                    logger.debug(
                        f"模板未匹配: {tpl_path} (第 {attempt+1} 次)，"
                        f"{recognize_retry_interval}s 后重试..."
                    )
                    time.sleep(recognize_retry_interval)

            if pos is None:
                logger.debug(f"模板未匹配: {tpl_path} (共尝试 {1 + recognize_retries} 次)")
                continue

            # 匹配成功
            matched_results.append({
                "path": tpl_path,
                "pos": pos,
                "conf": conf,
            })
            logger.info(
                f"模板匹配成功: {tpl_path} 位置={pos} 置信度={conf:.3f}"
            )

            # 根据批量点击模式决定是否在循环内点击
            batch_click_mode = str(params.get("batch_click_mode", "all")).lower()
            # 注意：first 模式不能在这里 break，否则 _do_click 根本不会被调用！
            #   正确的做法：first / each_wait 在循环内执行点击，all 模式到汇总循环执行
            if action == "click":
                if batch_click_mode == "each_wait":
                    # each_wait: 点完一个 + 主点击后延迟(等游戏反应) + 附加 + 附加后延迟
                    self._do_click(pos, button)
                    if click_delay_ms > 0:
                        time.sleep(click_delay_ms / 1000.0)
                    if additional_click_enabled:
                        self._do_additional_click(
                            additional_mode,
                            additional_x_expr, additional_y_expr,
                            coord_file, match_field, match_custom_field,
                            additional_button, additional_delay_ms
                        )
                    continue
                elif batch_click_mode == "first":
                    # first: 立即点击（+主点击后延迟 +附加+附加后延迟）然后 break
                    self._do_click(pos, button)
                    if click_delay_ms > 0:
                        time.sleep(click_delay_ms / 1000.0)
                    if additional_click_enabled:
                        self._do_additional_click(
                            additional_mode,
                            additional_x_expr, additional_y_expr,
                            coord_file, match_field, match_custom_field,
                            additional_button, additional_delay_ms
                        )
                    break  # 只点第一个：在点击之后才 break

        # 如果没有匹配结果
        if not matched_results:
            msg = f"未匹配到任何模板（共尝试 {len(template_paths)} 个模板）"
            logger.warning(msg)
            return False, msg

        # ---- 执行点击（仅 all 模式：汇总所有匹配结果后逐个点击）----
        # 注意：each_wait / first 模式已在上面的循环内执行点击，这里只处理 all 模式
        need_summary_click = (action == "click") and (batch_click_mode not in ("each_wait", "first"))
        if need_summary_click:
            for match in matched_results:
                if self.should_stop:
                    break
                pos = match["pos"]
                # 执行图像识别匹配点击
                self._do_click(pos, button)
                # 主点击后延迟（等游戏反应弹出框/动画）—— 必须放在
                # 附加点击**之前**，否则主点击和附加点击几乎同时发出，
                # 游戏来不及响应，对话框/动画还没出现，附加点击打不中目标
                if click_delay_ms > 0:
                    time.sleep(click_delay_ms / 1000.0)
                # 执行附加坐标点击（内部已自带 additional_delay_ms）
                if additional_click_enabled:
                    self._do_additional_click(
                        additional_mode,
                        additional_x_expr, additional_y_expr,
                        coord_file, match_field, match_custom_field,
                        additional_button, additional_delay_ms
                    )

        # ---- 汇总结果 ----
        # wait / wait_disappear 动作也支持附加点击
        if action in ("wait", "wait_disappear") and additional_click_enabled and matched_results:
            for match in matched_results:
                if self.should_stop:
                    break
                # wait 动作：主点击 → click_delay 等游戏反应 → 附加点击
                if action == "wait" and match.get("pos") is not None:
                    pos = match["pos"]
                    self._do_click(pos, button)
                    if click_delay_ms > 0:
                        time.sleep(click_delay_ms / 1000.0)
                self._do_additional_click(
                    additional_mode,
                    additional_x_expr, additional_y_expr,
                    coord_file, match_field, match_custom_field,
                    additional_button, additional_delay_ms
                )

        result_parts = []
        for m in matched_results:
            if m.get("disappeared"):
                result_parts.append(f"{m['path']} 已消失")
            else:
                result_parts.append(
                    f"{m['path']} 位置={m['pos']} 置信度={m['conf']:.3f}"
                )
        result = f"图像识别完成: 共匹配 {len(matched_results)} 个模板\n" + "\n".join(result_parts)
        logger.info(result)
        return True, result

    def _resolve_image_template_paths(
        self,
        params: Dict[str, Any],
        source_mode: str
    ) -> List[str]:
        """
        根据 source_mode 解析模板路径列表。

        :param params: 事件参数
        :param source_mode: "direct"/"dynamic"/"batch"
        :return: 模板路径列表
        """
        template_paths = []

        if source_mode == "direct":
            # 直接指定路径
            template_path = str(params.get("template_path", "") or "").strip()
            if template_path:
                if os.path.isfile(template_path):
                    template_paths.append(template_path)
                else:
                    logger.info(f"direct模板跳过：文件不存在 → {template_path}")

        elif source_mode == "dynamic":
            # 动态构建：根据函数调用结果拼接路径
            dyn_field = str(params.get("dyn_field", "target_location") or "target_location")
            dyn_custom = str(params.get("dyn_custom_field", "") or "").strip()
            if dyn_field == "__custom__" and dyn_custom:
                dyn_field = dyn_custom

            # 地图白名单配置（只识别有效地图，忽略其他值如"前往"）
            allowed_maps = params.get("allowed_maps", None)

            # 优先从所有变量中搜索（更健壮，可跨事件查找）
            value = self._search_var_for_field(dyn_field)
            if value is None:
                # 回退：直接从 last_result 获取
                if isinstance(self._last_result, dict):
                    value = self._last_result.get(dyn_field)
                    if value is not None:
                        logger.debug(
                            f"动态模板：从 last_result.{dyn_field} = {value}"
                        )

            if value is not None:
                # 地图白名单检查：如果配置了白名单且值不在白名单中，跳过
                if allowed_maps and str(value) not in allowed_maps:
                    logger.info(
                        f"地图白名单过滤：'{value}' 不在有效地图列表中，跳过 "
                        f"(有效地图: {allowed_maps})"
                    )
                    return template_paths  # 返回空列表，由调用方处理为 skip

                prefix = str(params.get("prefix", "") or "")
                dir_path = str(params.get("dir_path", "") or "")
                suffix = str(params.get("suffix", ".bmp") or ".bmp")

                # 构建路径
                file_name = f"{prefix}{value}{suffix}"
                if dir_path:
                    template_path = f"{dir_path.rstrip('/').rstrip('\\')}/{file_name}"
                else:
                    template_path = file_name

                # 关键保护：构建的文件必须存在，否则直接跳过（避免文件不存在报错+重试）
                if os.path.isfile(template_path):
                    template_paths.append(template_path)
                    logger.info(
                        f"动态模板路径构建: {dyn_field}={value} → {template_path}"
                    )
                else:
                    # 不存在：用 info 级别记录（不打 ERROR，不触发重试），然后跳过
                    logger.info(
                        f"动态模板跳过：文件不存在 "
                        f"({dyn_field}={value} → {template_path})"
                    )
            else:
                logger.warning(f"动态模板构建：字段 {dyn_field} 未找到值")

        elif source_mode == "batch":
            # 批量模式：扫描目录下所有匹配的图片
            batch_dir = str(params.get("batch_dir", "") or "").strip()
            batch_ext = str(params.get("batch_ext", ".bmp,.png,.jpg") or ".bmp,.png,.jpg")
            batch_sort = str(params.get("batch_sort", "name") or "name")
            batch_use_var = bool(params.get("batch_use_var", False))
            batch_var_field = str(params.get("batch_var_field", "target_location") or "target_location")

            if batch_dir and os.path.isdir(batch_dir):
                # 解析扩展名列表
                exts = [e.strip().lower() for e in batch_ext.split(",") if e.strip()]
                if not exts:
                    exts = [".bmp"]

                # 扫描目录
                try:
                    all_files = []
                    for fname in os.listdir(batch_dir):
                        fpath = os.path.join(batch_dir, fname)
                        if not os.path.isfile(fpath):
                            continue
                        _, ext = os.path.splitext(fname)
                        if ext.lower() in exts:
                            all_files.append(fpath)

                    # 如果启用了变量筛选，只保留文件名包含变量值的
                    if batch_use_var:
                        # 优先从所有变量中搜索
                        filter_value = self._search_var_for_field(batch_var_field)
                        if filter_value is None and isinstance(self._last_result, dict):
                            filter_value = self._last_result.get(batch_var_field)
                        if filter_value:
                            filter_str = str(filter_value).lower()
                            all_files = [
                                f for f in all_files
                                if filter_str in os.path.basename(f).lower()
                            ]
                            logger.info(
                                f"批量筛选：保留文件名含 '{filter_value}' 的 "
                                f"{len(all_files)}/{len(os.listdir(batch_dir))} 个文件"
                            )

                    # 排序
                    if batch_sort == "random":
                        import random
                        random.shuffle(all_files)
                    elif batch_sort == "score":
                        # 按文件名长度排序（通常更精确的匹配）
                        all_files.sort(key=lambda x: len(os.path.basename(x)))
                    else:
                        all_files.sort(key=lambda x: os.path.basename(x).lower())

                    template_paths = all_files
                    logger.info(
                        f"批量识别：目录 {batch_dir} 中找到 {len(template_paths)} 个图片文件"
                    )
                except Exception as e:
                    logger.error(f"批量扫描目录失败: {e}")
            else:
                logger.warning(f"批量模式：目录不存在或无效: {batch_dir}")

        return template_paths

    def _search_var_for_field(self, field_name: str) -> Optional[Any]:
        """在所有变量上下文中搜索指定字段的值。"""
        # 特殊映射：map_name 映射到 target_location
        effective_field = field_name
        if field_name == "map_name":
            # 尝试从 last_result 获取 target_location
            if isinstance(self._last_result, dict):
                target_loc = self._last_result.get("target_location")
                if target_loc:
                    logger.debug(f"map_name 映射到 target_location={target_loc}")
                    return target_loc
            # 尝试从位置数据容器获取最后存储的地图名
            all_locs = self._location_container.get_all_locations()
            if all_locs:
                # 获取最后存储的位置
                last_map = list(all_locs.keys())[-1]
                logger.debug(f"map_name 从位置容器获取最后地图名={last_map}")
                return last_map
        
        # 特殊映射：location 字段
        if field_name == "location":
            if isinstance(self._last_result, dict):
                target_loc = self._last_result.get("target_location")
                if target_loc:
                    return target_loc

        # 从位置数据容器中搜索
        if self._location_container.has_location(effective_field):
            location_data = self._location_container.get_location(effective_field)
            if location_data:
                logger.debug(f"从位置数据容器中找到字段 '{effective_field}'={location_data}")
                return location_data

        # 从 last_result 中搜索
        if isinstance(self._last_result, dict):
            val = self._last_result.get(effective_field)
            if val is not None:
                return val

        # 从所有变量中搜索
        for var_name, var_value in self._var_context.items():
            if isinstance(var_value, dict):
                val = var_value.get(effective_field)
                if val is not None:
                    logger.debug(f"从变量 '{var_name}' 中找到字段 '{effective_field}'={val}")
                    return val
            elif hasattr(var_value, effective_field):
                try:
                    val = getattr(var_value, effective_field)
                    if val is not None:
                        return val
                except Exception:
                    pass
        return None

    def _search_var_for_path(self, var_path: str) -> Optional[Any]:
        """
        通过路径（如 "JHRW.target_coord.0"）在变量上下文中查找值。

        支持：
        - 顶层变量名: "JHRW" → 直接返回变量值
        - 点号路径: "JHRW.target_coord" → 返回 dict 中对应键
        - 索引访问: "JHRW.target_coord.0" → 返回列表/元组中第 N 个元素
        """
        parts = var_path.split(".")
        if not parts:
            return None

        # 获取顶层变量
        top_name = parts[0]
        if top_name in self._var_context:
            current = self._var_context[top_name]
        elif isinstance(self._last_result, dict) and top_name in self._last_result:
            current = self._last_result[top_name]
        else:
            # 在所有变量中搜索匹配的顶层名
            found = False
            for var_name, var_value in self._var_context.items():
                if var_name == top_name:
                    current = var_value
                    found = True
                    break
            if not found:
                # 尝试从 last_result 中搜索
                if isinstance(self._last_result, dict):
                    current = self._last_result
                else:
                    return None

        # 遍历剩余路径
        for part in parts[1:]:
            if current is None:
                return None

            # 尝试索引访问（数字）
            try:
                idx = int(part)
                if isinstance(current, (list, tuple)) and 0 <= idx < len(current):
                    current = current[idx]
                    continue
            except (ValueError, TypeError):
                pass

            # 尝试键访问
            if isinstance(current, dict):
                current = current.get(part)
            elif hasattr(current, part):
                try:
                    current = getattr(current, part)
                except Exception:
                    return None
            else:
                return None

        return current

    def _do_click(self, target_coord: tuple, click_type: str = "left", delay: float = 0.0,
                  press_delay: float = 0.05) -> bool:
        """
        统一点击逻辑。

        :param target_coord: 目标坐标元组 (x, y)
        :param click_type: 点击类型 "left"/"right"/"double"
        :param delay: 点击后延迟(秒)
        :param press_delay: 按下→弹起保持时间(秒)，后台模式生效，可 GUI 配置
        :return: 是否成功
        """
        try:
            x, y = int(target_coord[0]), int(target_coord[1])

            # 检查窗口是否已绑定
            from core.window_manager import window_manager
            if not window_manager.is_valid():
                logger.warning(f"点击跳过: 窗口未绑定或已失效")
                return False

            if click_type == "double":
                input_controller.double_click(x, y)
            elif click_type == "right":
                input_controller.click(x, y, button="right", press_delay=press_delay)
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

    def _check_coord_readable(self) -> bool:
        """
        快速检测坐标读取是否可用（字模方案）。

        使用全局坐标读取器单例（glyph 字模版），避免创建新实例。

        :return: True=可读取有效坐标，False=窗口未绑定或识别不可用
        """
        try:
            from core.game_coord_reader import get_coord_reader
            reader = get_coord_reader()

            # 字模版：需窗口已绑定（不再连接进程，见 game_coord_reader 模块头）
            if not reader.is_connected:
                try:
                    from core.window_manager import window_manager
                    bound_pid = int(getattr(window_manager, "pid", 0) or 0)
                    if not bound_pid:
                        return False
                    if not reader.connect(bound_pid):
                        return False
                except Exception as e:
                    logger.warning(f"从窗口管理器获取绑定 PID 失败: {e}")
                    return False

            # 尝试读取坐标
            coords = reader.read_coords()
            if coords is None:
                return False
            x, y = coords
            if abs(x) < 0.01 and abs(y) < 0.01:
                return False
            return True
        except Exception as e:
            logger.debug(f"_check_coord_readable异常: {e}")
            return False

    def _check_auto_wait_arrival(
        self, params: Dict[str, Any], result: Any, func_kwargs: Dict = None
    ) -> Tuple[bool, Any]:
        """
        检查是否需要自动等待角色到达目标位置。

        当函数调用事件配置了 auto_wait_arrival=True 时，
        自动从返回结果中提取目标坐标，等待角色移动停止并到达目标位置。

        自动启用条件：函数结果包含 target_game 字段（地图数据函数的特征字段）。
        注意：JHRW 等查询函数返回 target_coord 但不返回 target_game，因此不会误触发。

        :param params: 事件参数
        :param result: 函数调用结果
        :param func_kwargs: 原始函数调用的kwargs（保留兼容，暂未使用）
        :return: (success, result)
        """
        # 检查是否启用了自动等待到达
        auto_wait = params.get("auto_wait_arrival", False)

        # 如果用户未手动启用，但函数调用结果中包含 target_game 字段，
        # 则自动启用等待到达（target_game 是地图数据函数的独有字段，
        # JHRW 等查询函数只返回 target_coord，不会误触发）
        if not auto_wait and isinstance(result, dict):
            target_game = result.get("target_game")
            if target_game and isinstance(target_game, (list, tuple)) and len(target_game) >= 2:
                auto_wait = True
                logger.info("检测到函数返回 target_game，自动启用等待到达")

        if not auto_wait:
            return True, result

        # 从结果中提取目标坐标
        target_coord = None
        if isinstance(result, dict):
            # 兼容多种字段名
            target_coord = (
                result.get("target_coord")
                or result.get("target_game")
                or result.get("coord")
            )

        if not target_coord or not isinstance(target_coord, (list, tuple)) or len(target_coord) < 2:
            logger.warning(
                "自动等待到达：未能从函数调用结果中提取目标坐标"
            )
            self._emit_log(
                "warning", "自动等待到达：未找到目标坐标，跳过等待"
            )
            return True, result

        target_x = float(target_coord[0])
        target_y = float(target_coord[1])

        # 禁区规避（2026-08-05）：自动等待到达的目标坐标也必须在禁区外，
        # 否则 JHRW 读出的原始坐标（如建邺城 (271,114)）落在传送热点上，
        # 角色走到会被传送。地图名优先取 result.target_location，取不到
        # 则按模块名映射（result 来自 JYC/JNYW 等地图函数时模块名可映射）。
        try:
            from core.map_no_go import MODULE_MAP_NAME, resolve_safe_coord
            map_name = ""
            if isinstance(result, dict):
                map_name = str(result.get("target_location") or result.get("location") or "").strip()
            if not map_name:
                _mod = str(params.get("module_name") or "").upper()
                map_name = MODULE_MAP_NAME.get(_mod, "")
            if map_name:
                _sx, _sy, _adj = resolve_safe_coord(map_name, target_x, target_y)
                if _adj:
                    logger.info(
                        f"[禁区规避] 等待到达目标 ({target_x:.0f},{target_y:.0f})"
                        f" 在 {map_name} 禁区内 → 修正为 ({_sx:.0f},{_sy:.0f})"
                    )
                    target_x, target_y = _sx, _sy
                # UI 遮挡避让（2026-08-05）：大地图打开时超出有效点击范围的
                # 坐标点落在大地图 UI 上，等待目标同步钳制（用户实测上限）
                from core.map_ui_block import map_coord_ui_avoid
                _ux, _uy, _ui = map_coord_ui_avoid(map_name, target_x, target_y)
                if _ui:
                    logger.info(
                        f"[UI避让] 等待到达目标 ({target_x:.0f},{target_y:.0f})"
                        f" 在 {map_name} 超出有效范围 → 修正为 ({_ux:.0f},{_uy:.0f})"
                    )
                    target_x, target_y = _ux, _uy
        except Exception as e:
            logger.debug(f"等待到达禁区规避异常（不影响等待）: {e}")

        # 获取配置参数（事件驱动版，2026-08-05）
        wait_timeout = float(params.get("wait_arrival_timeout", 0.0))
        wait_tolerance = float(params.get("wait_arrival_tolerance", 3.0))
        # 静止确认秒数（新逻辑）；向后兼容老任务的 wait_arrival_stable_count（次数）
        _stop_confirm = params.get("wait_arrival_stop_confirm_s")
        if _stop_confirm is None:
            _old = params.get("wait_arrival_stable_count")
            if _old is not None:
                _stop_confirm = float(_old) / 5.0  # 老字段 5 次 ≈ 1 秒
            else:
                _stop_confirm = 1.0  # 默认 1.0s
        wait_stop_confirm_s = float(_stop_confirm)
        wait_sample_interval = float(params.get("wait_arrival_sample_interval", 0.2))
        # 等待期间是否把鼠标挪到屏幕 (5,5)（默认 True，防遮挡识别目标）
        wait_hide_mouse = str(params.get("wait_arrival_hide_mouse", "true")).lower() != "false"

        # 获取 PID
        # 优先从函数调用结果中获取（result 中有 pid 字段）
        pid = None
        if isinstance(result, dict) and result.get("pid"):
            try:
                pid = int(result["pid"])
            except (ValueError, TypeError):
                pass

        # 其次从参数中获取
        if pid is None:
            pid = params.get("pid")
            if pid is not None:
                try:
                    pid = int(pid)
                except (ValueError, TypeError):
                    pid = None

        # 从位置容器获取 PID
        if pid is None and self._location_container:
            try:
                locs = self._location_container.get_all_locations()
                for loc_data in locs.values():
                    if isinstance(loc_data, dict) and loc_data.get("pid"):
                        pid = int(loc_data["pid"])
                        break
            except (ValueError, TypeError):
                pass

        # 从窗口管理器获取绑定的 PID
        if pid is None:
            try:
                from core.window_manager import window_manager
                bound_pid = int(getattr(window_manager, "pid", 0) or 0)
                if bound_pid:
                    pid = bound_pid
                    logger.info(f"从窗口管理器获取绑定 PID={pid}")
            except Exception as e:
                logger.warning(f"从窗口管理器获取绑定 PID 失败: {e}")

        if pid is None:
            logger.error("无法获取游戏进程PID，坐标读取器未连接")
            self._emit_log(
                "error",
                "自动等待到达：无法获取游戏进程PID，请先绑定窗口"
            )
            return True, result

        # 导入 ArrivalVerifier
        try:
            from core.arrival_verifier import ArrivalVerifier

            verifier = ArrivalVerifier(
                tolerance=wait_tolerance,
                timeout=wait_timeout,
                stop_confirm_s=wait_stop_confirm_s,
            )

            def _should_stop():
                return self.should_stop or self.is_paused

            self._emit_log(
                "info",
                f"自动等待到达：目标=({target_x:.1f}, {target_y:.1f})"
                f"，移动兜底超时={wait_timeout}s(0=自动)，"
                f"静止确认={wait_stop_confirm_s}s"
            )

            ok, msg, current = verifier.wait_for_arrival(
                target_x=target_x,
                target_y=target_y,
                pid=pid,
                should_stop_cb=_should_stop,
                sample_interval=wait_sample_interval,
                tolerance=wait_tolerance,
                timeout=wait_timeout,
                stop_confirm_s=wait_stop_confirm_s,
                hide_mouse=wait_hide_mouse,
            )

            if ok:
                self._emit_log("info", f"自动等待到达：{msg}")
                return True, result
            else:
                self._emit_log("warning", f"自动等待到达失败：{msg}")

                # 2026-08-06 到达失败后抖动重试（用户方案）：
                #   1) 在【游戏坐标】上随机偏移 +10~50（X、Y 独立随机）；
                #   2) 抖动后坐标不能超过大地图有效点击范围（max_game_coord，
                #      用户实测，如建邺城 [284,140]）——超了则改为反向 -10~50；
                #   3) 抖动坐标单击一次 → 延迟 2s → 再点击原来任务正确的坐标。
                # 背景：同一坐标重试必然再踩同一个坑（大地图/UI 边缘是像素级
                # 判定），偏移后总有一次落在有效点击区。
                try:
                    from core.input_controller import input_controller
                    from core.map_ui_block import get_map_calibration, _load_ui_blocks

                    # 大地图有效点击范围（max_game_coord），拿不到不限制
                    _max_x = _max_y = None
                    try:
                        _entry = _load_ui_blocks().get(map_name) or {}
                        _limit = _entry.get("max_game_coord")
                        if _limit and len(_limit) == 2:
                            _max_x, _max_y = float(_limit[0]), float(_limit[1])
                    except Exception:
                        pass

                    # 1) 正向抖动 +10~50（游戏坐标）
                    _jx = target_x + random.uniform(10.0, 50.0)
                    _jy = target_y + random.uniform(10.0, 50.0)
                    # 2) 超大地图范围 → 反向 -10~50
                    if _max_x is not None and (_jx > _max_x or _jy > _max_y):
                        logger.info(
                            f"[到达重试] 抖动坐标 ({_jx:.0f},{_jy:.0f}) 超出大地图"
                            f"有效范围 ({_max_x:.0f},{_max_y:.0f}) → 反向抖动"
                        )
                        _jx = target_x - random.uniform(10.0, 50.0)
                        _jy = target_y - random.uniform(10.0, 50.0)

                    # 游戏坐标 → 客户区像素（用地图校准）
                    _calib = get_map_calibration(map_name)
                    if _calib is not None:
                        _ox, _oy, _sx, _sy = _calib
                        # 抖动坐标像素
                        _jpx = _ox + _jx * _sx
                        _jpy = _oy + _jy * _sy
                        # 原始正确坐标像素
                        _tpx = _ox + target_x * _sx
                        _tpy = _oy + target_y * _sy
                        logger.info(
                            f"[到达重试] 目标({target_x:.0f},{target_y:.0f}) 到达失败，"
                            f"抖动点击 ({_jx:.0f},{_jy:.0f}) → 像素({_jpx:.0f},{_jpy:.0f})"
                        )
                        input_controller.click(int(_jpx), int(_jpy), button="left")
                        # 3) 单击后延迟 2s，再点击原来任务正确的坐标
                        time.sleep(2.0)
                        logger.info(
                            f"[到达重试] 延迟 2s 后点击原目标坐标 "
                            f"({target_x:.0f},{target_y:.0f}) → 像素({_tpx:.0f},{_tpy:.0f})"
                        )
                        input_controller.click(int(_tpx), int(_tpy), button="left")
                        # 二次等待到达（复用 verifier，短超时）
                        _ok2, _msg2, _cur2 = verifier.wait_for_arrival(
                            target_x=target_x,
                            target_y=target_y,
                            pid=pid,
                            should_stop_cb=_should_stop,
                            sample_interval=wait_sample_interval,
                            tolerance=wait_tolerance,
                            timeout=min(wait_timeout, 30.0) if wait_timeout > 0 else 30.0,
                            stop_confirm_s=wait_stop_confirm_s,
                            hide_mouse=wait_hide_mouse,
                        )
                        if _ok2:
                            self._emit_log("info", f"自动等待到达（抖动重试后）：{_msg2}")
                            return True, result
                        self._emit_log("warning", f"自动等待到达（抖动重试后仍失败）：{_msg2}")
                    else:
                        logger.debug(
                            f"到达抖动重试跳过：{map_name!r} 无地图校准数据"
                        )
                except Exception as e:
                    logger.debug(f"到达抖动重试异常（不影响主流程）: {e}")

                # 返回 False 表示未到达，由调用方决定是否重试函数调用
                return False, result

        except ImportError as e:
            logger.error(f"导入 ArrivalVerifier 失败: {e}")
            self._emit_log("error", f"自动等待到达功能不可用: {e}")
            return True, result
        except Exception as e:
            logger.error(f"自动等待到达异常: {e}")
            self._emit_log("error", f"自动等待到达异常: {e}")
            return True, result

    def _auto_store_location(self, result: Any) -> None:
        """
        自动从函数调用结果中提取位置数据并存入容器。

        支持的格式：
        - {"target_location": "江南野外 145，35"}
        - "江南野外 145，35"（纯字符串）
        - {"target_location": "江南野外", "target_coord": [145, 35]}

        :param Any result: 函数调用结果
        """
        try:
            stored = self._location_container.store_from_result(result)
            if stored:
                logger.info(
                    f"位置数据已存储: {stored['location']} "
                    f"({stored['x']}, {stored['y']})"
                )
        except Exception as e:
            logger.debug(f"自动存储位置数据失败（忽略）: {e}")

    def _execute_function_call(self, params):
        """
        函数调用事件执行器。

        params 结构：
            {"module": "", "function": "", "args": [], "kwargs": {}}

        特殊功能：
        - 当 module 为 "auto" 时，自动根据上一次函数调用结果中的中文地图名
          在所有地图模块中搜索匹配的模块并执行
        - 支持结果验证和重试：当返回值不在白名单中时自动重试

        :param params: 事件参数
        :return: (success, result)
        """
        module_name = params.get("module", "")
        function_name = params.get("function", "")
        args = params.get("args", []) or []
        kwargs = params.get("kwargs", {}) or {}

        # args 必须是列表/元组，kwargs 必须是字典
        if not isinstance(args, (list, tuple)):
            args = [args]
        if not isinstance(kwargs, dict):
            kwargs = {}

        # === 自动匹配模式：module 为 "auto" ===
        if module_name.lower() == "auto":
            return self._execute_auto_match(function_name, args, kwargs)

        if not module_name or not function_name:
            msg = "函数调用事件缺少 module 或 function 参数"
            logger.warning(msg)
            return False, msg

        # === 结果验证配置 ===
        validate_field = params.get("result_validate_field", None)
        validate_whitelist = params.get("result_validate_whitelist", None)
        validate_retries = int(params.get("result_validate_retries", 3))
        validate_retry_interval = float(params.get("result_validate_retry_interval", 0.5))

        # === 到达失败重试配置 ===
        # 当启用自动等待到达时，若角色未到达目标，重新执行函数调用（包括按Tab+点击）
        auto_wait = params.get("auto_wait_arrival", False)
        # 注意：即使auto_wait为False，如果函数返回结果包含target_game/target_coord，
        # _check_auto_wait_arrival也会自动启用等待。因此重试次数始终计算。
        wait_arrival_retries = int(params.get("wait_arrival_retries", 3))
        # 重试循环：总次数 = 1(初始) + max(验证重试, 到达重试)
        # 到达重试始终计算，因为_check_auto_wait_arrival会根据返回结果自动启用
        if validate_field and validate_whitelist:
            max_attempts = 1 + max(validate_retries, wait_arrival_retries)
        else:
            max_attempts = 1 + wait_arrival_retries
        
        for attempt in range(1, max_attempts + 1):
            if self.should_stop:
                return False, "任务被停止"

            try:
                logger.info(
                    f"调用任务库函数: {module_name}.{function_name}"
                    f"(args={args}, kwargs={kwargs})"
                    f"{f' (第{attempt}次)' if attempt > 1 else ''}"
                )
                success, result, error = task_library.call_function(
                    module_name, function_name, *args, **kwargs
                )
                if success:
                    logger.info(
                        f"函数调用成功: {module_name}.{function_name} -> {result}"
                    )

                    # === 自动存储位置数据 ===
                    self._auto_store_location(result)

                    # === 推送任务详情到 IPC（必须在 validate 之前，否则
                    #     验证失败/重试耗尽时 result 永远不会到 StatusPanel）===
                    # 每次函数调用成功都广播一次，验证失败也带数据进 IPC，
                    # 方便用户观察"函数本身能跑出啥"。重试会用最新 result 覆盖。
                    self._maybe_emit_quest_detail(result)

                    # === 结果验证 ===
                    if validate_field and validate_whitelist:
                        # 获取要验证的字段值
                        field_value = None
                        if isinstance(result, dict):
                            field_value = result.get(validate_field)
                        
                        if field_value is not None:
                            if str(field_value) in validate_whitelist:
                                logger.info(
                                    f"结果验证通过: {validate_field}='{field_value}' 在白名单中"
                                )
                                # 结果验证通过后，检查自动等待到达
                                arrived, result = self._check_auto_wait_arrival(params, result, kwargs)
                                if arrived:
                                    return True, result
                                # 未到达，检查是否还能重试
                                if attempt < max_attempts:
                                    # 如果任务被停止，不重试
                                    if self.should_stop:
                                        return True, result
                                    # 检查坐标读取是否可用，避免无意义重试
                                    if not self._check_coord_readable():
                                        logger.error("坐标地址失效，无法等待到达，停止重试")
                                        self._emit_log("error", "坐标读取失败，请重新扫描地址或绑定窗口")
                                        return True, result
                                    logger.warning(f"角色未到达目标，准备重新执行函数调用")
                                    self._emit_log("warning", f"角色未到达目标，重新执行地图函数")
                                    time.sleep(validate_retry_interval)
                                    continue
                                logger.warning(f"到达失败，已重试{max_attempts - 1}次仍失败，继续执行")
                                return True, result
                            else:
                                # 不在白名单中，需要重试
                                logger.warning(
                                    f"结果验证失败: {validate_field}='{field_value}' "
                                    f"不在白名单 {validate_whitelist} 中"
                                )
                                if attempt < max_attempts:
                                    logger.info(
                                        f"将在 {validate_retry_interval}s 后重新调用函数..."
                                    )
                                    time.sleep(validate_retry_interval)
                                    continue
                                else:
                                    # 达到最大重试次数，返回失败
                                    error_msg = (
                                        f"函数调用结果验证失败，已重试 {validate_retries} 次，"
                                        f"'{field_value}' 不在有效地图列表中"
                                    )
                                    logger.error(error_msg)
                                    return False, error_msg
                        else:
                            logger.warning(
                                f"结果验证字段 '{validate_field}' 未找到，跳过验证"
                            )
                            arrived, result = self._check_auto_wait_arrival(params, result, kwargs)
                            if arrived:
                                return True, result
                            if attempt < max_attempts:
                                if self.should_stop:
                                    return True, result
                                if not self._check_coord_readable():
                                    logger.error("坐标地址失效，无法等待到达，停止重试")
                                    self._emit_log("error", "坐标读取失败，请重新扫描地址或绑定窗口")
                                    return True, result
                                logger.warning(f"角色未到达目标，准备重新执行函数调用")
                                self._emit_log("warning", f"角色未到达目标，重新执行地图函数")
                                time.sleep(validate_retry_interval)
                                continue
                            logger.warning(f"到达失败，已重试{max_attempts - 1}次仍失败，继续执行")
                            return True, result

                    # 无结果验证配置，直接检查自动等待到达
                    arrived, result = self._check_auto_wait_arrival(params, result, kwargs)
                    if arrived:
                        return True, result
                    if attempt < max_attempts:
                        if self.should_stop:
                            return True, result
                        if not self._check_coord_readable():
                            logger.error("坐标地址失效，无法等待到达，停止重试")
                            self._emit_log("error", "坐标读取失败，请重新扫描地址或绑定窗口")
                            return True, result
                        logger.warning(f"角色未到达目标，准备重新执行函数调用")
                        self._emit_log("warning", f"角色未到达目标，重新执行地图函数")
                        time.sleep(validate_retry_interval)
                        continue
                    logger.warning(f"到达失败，已重试{max_attempts - 1}次仍失败，继续执行")
                    return True, result
                else:
                    logger.error(
                        f"函数调用失败: {module_name}.{function_name}: {error}"
                    )
                    # 函数调用本身失败，不重试（由事件重试机制处理）
                    return False, error
                    
            except Exception as e:
                logger.exception(f"函数调用执行异常: {e}")
                if attempt < max_attempts:
                    logger.info(f"异常后将在 {validate_retry_interval}s 后重试...")
                    time.sleep(validate_retry_interval)
                    continue
                return False, str(e)

        return False, "函数调用重试耗尽"

    def _execute_auto_match(self, function_name, args, kwargs):
        """
        自动匹配模式执行器：根据上一次函数调用结果中的中文地图名
        在所有地图模块中搜索匹配的模块并执行。

        搜索逻辑：
        1. 从 last_result 中尝试获取 target_location 字段
        2. 如果没有，从 _var_context 中搜索包含中文地图名的字段
        3. 使用中文地图名在 task_library 的 map 分类中搜索匹配的模块

        :param function_name: 要调用的函数名（如模块名匹配后调用同名函数）
        :param args: 位置参数
        :param kwargs: 关键字参数
        :return: (success, result)
        """
        # 步骤 1: 获取中文地图名
        location_name = None

        # 优先从 last_result 获取
        if isinstance(self._last_result, dict):
            location_name = self._last_result.get("target_location")

        # 如果没有，从所有变量中搜索
        if not location_name:
            for var_name, var_value in self._var_context.items():
                if isinstance(var_value, dict):
                    loc = var_value.get("target_location")
                    if loc and isinstance(loc, str) and any('\u4e00' <= c <= '\u9fff' for c in loc):
                        location_name = loc
                        logger.info(f"从变量 '{var_name}' 中找到地图名: {loc}")
                        break

        if not location_name:
            msg = "自动匹配失败：未找到中文地图名（target_location）"
            logger.error(msg)
            return False, msg

        logger.info(f"自动匹配：搜索地图 '{location_name}' 对应的模块...")

        # 步骤 2: 在 task_library 中搜索匹配的地图模块
        matched_module = task_library.search_map_by_name(location_name)

        if not matched_module:
            msg = f"自动匹配失败：未找到地图 '{location_name}' 对应的地图模块"
            logger.error(msg)
            logger.info(f"提示：请确保地图模块的文档（__doc__）中包含中文地图名 '{location_name}'")
            return False, msg

        logger.info(f"自动匹配成功：地图 '{location_name}' -> 模块 '{matched_module}'")

        # 步骤 3: 使用匹配到的模块执行函数
        # 如果 function_name 为空，使用模块名作为函数名
        actual_function = function_name if function_name else matched_module

        # 地图模块的函数（如 JNYW, DHW）期望接收一个坐标元组作为单参数
        # 例如 JNYW((gx, gy))，而非 JNYW(gx, gy)
        # 因此当 args 有 2 个数值时，将其打包为单个元组
        final_args = args
        module_info = task_library.modules.get(matched_module, {})
        if module_info.get("category") == "map" and len(args) == 2:
            try:
                coord_tuple = (int(args[0]), int(args[1]))
                final_args = [coord_tuple]
                logger.info(
                    f"地图模块参数转换: {args} -> {final_args}"
                )
            except (ValueError, TypeError):
                pass

        try:
            logger.info(
                f"自动调用: {matched_module}.{actual_function}"
                f"(args={final_args}, kwargs={kwargs})"
            )
            success, result, error = task_library.call_function(
                matched_module, actual_function, *final_args, **kwargs
            )
            if success:
                logger.info(
                    f"自动调用成功: {matched_module}.{actual_function} -> {result}"
                )
                return True, result
            else:
                logger.error(
                    f"自动调用失败: {matched_module}.{actual_function}: {error}"
                )
                return False, error
        except Exception as e:
            logger.exception(f"自动调用执行异常: {e}")
            return False, str(e)

    def _execute_condition(self, event: Event, depth: int = 0) -> tuple:
        """
        执行条件分支事件（增强版 - 真正的分支控制流）。

        支持两种模式：
        1. mode = "simple"：
            执行条件判断，根据结果执行 true_branch 或 false_branch 事件序列。

        2. mode = "switch"：
            从变量上下文中取字段值，匹配 case 并执行对应的 actions 事件序列。

        支持嵌套 condition（最多3层），通过 depth 参数控制。

        :param event: Event 实例
        :param depth: 当前嵌套深度（0-3）
        :return: (success, result)
        """
        # 检查嵌套深度
        if depth > 3:
            logger.warning("Condition嵌套深度超过3层，停止执行")
            return False, {"error": "max_depth_exceeded", "depth": depth}

        params = event.params
        mode = str(params.get("mode", "simple")).lower()

        if mode == "simple":
            # ============ simple 模式：条件判断 + 分支执行 ============
            # 1. 执行条件判断
            result, cond, actual, value = self._evaluate_simple_condition(params)

            if not result:
                # 条件判断本身失败（如类型错误）
                return False, cond

            # 2. 根据结果选择分支
            branch_key = "true_branch" if cond else "false_branch"
            branch_events = params.get(branch_key, [])

            if not branch_events:
                # 分支为空，直接返回结果
                logger.info(
                    f"条件判断: {actual!r} {params.get('operator', '==')} {value!r} "
                    f"-> {cond}，分支 {branch_key} 为空，跳过"
                )
                return True, {
                    "condition": cond,
                    "actual": actual,
                    "value": value,
                    "branch": branch_key,
                    "executed": False,
                }

            # 3. 递归执行分支事件序列
            logger.info(
                f"条件判断: {actual!r} {params.get('operator', '==')} {value!r} "
                f"-> {cond}，执行分支 {branch_key}（{len(branch_events)} 个事件）"
            )

            executed_results = []
            for branch_event_data in branch_events:
                if self.should_stop:
                    break

                # 从字典创建事件实例
                try:
                    branch_event = Event.from_dict(branch_event_data)
                except Exception as e:
                    logger.warning(f"分支事件反序列化失败: {e}")
                    continue

                # 递归执行事件
                success, branch_result = self._execute_event_with_depth(
                    branch_event, depth=depth + 1
                )
                executed_results.append({
                    "event": branch_event.name,
                    "success": success,
                    "result": branch_result,
                })

                # 如果分支事件失败且策略为 stop，中止整个分支
                if not success and branch_event.on_error == "stop":
                    logger.error(
                        f"分支事件 {branch_event.name!r} 失败（on_error=stop），"
                        f"中止分支执行"
                    )
                    return False, {
                        "condition": cond,
                        "branch": branch_key,
                        "error": f"branch_event_failed: {branch_result}",
                    }

            return True, {
                "condition": cond,
                "actual": actual,
                "value": value,
                "branch": branch_key,
                "executed": True,
                "results": executed_results,
            }

        elif mode == "switch":
            # ============ switch 模式：匹配 case + 执行动作序列 ============
            return self._execute_switch_condition_with_depth(params, depth)

        else:
            msg = f"未知的 condition 模式: {mode!r}"
            logger.warning(msg)
            return False, msg

    def _evaluate_simple_condition(self, params):
        """
        执行 simple 模式的条件判断。

        :param params: 事件参数
        :return: (success, condition_result, actual, value)
        """
        variable = params.get("variable", "")
        operator = str(params.get("operator", "==")).lower()
        value = params.get("value", None)

        # 用 _search_var_for_field 或 _resolve_value 解析变量
        if variable in ("", "last_result", "last"):
            actual = self._last_result
        elif "." in variable or variable in self._var_context:
            actual = self._resolve_value(variable)
        else:
            actual = self._search_var_for_field(variable)
            if actual is None:
                actual = variable

        try:
            if operator == "==":
                cond = actual == value
            elif operator == "!=":
                cond = actual != value
            elif operator == ">":
                cond = actual is not None and value is not None and actual > value
            elif operator == "<":
                cond = actual is not None and value is not None and actual < value
            elif operator == ">=":
                cond = actual is not None and value is not None and actual >= value
            elif operator == "<=":
                cond = actual is not None and value is not None and actual <= value
            else:
                msg = f"不支持的条件运算符: {operator!r}"
                logger.warning(msg)
                return False, msg, actual, value
        except TypeError as e:
            msg = f"条件比较类型错误: {e}"
            logger.warning(msg)
            return False, msg, actual, value

        return True, cond, actual, value

    def _execute_event_with_depth(self, event: Event, depth: int = 0):
        """
        带深度控制的事件执行（用于 condition 分支递归）。

        :param event: Event 实例
        :param depth: 当前嵌套深度
        :return: (success, result)
        """
        # 未启用则跳过
        if not event.enabled:
            logger.debug(f"分支事件未启用，跳过: {event.name!r}")
            return True, "skipped"

        # 执行前延迟
        if event.pre_delay and event.pre_delay > 0:
            logger.debug(f"分支事件 {event.name!r} pre_delay={event.pre_delay}s")
            self._interruptible_sleep(event.pre_delay)
            if self.should_stop:
                return False, "任务被停止"

        # 分发执行（带重试逻辑）
        success, result = self._dispatch_with_retry_and_depth(event, depth)

        # 执行后延迟
        if event.post_delay and event.post_delay > 0 and not self.should_stop:
            logger.debug(f"分支事件 {event.name!r} post_delay={event.post_delay}s")
            self._interruptible_sleep(event.post_delay)

        return success, result

    def _dispatch_with_retry_and_depth(self, event: Event, depth: int = 0):
        """
        带深度控制的事件分发（用于 condition 分支递归）。

        对于 CONDITION 类型事件，传递 depth 参数；
        对于其他类型，直接分发执行。

        :param event: Event 实例
        :param depth: 当前嵌套深度
        :return: (success, result)
        """
        max_attempts = 1
        if event.on_error == "retry":
            max_attempts = 1 + max(0, event.max_retries)

        last_success = False
        last_result = None
        last_error = None

        for attempt in range(1, max_attempts + 1):
            if self.should_stop:
                return False, "任务被停止"

            # 2026-08-05 增强：子流程/分支事件也打印"开始执行"，便于
            # 子流程里卡住时定位（之前只有主流程 _dispatch_with_retry 有，
            # condition 分支里看不到"开始执行"，卡住时无从定位）。
            if attempt == 1:
                params_summary = _summarize_event_params(event)
                prefix = "  " * depth if depth > 0 else ""
                logger.info(
                    f"{prefix}开始执行分支事件 {event.name!r} [{event.event_type}] "
                    f"params={params_summary}"
                )

            try:
                # 对于 CONDITION 事件，传递 depth 参数
                if event.event_type == EventType.CONDITION:
                    success, result = self._execute_condition(event, depth=depth)
                else:
                    success, result = self._dispatch(event)

                if success:
                    if attempt > 1:
                        logger.info(
                            f"分支事件 {event.name!r} 在第 {attempt} 次尝试成功"
                        )
                    return True, result

                last_success = False
                last_result = result
                last_error = str(result) if result is not None else "执行失败"
            except Exception as e:
                last_success = False
                last_result = None
                last_error = str(e)
                logger.exception(
                    f"分支事件 {event.name!r} 第 {attempt} 次执行异常: {e}"
                )

            if attempt < max_attempts:
                logger.warning(
                    f"分支事件 {event.name!r} 第 {attempt} 次失败，"
                    f"准备重试（共 {max_attempts} 次）: {last_error}"
                )
                time.sleep(0.2)

        if event.on_error == "skip":
            return True, f"skipped: {last_error}"

        return False, last_error or "执行失败"

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
                if self.should_stop:
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
    def _emit_log(self, level, message):
        """
        发射日志信号，失败时静默忽略。

        :param level: 日志级别字符串（"info"/"warning"/"error"/...）
        :param message: 日志消息
        """
        try:
            self.log_signal.emit(str(level), str(message))
        except Exception:
            pass

    def _emit_status(self, status):
        """
        发射状态信号，失败时静默忽略。

        :param status: 状态文本
        """
        try:
            self.status_signal.emit(str(status))
        except Exception:
            pass



# 模块级单例实例，供全局使用
task_engine = TaskEngine()
