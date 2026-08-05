# -*- coding: utf-8 -*-
"""
任务序列模型模块。

定义 TaskSequence 类，负责编排多个 Task 的执行顺序，
并维护当前任务 / 当前事件的游标位置，支持前进、重置等操作。
"""
import os
import json
import uuid

from utils.helpers import ensure_dir
from utils.logger import logger
from models.task import Task


class TaskSequence:
    """
    任务序列：编排多个 Task 的执行。

    :ivar str id: 序列唯一标识（UUID 字符串）
    :ivar str name: 序列名称
    :ivar list[Task] tasks: 任务列表（按执行顺序）
    :ivar int current_task_index: 当前任务下标
    :ivar int current_event_index: 当前事件下标
    :ivar int loop_count: 序列循环次数，0 表示无限循环，默认 1
    :ivar float loop_delay: 序列循环间隔（秒），默认 1.0
    """

    def __init__(self, name="", tasks=None, current_task_index=0,
                 current_event_index=0, id=None,
                 loop_count=1, loop_delay=1.0):
        """
        构造一个任务序列。

        :param name: 序列名称
        :param tasks: 任务列表，元素可为 Task 实例或字典
        :param current_task_index: 初始任务下标
        :param current_event_index: 初始事件下标
        :param id: 指定 ID，未指定时自动生成
        """
        self.id = id if id else str(uuid.uuid4())
        self.name = name if name else ""
        # 任务列表：兼容 Task 实例或字典
        self.tasks = []
        if tasks:
            for t in tasks:
                self.tasks.append(self._coerce_task(t))
        # 游标初始化（会做边界裁剪）
        self.current_task_index = self._clamp_task_index(current_task_index)
        self.current_event_index = self._clamp_event_index(current_event_index)
        # 序列循环：0=无限循环，默认 1（执行一次不循环）
        self.loop_count = max(0, int(loop_count)) if loop_count is not None else 1
        self.loop_delay = float(loop_delay) if loop_delay is not None else 1.0

    @staticmethod
    def _coerce_task(t):
        """将传入对象统一转换为 Task 实例。"""
        if isinstance(t, Task):
            return t
        if isinstance(t, dict):
            return Task.from_dict(t)
        raise TypeError(f"任务类型不合法，期望 Task 或 dict，收到 {type(t).__name__}")

    def _clamp_task_index(self, idx):
        """裁剪任务下标到合法范围 [0, len(tasks)-1]，空列表返回 0。"""
        if not self.tasks:
            return 0
        idx = max(0, int(idx))
        return min(idx, len(self.tasks) - 1)

    def _clamp_event_index(self, idx):
        """裁剪事件下标到当前任务的合法范围。"""
        current = self.get_current_task()
        if current is None or len(current.events) == 0:
            return 0
        idx = max(0, int(idx))
        return min(idx, len(current.events) - 1)

    # ------------------------------------------------------------------
    # 任务管理
    # ------------------------------------------------------------------
    def add_task(self, task):
        """
        添加任务到末尾。

        :param task: Task 实例或字典
        :return: 添加后的 Task 实例
        """
        t = self._coerce_task(task)
        self.tasks.append(t)
        return t

    def remove_task(self, task_id):
        """
        按 ID 删除任务。

        :param str task_id: 任务 ID
        :return: bool，是否删除成功
        """
        for i, t in enumerate(self.tasks):
            if t.id == task_id:
                self.tasks.pop(i)
                # 删除后修正游标，避免越界
                self.current_task_index = self._clamp_task_index(self.current_task_index)
                self.current_event_index = 0
                return True
        logger.warning(f"未找到要移除的任务: id={task_id}, 序列={self.name}")
        return False

    def get_task_by_id(self, task_id):
        """按 ID 查找任务，未找到返回 None。"""
        for t in self.tasks:
            if t.id == task_id:
                return t
        return None

    def get_current_task(self):
        """
        获取当前任务。

        :return: Task 实例，无任务时返回 None
        """
        if not self.tasks:
            return None
        # 防御性裁剪，避免外部修改 tasks 后游标越界
        idx = min(self.current_task_index, len(self.tasks) - 1)
        return self.tasks[idx]

    def get_current_event(self):
        """
        获取当前事件。

        :return: Event 实例，无当前事件时返回 None
        """
        task = self.get_current_task()
        if task is None or not task.events:
            return None
        idx = min(self.current_event_index, len(task.events) - 1)
        return task.events[idx]

    # ------------------------------------------------------------------
    # 游标控制
    # ------------------------------------------------------------------
    def advance(self):
        """
        前进到下一个事件。

        按事件 -> 任务 -> 序列结束的层级推进：
        1. 当前任务还有下一个事件，则事件下标 +1；
        2. 当前任务事件已遍历完，则切换到下一个任务并定位到该任务第 0 个事件；
           若新任务为空则继续跳过，直到遇到非空任务或序列结束；
        3. 所有任务遍历完成，返回 False 表示序列结束。

        :return: bool，True 表示成功前进到下一个事件，False 表示序列已结束
        """
        while True:
            if not self.tasks:
                return False
            task = self.get_current_task()
            if task is None:
                return False
            # 当前任务内仍有下一个事件
            if self.current_event_index < len(task.events) - 1:
                self.current_event_index += 1
                return True
            # 当前任务已遍历完，尝试切换到下一个任务
            if self.current_task_index < len(self.tasks) - 1:
                self.current_task_index += 1
                self.current_event_index = 0
                # 新任务有事件则定位成功；空任务则继续跳过
                if len(self.tasks[self.current_task_index].events) > 0:
                    return True
                continue
            # 所有任务遍历完成
            return False

    def reset(self):
        """
        重置游标到序列起始位置。

        :return: bool，始终返回 True
        """
        self.current_task_index = 0
        self.current_event_index = 0
        return True

    def is_finished(self):
        """
        判断序列是否已遍历完成（不推进游标）。

        :return: bool
        """
        if not self.tasks:
            return True
        task = self.get_current_task()
        if task is None:
            return True
        # 处于最后一个任务的最后一个事件
        return (self.current_task_index == len(self.tasks) - 1 and
                self.current_event_index >= len(task.events) - 1)

    # ------------------------------------------------------------------
    # 序列化 / 反序列化
    # ------------------------------------------------------------------
    def to_dict(self):
        """序列化为字典。"""
        return {
            "id": self.id,
            "name": self.name,
            "tasks": [t.to_dict() for t in self.tasks],
            "current_task_index": self.current_task_index,
            "current_event_index": self.current_event_index,
            "loop_count": self.loop_count,
            "loop_delay": self.loop_delay,
        }

    @classmethod
    def from_dict(cls, d):
        """从字典创建 TaskSequence 实例。"""
        if not isinstance(d, dict):
            raise TypeError(f"from_dict 需要字典参数，收到 {type(d).__name__}")
        return cls(
            id=d.get("id"),
            name=d.get("name", ""),
            tasks=d.get("tasks", []),
            current_task_index=d.get("current_task_index", 0),
            current_event_index=d.get("current_event_index", 0),
            loop_count=d.get("loop_count", 1),
            loop_delay=d.get("loop_delay", 1.0),
        )

    def to_json(self, indent=None):
        """序列化为 JSON 字符串。"""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    @classmethod
    def from_json(cls, s):
        """从 JSON 字符串创建 TaskSequence 实例。"""
        if isinstance(s, (bytes, bytearray)):
            s = s.decode("utf-8")
        return cls.from_dict(json.loads(s))

    # ------------------------------------------------------------------
    # 文件持久化
    # ------------------------------------------------------------------
    def save(self, filepath):
        """
        保存任务序列到 JSON 文件。

        :param str filepath: 文件路径，可为相对路径（相对项目根目录）
        :return: bool，是否保存成功
        """
        filepath = self._resolve_path(filepath)
        try:
            parent = os.path.dirname(filepath)
            if parent:
                ensure_dir(parent)
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
            logger.info(f"任务序列已保存: {filepath}")
            return True
        except (OSError, TypeError, ValueError) as e:
            logger.error(f"保存任务序列失败 {filepath}: {e}")
            return False

    @classmethod
    def load(cls, filepath):
        """
        从 JSON 文件加载任务序列。

        :param str filepath: 文件路径，可为相对路径（相对项目根目录）
        :return: TaskSequence 实例，加载失败返回 None
        """
        filepath = cls._resolve_path(filepath)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            return cls.from_dict(data)
        except (OSError, json.JSONDecodeError) as e:
            logger.error(f"加载任务序列失败 {filepath}: {e}")
            return None

    @staticmethod
    def _resolve_path(filepath):
        """解析文件路径：相对路径相对项目根目录解析。"""
        if not filepath:
            return filepath
        if os.path.isabs(filepath):
            return filepath
        # 项目根目录：当前文件的上两级（models/task_sequence.py -> models -> 项目根）
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(project_root, filepath)

    # ------------------------------------------------------------------
    # 其他
    # ------------------------------------------------------------------
    def __repr__(self):
        return (f"TaskSequence(id={self.id[:8]}, name={self.name!r}, "
                f"tasks={len(self.tasks)}, pos=({self.current_task_index},"
                f"{self.current_event_index}))")

    def __len__(self):
        return len(self.tasks)

    def __iter__(self):
        return iter(self.tasks)
