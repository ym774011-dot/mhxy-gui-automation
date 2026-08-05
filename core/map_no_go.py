# -*- coding: utf-8 -*-
"""
地图禁区规避 —— 防止角色走到传送热点/陷阱坐标。

背景（2026-08-05 用户反馈）：
    任务 NPC 站在地图切换传送点上（如建邺城江湖大盗 (171,109)），
    角色走到该坐标会先触发跨图传送，而不是 NPC 对话。

方案：
    用户在 `data/map_no_go_zones.json` 维护每个地图的禁区表，
    地图函数调用前自动把目标坐标修正到禁区外最近的安全点。

数据格式（data/map_no_go_zones.json）::

    {
      "建邺城": [
        {"name": "传送热点", "x": 171, "y": 109, "radius": 3},        # 圆形
        {"name": "陷阱区", "x1": 100, "y1": 50, "x2": 110, "y2": 60}  # 矩形
      ]
    }
"""
from __future__ import annotations

import json
import os
import time
from typing import Dict, List, Optional, Tuple

from utils.logger import logger

# 模块名 → 地图名（与 地图数据/*.py 的 title 一致）
MODULE_MAP_NAME = {
    "JYC": "建邺城",
    "JNYW": "江南野外",
    "DHW": "东海湾",
    "CAC": "长安城",
    "ALG": "傲来国",
    "BXG": "宝象国",
    "CSC": "长寿村",
    "XLNR": "西凉女国",
    "ZZG": "朱紫国",
}

_ZONES_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "data", "map_no_go_zones.json"
)

# 运行时缓存（避免每次调用都读盘；文件更新后调用 reload_zones 刷新）
_cache: Optional[Dict[str, List[dict]]] = None
_cache_mtime: float = 0.0


def _load_zones() -> Dict[str, List[dict]]:
    """读取禁区表（带 mtime 缓存，文件变化自动重载）。"""
    global _cache, _cache_mtime
    try:
        mtime = os.path.getmtime(_ZONES_PATH)
        if _cache is not None and mtime == _cache_mtime:
            return _cache
        with open(_ZONES_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        # 去掉 "_" 开头的说明键
        zones = {k: v for k, v in data.items() if not k.startswith("_")}
        _cache = zones
        _cache_mtime = mtime
        return zones
    except Exception as e:
        logger.warning(f"读取禁区表失败: {e}")
        return {}


def reload_zones() -> None:
    """强制重载禁区表（GUI 保存配置后调用）。"""
    global _cache, _cache_mtime
    _cache = None
    _cache_mtime = 0.0
    _load_zones()


def _in_zone_circle(zone: dict, gx: float, gy: float) -> bool:
    r = float(zone.get("radius", 3))
    dx = gx - float(zone["x"])
    dy = gy - float(zone["y"])
    return dx * dx + dy * dy <= r * r


def _in_zone_rect(zone: dict, gx: float, gy: float) -> bool:
    return (
        float(zone["x1"]) <= gx <= float(zone["x2"])
        and float(zone["y1"]) <= gy <= float(zone["y2"])
    )


def is_in_no_go_zone(
    map_name: str, gx: float, gy: float
) -> Tuple[bool, Optional[dict]]:
    """判断坐标是否在任何禁区内。

    :return: (是否在禁区, 命中的禁区 dict 或 None)
    """
    zones = _load_zones()
    for zone in zones.get(map_name, []):
        if "radius" in zone:
            if _in_zone_circle(zone, gx, gy):
                return True, zone
        elif "x1" in zone:
            if _in_zone_rect(zone, gx, gy):
                return True, zone
    return False, None


def resolve_safe_coord(
    map_name: str, gx: float, gy: float, max_ring: int = 8
) -> Tuple[float, float, bool]:
    """把目标坐标修正到禁区外最近的安全点。

    策略（用户 2026-08-05 规则）：
      1. 命中禁区且该禁区声明了 ``fix: [dx, dy]`` → 先按 fix 偏移
         （如建邺城统一 [-5,-5]，X-5,Y-5 再点击）；
      2. 若 fix 修正后仍落在其它禁区（重叠区），回退到螺旋搜索
         从禁区边界向外逐圈扩散找第一个安全点；
      3. 无 fix 字段的禁区 → 直接螺旋搜索。

    :param map_name: 地图名（如 '建邺城'）
    :param gx, gy: 原始目标坐标
    :param max_ring: 最大扩散圈数（默认 8，约 8 格 = 够避开小传送点）
    :return: (安全x, 安全y, 是否被修正过)
    """
    hit, zone = is_in_no_go_zone(map_name, gx, gy)
    if not hit:
        return float(gx), float(gy), False

    # 1) 禁区声明了 fix 偏移 → 优先用（用户规则：X-5, Y-5）
    fix = zone.get("fix") if zone else None
    if fix and len(fix) == 2:
        fx, fy = float(gx) + float(fix[0]), float(gy) + float(fix[1])
        # 边界钳制：游戏坐标最小 0（负值会算出窗口外像素，点击无效）
        fx, fy = max(0.0, fx), max(0.0, fy)
        if not is_in_no_go_zone(map_name, fx, fy)[0]:
            return fx, fy, True
        # fix 后仍命中其它禁区 → 以 fix 点为起点继续螺旋搜索
        gx, gy = fx, fy

    gxi, gyi = int(round(gx)), int(round(gy))
    # 2) 螺旋式向外搜索：先试目标附近 1 格，再逐圈扩大
    for ring in range(1, max_ring + 1):
        # 枚举当前环上的点（正方形边界）
        for dx in range(-ring, ring + 1):
            for dy in range(-ring, ring + 1):
                if max(abs(dx), abs(dy)) != ring:
                    continue  # 只扫当前环
                cx, cy = gxi + dx, gyi + dy
                if not is_in_no_go_zone(map_name, cx, cy)[0]:
                    return float(cx), float(cy), True
    # 兜底：返回偏移 max_ring 格的固定方向点
    return float(gxi + max_ring), float(gyi), True


def safe_target_for_module(
    module_name: str, coord: Tuple[float, float]
) -> Tuple[float, float, bool]:
    """按模块名（JYC/JNYW...）规避禁区。

    :param module_name: 地图函数模块名
    :param coord: 目标坐标 (gx, gy)
    :return: (安全x, 安全y, 是否被修正)
    """
    map_name = MODULE_MAP_NAME.get(module_name)
    if map_name is None:
        return float(coord[0]), float(coord[1]), False
    return resolve_safe_coord(map_name, float(coord[0]), float(coord[1]))


if __name__ == "__main__":
    # 自测
    print("禁区表内容:")
    for k, v in _load_zones().items():
        print(f"  {k}: {len(v)} 条")
    x, y, ok = resolve_safe_coord("建邺城", 171, 109)
    print(f"建邺城 (171,109) → ({x:.0f},{y:.0f}) 修正={ok}")
