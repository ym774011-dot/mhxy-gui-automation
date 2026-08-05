# -*- coding: utf-8 -*-
"""
位置数据容器模块。

提供 LocationDataContainer 类，用于管理任务执行过程中的地图位置数据。
支持自动解析函数调用返回的 "地图名 x，y" 格式数据，分离场景名称和坐标值。

特性：
- 自动解析 "江南野外 145，35" 格式数据
- 支持跨事件访问位置数据
- 任务完成后统一清理
- 线程安全的读写操作
"""
import re
import threading
from typing import Any, Dict, List, Optional, Tuple

from utils.logger import logger


class LocationDataContainer:
    """
    位置数据容器类。

    存储任务执行过程中获取的地图位置信息，支持自动解析
    "地图名 x，y" 格式的数据。

    数据结构：
    {
        "地图名": {
            "location": "地图名",
            "x": 145,
            "y": 35,
            "raw": "江南野外 145，35"
        }
    }

    :ivar Dict[str, Dict[str, Any]] _locations: 位置数据存储
    :ivar threading.Lock _lock: 线程锁
    :ivar List[str] _supported_maps: 支持的地图列表
    """

    def __init__(self, supported_maps: Optional[List[str]] = None) -> None:
        """
        初始化位置数据容器。

        :param Optional[List[str]] supported_maps: 支持的地图名称列表
        """
        self._locations: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._supported_maps = supported_maps or [
            "江南野外", "建邺城", "东海湾"
        ]

    # ==================================================================
    # 核心解析方法
    # ==================================================================
    def parse_location_string(self, text: str) -> Optional[Dict[str, Any]]:
        """
        解析位置字符串，分离地图名和坐标。

        支持格式：
        - "江南野外 145，35"
        - "江南野外 145,35"
        - "江南野外 145 35"
        - "145，35"（无地图名时使用默认地图）

        :param str text: 位置字符串
        :return: 解析结果字典 {"location", "x", "y", "raw"} 或 None
        """
        if not text or not isinstance(text, str):
            return None

        text = text.strip()

        # 尝试匹配 "地图名 x，y" 格式
        # 支持全角逗号 ， 和半角逗号 , 以及空格分隔
        pattern = r'^(.+?)\s+(\d+)\s*[，,]\s*(\d+)$'
        match = re.match(pattern, text)

        if match:
            location = match.group(1).strip()
            try:
                x = int(match.group(2))
                y = int(match.group(3))
                return {
                    "location": location,
                    "x": x,
                    "y": y,
                    "raw": text,
                }
            except (ValueError, IndexError):
                pass

        # 尝试匹配纯坐标格式 "x，y"
        coord_pattern = r'^(\d+)\s*[，,]\s*(\d+)$'
        coord_match = re.match(coord_pattern, text)
        if coord_match:
            try:
                x = int(coord_match.group(1))
                y = int(coord_match.group(2))
                return {
                    "location": "",
                    "x": x,
                    "y": y,
                    "raw": text,
                }
            except (ValueError, IndexError):
                pass

        logger.debug(f"无法解析位置字符串: {text}")
        return None

    def extract_location_from_result(
        self, result: Any, field_name: str = "target_location"
    ) -> Optional[Dict[str, Any]]:
        """
        从函数调用结果中提取位置信息。

        支持的结果格式：
        - {"target_location": "江南野外 145，35"}
        - "江南野外 145，35"（纯字符串）
        - {"target_location": "江南野外", "target_coord": [145, 35]}
        - {"location": "江南野外 145，35"}

        :param Any result: 函数调用结果
        :param str field_name: 包含位置信息的字段名
        :return: 解析结果字典或 None
        """
        if result is None:
            return None

        # 处理纯字符串结果
        if isinstance(result, str):
            return self.parse_location_string(result)

        # 处理字典结果
        if isinstance(result, dict):
            # 优先从指定字段解析
            if field_name in result:
                field_value = result[field_name]
                if isinstance(field_value, str):
                    parsed = self.parse_location_string(field_value)
                    if parsed:
                        return parsed

            # 尝试从 location 字段解析
            if "location" in result:
                location_value = result["location"]
                if isinstance(location_value, str):
                    parsed = self.parse_location_string(location_value)
                    if parsed:
                        return parsed

            # 处理分离的坐标格式
            location = result.get("target_location", "") or result.get("location", "")
            target_coord = result.get("target_coord", []) or result.get("coord", [])

            if location and target_coord and isinstance(target_coord, (list, tuple)):
                try:
                    x = int(target_coord[0])
                    y = int(target_coord[1]) if len(target_coord) > 1 else 0
                    return {
                        "location": str(location),
                        "x": x,
                        "y": y,
                        "raw": f"{location} {x}，{y}",
                    }
                except (ValueError, IndexError, TypeError):
                    pass

        return None

    # ==================================================================
    # 存储操作
    # ==================================================================
    def store_location(
        self,
        location: str,
        x: int,
        y: int,
        raw: str = "",
    ) -> Dict[str, Any]:
        """
        存储位置数据。

        :param str location: 地图名称
        :param int x: X 坐标
        :param int y: Y 坐标
        :param str raw: 原始字符串
        :return: 存储的数据字典
        """
        with self._lock:
            key = location.strip()
            data = {
                "location": key,
                "x": x,
                "y": y,
                "raw": raw,
            }
            self._locations[key] = data
            logger.debug(f"存储位置数据: {key} ({x}, {y})")
            return data

    def store_from_string(self, text: str) -> Optional[Dict[str, Any]]:
        """
        从字符串解析并存储位置数据。

        :param str text: 位置字符串，如 "江南野外 145，35"
        :return: 存储的数据字典或 None
        """
        parsed = self.parse_location_string(text)
        if parsed:
            return self.store_location(
                parsed["location"], parsed["x"], parsed["y"], parsed["raw"]
            )
        return None

    def store_from_result(
        self, result: Any, field_name: str = "target_location"
    ) -> Optional[Dict[str, Any]]:
        """
        从函数调用结果提取并存储位置数据。

        :param Any result: 函数调用结果
        :param str field_name: 包含位置信息的字段名
        :return: 存储的数据字典或 None
        """
        parsed = self.extract_location_from_result(result, field_name)
        if parsed and parsed["location"]:
            return self.store_location(
                parsed["location"], parsed["x"], parsed["y"], parsed["raw"]
            )
        return None

    # ==================================================================
    # 查询操作
    # ==================================================================
    def get_location(self, location: str) -> Optional[Dict[str, Any]]:
        """
        获取指定地图的位置数据。

        :param str location: 地图名称
        :return: 位置数据字典或 None
        """
        with self._lock:
            return self._locations.get(location.strip())

    def get_coordinates(self, location: str) -> Optional[Tuple[int, int]]:
        """
        获取指定地图的坐标。

        :param str location: 地图名称
        :return: (x, y) 元组或 None
        """
        data = self.get_location(location)
        if data:
            return (data["x"], data["y"])
        return None

    def get_all_locations(self) -> Dict[str, Dict[str, Any]]:
        """
        获取所有位置数据。

        :return: 所有位置数据的副本
        """
        with self._lock:
            return dict(self._locations)

    def get_locations_list(self) -> List[Dict[str, Any]]:
        """
        获取所有位置数据列表。

        :return: 位置数据列表
        """
        with self._lock:
            return list(self._locations.values())

    def has_location(self, location: str) -> bool:
        """
        检查指定地图是否存在。

        :param str location: 地图名称
        :return: 是否存在
        """
        with self._lock:
            return location.strip() in self._locations

    def get_location_count(self) -> int:
        """
        获取存储的位置数量。

        :return: 位置数量
        """
        with self._lock:
            return len(self._locations)

    # ==================================================================
    # 清理操作
    # ==================================================================
    def clear_location(self, location: str) -> bool:
        """
        删除指定地图的位置数据。

        :param str location: 地图名称
        :return: 是否删除成功
        """
        with self._lock:
            key = location.strip()
            if key in self._locations:
                del self._locations[key]
                logger.debug(f"删除位置数据: {key}")
                return True
            return False

    def clear_all(self) -> None:
        """清空所有位置数据。"""
        with self._lock:
            count = len(self._locations)
            self._locations.clear()
            if count > 0:
                logger.info(f"清空所有位置数据: {count} 条记录")

    # ==================================================================
    # 批量操作
    # ==================================================================
    def update_from_dict(self, data: Dict[str, Dict[str, Any]]) -> None:
        """
        从字典批量更新位置数据。

        :param Dict[str, Dict[str, Any]] data: 位置数据字典
        """
        with self._lock:
            for key, value in data.items():
                if isinstance(value, dict):
                    self._locations[key] = value

    def merge(self, other: "LocationDataContainer") -> None:
        """
        合并另一个容器的数据。

        :param LocationDataContainer other: 另一个容器实例
        """
        other_data = other.get_all_locations()
        self.update_from_dict(other_data)

    # ==================================================================
    # 支持的地图管理
    # ==================================================================
    def get_supported_maps(self) -> List[str]:
        """
        获取支持的地图列表。

        :return: 地图名称列表
        """
        return list(self._supported_maps)

    def add_supported_map(self, map_name: str) -> None:
        """
        添加支持的地图。

        :param str map_name: 地图名称
        """
        if map_name and map_name not in self._supported_maps:
            self._supported_maps.append(map_name)

    def set_supported_maps(self, maps: List[str]) -> None:
        """
        设置支持的地图列表。

        :param List[str] maps: 地图名称列表
        """
        self._supported_maps = list(maps) if maps else []

    # ==================================================================
    # 工具方法
    # ==================================================================
    def to_dict(self) -> Dict[str, Any]:
        """
        导出为字典。

        :return: 容器数据字典
        """
        return {
            "locations": self.get_all_locations(),
            "supported_maps": self.get_supported_maps(),
            "count": self.get_location_count(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LocationDataContainer":
        """
        从字典创建实例。

        :param Dict[str, Any] data: 数据字典
        :return: LocationDataContainer 实例
        """
        container = cls(data.get("supported_maps", None))
        container.update_from_dict(data.get("locations", {}))
        return container

    def __repr__(self) -> str:
        """返回字符串表示。"""
        with self._lock:
            locations_list = list(self._locations.keys())
            return (
                f"LocationDataContainer("
                f"count={len(self._locations)}, "
                f"locations={locations_list}"
                f")"
            )

    def __len__(self) -> int:
        """返回存储的位置数量。"""
        return self.get_location_count()


# ==========================================================================
# 全局容器单例管理
# ==========================================================================
_global_container: Optional[LocationDataContainer] = None
_global_container_lock = threading.Lock()


def get_global_location_container() -> LocationDataContainer:
    """
    获取全局位置数据容器单例。

    :return: LocationDataContainer 实例
    """
    global _global_container
    if _global_container is None:
        with _global_container_lock:
            if _global_container is None:
                _global_container = LocationDataContainer()
    return _global_container


def reset_global_location_container(
    supported_maps: Optional[List[str]] = None,
) -> LocationDataContainer:
    """
    重置全局位置数据容器（任务开始时调用）。

    :param Optional[List[str]] supported_maps: 支持的地图列表
    :return: 新的 LocationDataContainer 实例
    """
    global _global_container
    with _global_container_lock:
        _global_container = LocationDataContainer(supported_maps)
    return _global_container


def clear_global_location_container() -> None:
    """
    清空全局位置数据容器（任务结束时调用）。
    """
    global _global_container
    if _global_container is not None:
        _global_container.clear_all()
