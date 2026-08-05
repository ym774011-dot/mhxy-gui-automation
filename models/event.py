# -*- coding: utf-8 -*-
"""
事件模型模块。

定义 EventType（事件类型常量）与 Event（单个操作事件）。
Event 表示任务序列中的一个原子操作，例如鼠标点击、键盘输入、
图像识别、YOLO 检测、函数调用、条件分支等。

支持序列化为字典 / JSON 字符串，便于持久化与界面交互。
"""
import json
import uuid
from typing import Dict, List, Optional, Any
from enum import Enum


class EventType(str, Enum):
    """
    事件类型常量。

    通过类属性集中管理所有事件类型字符串，避免散落在代码各处造成拼写错误。
    每个常量与 Event.params 的结构存在一一映射。
    """
    CLICK = "click"           # 鼠标点击
    KEY = "key"               # 键盘输入
    WAIT = "wait"             # 等待延迟
    IMAGE = "image"           # 图像识别
    YOLO = "yolo"             # YOLO 检测
    FUNCTION = "function"    # 函数调用
    CONDITION = "condition"   # 条件分支

    @classmethod
    def all(cls) -> List[str]:
        """返回所有合法的事件类型列表，便于校验。"""
        return [e.value for e in cls]

    @classmethod
    def is_valid(cls, event_type: str) -> bool:
        """判断给定字符串是否为合法事件类型。"""
        return event_type in cls.all()


class Event:
    """
    单个操作事件。

    :ivar str id: 事件唯一标识（UUID 字符串，自动生成）
    :ivar str name: 事件名称（用户可读）
    :ivar str event_type: 事件类型，取值见 EventType
    :ivar dict params: 事件参数字典，结构随 event_type 不同而不同
    :ivar float pre_delay: 执行前延迟（秒），默认 0
    :ivar float post_delay: 执行后延迟（秒），默认 0.5
    :ivar str on_error: 错误处理策略："retry" / "skip" / "stop"，默认 "skip"
    :ivar int max_retries: 最大重试次数，默认 3
    :ivar float retry_interval: 重试间隔（秒），默认 1.0
    :ivar bool enabled: 是否启用，默认 True

    各事件类型对应的 params 结构::

        click:      {"x": int, "y": int,
                     "button": "left"/"right"/"double", "background": bool}
        key:        {"keys": "alt+q", "text": "", "duration": float}
        wait:       {"duration": float, "wait_for_image": bool,
                     "image_path": "", "timeout": float}
        image:      {"template_path": "", "threshold": 0.8,
                     "action": "click"/"wait"/"record", "region": [x,y,w,h]}
        yolo:       {"target_class": "", "confidence": 0.5,
                     "action": "click"/"record", "model_path": ""}
        function:   {"module": "", "function": "", "args": [], "kwargs": {}}
        condition:  {"variable": "", "operator": "==" / "!=" / ">" / "<",
                     "value": any, "true_branch": [], "false_branch": []}
    """

    # 类属性类型注解
    id: str
    name: str
    event_type: str
    params: Dict[str, Any]
    pre_delay: float
    post_delay: float
    on_error: str
    max_retries: int
    retry_interval: float
    enabled: bool
    var_name: str

    # 合法的错误处理策略
    _VALID_ON_ERROR = ("retry", "skip", "stop")

    def __init__(
        self,
        name: str = "",
        event_type: str = EventType.CLICK,
        params: Optional[Dict[str, Any]] = None,
        pre_delay: float = 0.0,
        post_delay: float = 0.5,
        on_error: str = "skip",
        max_retries: int = 3,
        retry_interval: float = 1.0,
        enabled: bool = True,
        id: Optional[str] = None,
        var_name: str = ""
    ) -> None:
        """
        构造一个事件。

        :param name: 事件名称
        :param event_type: 事件类型（EventType 常量）
        :param params: 事件参数字典，为 None 时使用空字典
        :param pre_delay: 执行前延迟（秒）
        :param post_delay: 执行后延迟（秒）
        :param on_error: 错误处理策略
        :param max_retries: 最大重试次数
        :param retry_interval: 重试间隔（秒）
        :param enabled: 是否启用
        :param id: 指定 ID，未指定时自动生成 UUID
        :param var_name: 变量别名，用于在后续事件中通过 ${var_name.field} 引用结果
        """
        # ID：允许显式传入（用于反序列化），否则自动生成
        self.id = id if id else str(uuid.uuid4())
        self.name = name if name else ""
        # 变量名：用于在变量上下文中引用该事件的结果
        # 默认取事件名（去除空格），用户可自定义
        self.var_name = var_name if var_name else (name or "").replace(" ", "").replace("_", "")
        # 事件类型校验：非法类型降级为 CLICK，避免后续逻辑崩溃
        if EventType.is_valid(event_type):
            self.event_type = event_type
        else:
            self.event_type = EventType.CLICK
        # params 强制为字典，避免可变默认参数陷阱
        self.params = dict(params) if params else {}
        # 数值类参数做类型容错
        self.pre_delay = float(pre_delay) if pre_delay is not None else 0.0
        self.post_delay = float(post_delay) if post_delay is not None else 0.5
        # 错误策略校验：非法值降级为 "skip"
        self.on_error = on_error if on_error in self._VALID_ON_ERROR else "skip"
        self.max_retries = int(max_retries) if max_retries is not None else 3
        self.retry_interval = float(retry_interval) if retry_interval is not None else 1.0
        self.enabled = bool(enabled)

    # ------------------------------------------------------------------
    # 序列化 / 反序列化
    # ------------------------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        """
        序列化为字典。

        :return: 包含所有字段的字典，可直接 json.dump
        """
        return {
            "id": self.id,
            "name": self.name,
            "event_type": self.event_type,
            "params": self.params,
            "pre_delay": self.pre_delay,
            "post_delay": self.post_delay,
            "on_error": self.on_error,
            "max_retries": self.max_retries,
            "retry_interval": self.retry_interval,
            "enabled": self.enabled,
            "var_name": self.var_name,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> 'Event':
        """
        从字典创建 Event 实例。

        :param dict d: 字典数据
        :return: Event 实例
        """
        if not isinstance(d, dict):
            raise TypeError(f"from_dict 需要字典参数，收到 {type(d).__name__}")
        # 使用 get + 默认值，保证缺失字段也能正常构造
        return cls(
            id=d.get("id"),
            name=d.get("name", ""),
            event_type=d.get("event_type", EventType.CLICK),
            params=d.get("params", {}),
            pre_delay=d.get("pre_delay", 0.0),
            post_delay=d.get("post_delay", 0.5),
            on_error=d.get("on_error", "skip"),
            max_retries=d.get("max_retries", 3),
            retry_interval=d.get("retry_interval", 1.0),
            enabled=d.get("enabled", True),
            var_name=d.get("var_name", ""),
        )

    def to_json(self, indent: Optional[int] = None) -> str:
        """
        序列化为 JSON 字符串。

        :param indent: 缩进格数，None 表示紧凑输出
        :return: JSON 字符串
        """
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    @classmethod
    def from_json(cls, s: str) -> 'Event':
        """
        从 JSON 字符串创建 Event 实例。

        :param s: JSON 字符串
        :return: Event 实例
        """
        if isinstance(s, (bytes, bytearray)):
            s = s.decode("utf-8")
        return cls.from_dict(json.loads(s))

    # ------------------------------------------------------------------
    # 其他
    # ------------------------------------------------------------------
    def __repr__(self) -> str:
        """简洁描述，便于调试输出。"""
        return (f"Event(id={self.id[:8]}, name={self.name!r}, "
                f"type={self.event_type}, enabled={self.enabled})")

    def __eq__(self, other: object) -> bool:
        """按 ID 判断相等，便于在列表中查找/移除。"""
        if isinstance(other, Event):
            return self.id == other.id
        return False

    def __hash__(self) -> int:
        """按 ID 哈希，配合 __eq__ 使用。"""
        return hash(self.id)
