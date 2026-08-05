# -*- coding: utf-8 -*-
"""
任务模型模块。

定义 Task 类，表示一个完整任务（由若干 Event 组成的有序序列）。
支持事件增删、上下移动、序列化、持久化到 JSON 文件等操作。
"""
from __future__ import annotations

from typing import Optional

import os
import json
import uuid

from utils.helpers import get_timestamp, ensure_dir
from utils.logger import logger
from models.event import Event
from models.var_context import VarContext


class Task:
    """
    任务模型：一组有序事件的集合。

    :ivar str id: 任务唯一标识（UUID 字符串）
    :ivar str name: 任务名称
    :ivar str description: 任务描述
    :ivar list[Event] events: 事件列表（按执行顺序）
    :ivar int loop_count: 循环次数，0 表示无限循环，默认 1
    :ivar float loop_delay: 循环间隔（秒），默认 1.0
    :ivar str created_at: 创建时间字符串
    :ivar str updated_at: 更新时间字符串
    """

    def __init__(self, name: str = "", description: str = "",
                 events: Optional[list[Event]] = None,
                 loop_count: int = 1, loop_delay: float = 1.0,
                 created_at: Optional[str] = None,
                 updated_at: Optional[str] = None,
                 id: Optional[str] = None) -> None:
        """
        构造一个任务。

        :param name: 任务名称
        :param description: 任务描述
        :param events: 事件列表，元素可为 Event 实例或字典
        :param loop_count: 循环次数（0=无限）
        :param loop_delay: 循环间隔（秒）
        :param created_at: 创建时间，未指定则取当前时间
        :param updated_at: 更新时间，未指定则取当前时间
        :param id: 指定 ID，未指定时自动生成
        """
        now = get_timestamp("%Y-%m-%d %H:%M:%S")
        self.id = id if id else str(uuid.uuid4())
        self.name = name if name else ""
        self.description = description if description else ""
        # 事件列表：兼容传入 Event 实例或字典，统一转为 Event
        self.events = []
        if events:
            for e in events:
                self.events.append(self._coerce_event(e))
        # 循环次数：负数视为 1
        self.loop_count = max(0, int(loop_count)) if loop_count is not None else 1
        self.loop_delay = float(loop_delay) if loop_delay is not None else 1.0
        self.created_at = created_at if created_at else now
        self.updated_at = updated_at if updated_at else now
        # 变量上下文
        self.var_context = VarContext()

    @staticmethod
    def _coerce_event(e):
        """
        将传入对象统一转换为 Event 实例。

        :param e: Event 实例或字典
        :return: Event 实例
        """
        if isinstance(e, Event):
            return e
        if isinstance(e, dict):
            return Event.from_dict(e)
        raise TypeError(f"事件类型不合法，期望 Event 或 dict，收到 {type(e).__name__}")

    def _touch(self):
        """更新 updated_at 时间戳，供内部修改操作调用。"""
        self.updated_at = get_timestamp("%Y-%m-%d %H:%M:%S")

    # ------------------------------------------------------------------
    # 事件管理
    # ------------------------------------------------------------------
    def add_event(self, event):
        """
        添加事件到末尾。

        :param event: Event 实例或字典
        :return: 添加后的 Event 实例
        """
        ev = self._coerce_event(event)
        self.events.append(ev)
        self._touch()
        return ev

    def remove_event(self, event_id):
        """
        按 ID 删除事件。

        :param str event_id: 事件 ID
        :return: bool，是否删除成功
        """
        for i, ev in enumerate(self.events):
            if ev.id == event_id:
                self.events.pop(i)
                self._touch()
                return True
        logger.warning(f"未找到要移除的事件: id={event_id}, 任务={self.name}")
        return False

    def move_event(self, event_id, direction="up"):
        """
        上移或下移事件，调整执行顺序。

        :param str event_id: 事件 ID
        :param str direction: "up" 上移 / "down" 下移
        :return: bool，是否移动成功
        """
        direction = (direction or "").lower()
        if direction not in ("up", "down"):
            logger.warning(f"非法移动方向: {direction}（仅支持 'up'/'down'）")
            return False
        # 定位事件下标
        idx = -1
        for i, ev in enumerate(self.events):
            if ev.id == event_id:
                idx = i
                break
        if idx < 0:
            logger.warning(f"未找到要移动的事件: id={event_id}, 任务={self.name}")
            return False
        if direction == "up" and idx > 0:
            target = idx - 1
        elif direction == "down" and idx < len(self.events) - 1:
            target = idx + 1
        else:
            # 已到边界，无需移动
            return False
        # 交换位置
        self.events[idx], self.events[target] = self.events[target], self.events[idx]
        self._touch()
        return True

    def get_event_by_id(self, event_id):
        """
        按 ID 查找事件。

        :param str event_id: 事件 ID
        :return: Event 实例，未找到返回 None
        """
        for ev in self.events:
            if ev.id == event_id:
                return ev
        return None

    def get_event_index(self, event_id):
        """
        按 ID 查找事件下标。

        :param str event_id: 事件 ID
        :return: 下标，未找到返回 -1
        """
        for i, ev in enumerate(self.events):
            if ev.id == event_id:
                return i
        return -1

    # ------------------------------------------------------------------
    # 序列化 / 反序列化
    # ------------------------------------------------------------------
    def to_dict(self):
        """序列化为字典。"""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "events": [e.to_dict() for e in self.events],
            "loop_count": self.loop_count,
            "loop_delay": self.loop_delay,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d):
        """从字典创建 Task 实例。"""
        if not isinstance(d, dict):
            raise TypeError(f"from_dict 需要字典参数，收到 {type(d).__name__}")
        # events 字段可能是字典列表，构造时会自动转换
        return cls(
            id=d.get("id"),
            name=d.get("name", ""),
            description=d.get("description", ""),
            events=d.get("events", []),
            loop_count=d.get("loop_count", 1),
            loop_delay=d.get("loop_delay", 1.0),
            created_at=d.get("created_at"),
            updated_at=d.get("updated_at"),
        )

    def to_json(self, indent=None):
        """序列化为 JSON 字符串。"""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    @classmethod
    def from_json(cls, s):
        """从 JSON 字符串创建 Task 实例。"""
        if isinstance(s, (bytes, bytearray)):
            s = s.decode("utf-8")
        return cls.from_dict(json.loads(s))

    # ------------------------------------------------------------------
    # 文件持久化
    # ------------------------------------------------------------------
    def save(self, filepath):
        """
        保存任务到 JSON 文件。

        :param str filepath: 文件路径，可为相对路径（相对项目根目录）
        :return: bool，是否保存成功
        """
        filepath = self._resolve_path(filepath)
        try:
            # 确保父目录存在
            parent = os.path.dirname(filepath)
            if parent:
                ensure_dir(parent)
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
            logger.info(f"任务已保存: {filepath}")
            return True
        except (OSError, TypeError, ValueError) as e:
            logger.error(f"保存任务失败 {filepath}: {e}")
            return False

    @classmethod
    def load(cls, filepath):
        """
        从 JSON 文件加载任务。

        :param str filepath: 文件路径，可为相对路径（相对项目根目录）
        :return: Task 实例，加载失败返回 None
        """
        filepath = cls._resolve_path(filepath)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            return cls.from_dict(data)
        except (OSError, json.JSONDecodeError) as e:
            logger.error(f"加载任务失败 {filepath}: {e}")
            return None

    @staticmethod
    def _resolve_path(filepath):
        """
        解析文件路径：相对路径相对项目根目录解析。

        :param filepath: 输入路径
        :return: 绝对路径
        """
        if not filepath:
            return filepath
        if os.path.isabs(filepath):
            return filepath
        # 项目根目录：当前文件的上两级（models/task.py -> models -> 项目根）
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(project_root, filepath)

    # ------------------------------------------------------------------
    # 其他
    # ------------------------------------------------------------------
    def __repr__(self):
        return (f"Task(id={self.id[:8]}, name={self.name!r}, "
                f"events={len(self.events)}, loop={self.loop_count})")

    def __len__(self):
        return len(self.events)

    def __iter__(self):
        return iter(self.events)
