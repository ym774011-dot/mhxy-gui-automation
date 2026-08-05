# -*- coding: utf-8 -*-
"""
变量上下文管理模块。

提供 VarContext 类，用于管理任务执行过程中的变量存储和模板替换。
支持基础变量操作、嵌套访问和模板替换功能。
"""
import re
from typing import Any, Dict, Optional


class VarContext:
    """
    变量上下文管理类。

    管理任务执行过程中的变量存储，支持模板替换和嵌套访问。

    :ivar Dict[str, Any] _variables: 内部变量存储字典
    """

    def __init__(self) -> None:
        """初始化变量上下文。"""
        self._variables: Dict[str, Any] = {}

    def set(self, key: str, value: Any) -> None:
        """
        设置变量值。

        :param str key: 变量名
        :param Any value: 变量值
        """
        self._variables[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        """
        获取变量值，支持嵌套访问。

        支持使用点号分隔的嵌套访问，如 "result.target_coord.0"。

        :param str key: 变量名（支持嵌套访问）
        :param Any default: 默认值，变量不存在时返回
        :return: 变量值或默认值
        """
        # 分割嵌套路径
        parts = key.split(".")
        current = self._variables

        # 逐层访问
        for part in parts:
            if isinstance(current, dict):
                if part not in current:
                    return default
                current = current[part]
            elif isinstance(current, (list, tuple)):
                try:
                    index = int(part)
                    current = current[index]
                except (ValueError, IndexError):
                    return default
            else:
                return default

        return current

    def update(self, key: str, value: Any) -> None:
        """
        更新变量值（等同于 set）。

        :param str key: 变量名
        :param Any value: 新变量值
        """
        self.set(key, value)

    def clear(self, key: Optional[str] = None) -> None:
        """
        清空变量。

        :param Optional[str] key: 变量名，为 None 时清空所有变量
        """
        if key is None:
            self._variables.clear()
        elif key in self._variables:
            del self._variables[key]

    def replace(self, template: str) -> str:
        """
        替换模板中的变量引用。

        支持 ${var} 格式的变量引用，支持嵌套访问。

        :param str template: 模板字符串
        :return: 替换后的字符串
        """
        # 匹配 ${var} 格式的变量引用
        pattern = r'\$\{([^}]+)\}'

        def replacer(match):
            var_name = match.group(1).strip()
            value = self.get(var_name)
            if value is None:
                # 变量不存在，保持原样
                return match.group(0)
            return str(value)

        return re.sub(pattern, replacer, template)

    def replace_variables(self, template: str) -> str:
        """
        替换模板中的变量引用（replace 方法的别名）。

        :param str template: 模板字符串
        :return: 替换后的字符串
        """
        return self.replace(template)

    def __contains__(self, key: str) -> bool:
        """
        检查变量是否存在。

        :param str key: 变量名
        :return: 变量是否存在
        """
        return key in self._variables

    def __len__(self) -> int:
        """
        返回变量数量。

        :return: 变量数量
        """
        return len(self._variables)

    def __repr__(self) -> str:
        """返回字符串表示。"""
        return f"VarContext(variables={len(self._variables)})"