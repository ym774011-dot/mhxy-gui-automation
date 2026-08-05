# -*- coding: utf-8 -*-
"""
地图 UI 遮挡避让 —— 防止目标像素落在 UI 上导致点击失效。

背景（2026-08-05 用户反馈）：
    江南野外目标 (158,74) 映射成客户区像素 (684,373) 后，点击落在
    大地图/任务追踪面板等 UI 上被吃掉，角色不走动、NPC 无法对话。

方案：
    用户在 `data/map_ui_blocks.json` 维护每个地图的 UI 像素矩形
    （大地图、任务追踪面板、小地图等），地图函数调用前把目标
    game 坐标映射成客户区像素，若落在矩形内则沿最近边界偏移
    出矩形，再反算回 game 坐标。

数据格式（data/map_ui_blocks.json）::

    {
      "江南野外": {
        "origin": [314.0, 202.0],       # game(0,0) 的客户区像素
        "scale":  [2.34, 2.307],        # 每 game 单位像素数
        "blocks": [
          {"name": "大地图", "x1": 740, "y1": 195, "x2": 1000, "y2": 520},
          {"name": "任务追踪面板", "x1": 825, "y1": 108, "x2": 1000, "y2": 330}
        ]
      }
    }
"""
from __future__ import annotations

import json
import os
from typing import Dict, List, Optional, Tuple

from utils.logger import logger

_UI_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "data", "map_ui_blocks.json"
)

# 运行时缓存（mtime 变化自动重载）
_cache: Optional[Dict[str, dict]] = None
_cache_mtime: float = 0.0

# 偏移出矩形后额外留出的边距（像素）
UI_MARGIN = 25


def _load_ui_blocks() -> Dict[str, dict]:
    """读取 UI 禁区表（带 mtime 缓存）。"""
    global _cache, _cache_mtime
    try:
        mtime = os.path.getmtime(_UI_PATH)
        if _cache is not None and mtime == _cache_mtime:
            return _cache
        with open(_UI_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        data = {k: v for k, v in data.items() if not k.startswith("_")}
        _cache = data
        _cache_mtime = mtime
        return data
    except Exception as e:
        logger.warning(f"读取 UI 禁区表失败: {e}")
        return {}


def reload_ui_blocks() -> None:
    """强制重载（配置保存后调用）。"""
    global _cache, _cache_mtime
    _cache = None
    _cache_mtime = 0.0
    _load_ui_blocks()


def get_map_calibration(map_name: str) -> Optional[Tuple[float, float, float, float]]:
    """取地图校准参数 (ox, oy, sx, sy)。"""
    entry = _load_ui_blocks().get(map_name)
    if not entry:
        return None
    try:
        ox, oy = float(entry["origin"][0]), float(entry["origin"][1])
        sx, sy = float(entry["scale"][0]), float(entry["scale"][1])
    except (KeyError, TypeError, IndexError, ValueError):
        return None
    return (ox, oy, sx, sy)


def _in_rect(px: float, py: float, block: dict) -> bool:
    return (
        block["x1"] <= px <= block["x2"]
        and block["y1"] <= py <= block["y2"]
    )


def _get_client_size() -> Tuple[int, int]:
    """取当前客户区尺寸（懒导入 window_manager，失败默认 1000×620）。"""
    try:
        from core.window_manager import window_manager
        cw, ch = window_manager.get_client_size()
        if cw > 0 and ch > 0:
            return (int(cw), int(ch))
    except Exception:
        pass
    return (1000, 620)


def resolve_pixel_ui(
    map_name: str, px: float, py: float, margin: int = UI_MARGIN
) -> Tuple[float, float, Optional[str]]:
    """客户区像素落在 UI 矩形内 → 沿最近边界偏移出矩形。

    :param map_name: 地图名（如 '江南野外'）
    :param px, py: 目标客户区像素
    :param margin: 偏移出矩形后的额外边距
    :return: (新px, 新py, 命中的 UI 名)；未命中返回原值 + None
    """
    entry = _load_ui_blocks().get(map_name)
    if not entry:
        return float(px), float(py), None
    cw, ch = _get_client_size()
    for block in entry.get("blocks", []):
        if not _in_rect(px, py, block):
            continue
        x1, y1 = float(block["x1"]), float(block["y1"])
        x2, y2 = float(block["x2"]), float(block["y2"])
        # 到四边的距离，候选偏移点按距离排序；优先最近边，
        # 但排除会偏移出客户区的方向（点在窗口外同样点击无效）
        edges = [
            (px - x1, (x1 - margin, py)),
            (x2 - px, (x2 + margin, py)),
            (py - y1, (px, y1 - margin)),
            (y2 - py, (px, y2 + margin)),
        ]
        edges.sort(key=lambda e: e[0])
        for _, (npx, npy) in edges:
            if 0 <= npx < cw and 0 <= npy < ch:
                logger.info(
                    f"[UI避让] {map_name} 目标像素 ({px:.0f},{py:.0f}) "
                    f"在「{block['name']}」内 → 偏移到 ({npx:.0f},{npy:.0f})"
                )
                return float(npx), float(npy), block["name"]
        # 全方向都超界（极端情况）：钳制回客户区内
        npx = min(max(px, 0.0), float(cw - 1))
        npy = min(max(py, 0.0), float(ch - 1))
        logger.info(
            f"[UI避让] {map_name} 目标像素 ({px:.0f},{py:.0f}) 在「{block['name']}」内"
            f"（各方向超界）→ 钳制到 ({npx:.0f},{npy:.0f})"
        )
        return float(npx), float(npy), block["name"]
    return float(px), float(py), None


def map_coord_ui_avoid(
    map_name: str, gx: float, gy: float, margin: int = UI_MARGIN
) -> Tuple[float, float, Optional[str]]:
    """game 坐标 → UI 避让。

    两级策略（用户实测数据为权威）：
      1) ``max_game_coord``（大地图打开时有效点击范围上限，用户游戏内实测）：
         gx/gy 任一超限 → 钳制到上限（超出的坐标点落在大地图 UI 上，点击无效）。
         有该数据的地图直接返回，不再走像素矩形（避免估算偏差误伤）。
      2) 像素矩形避让（无 max_game_coord 的老数据兜底）：
         game → 像素 → 在矩形内沿最近边界偏移 → 反算 game。

    :param map_name: 地图名（如 '江南野外'）
    :param gx, gy: 原始目标 game 坐标
    :return: (新gx, 新gy, 命中的 UI 名)；未命中返回原值 + None
    """
    entry = _load_ui_blocks().get(map_name)
    if not entry:
        return float(gx), float(gy), None

    # 1) 用户实测有效点击范围钳制
    limit = entry.get("max_game_coord")
    if limit and len(limit) == 2:
        max_x, max_y = float(limit[0]), float(limit[1])
        ngx, ngy = min(float(gx), max_x), min(float(gy), max_y)
        if (ngx, ngy) != (float(gx), float(gy)):
            logger.info(
                f"[UI避让] {map_name} 目标 ({gx:.0f},{gy:.0f}) 超过大地图"
                f"有效点击范围 ({max_x:.0f},{max_y:.0f}) → 钳制到 ({ngx:.0f},{ngy:.0f})"
            )
            return float(ngx), float(ngy), "大地图有效范围"
        return float(gx), float(gy), None

    # 2) 像素矩形避让（兜底，无用户数据的地图）
    calib = get_map_calibration(map_name)
    if calib is None:
        return float(gx), float(gy), None
    ox, oy, sx, sy = calib
    px, py = ox + gx * sx, oy + gy * sy
    npx, npy, ui_name = resolve_pixel_ui(map_name, px, py, margin)
    if ui_name is None:
        return float(gx), float(gy), None
    ngx, ngy = (npx - ox) / sx, (npy - oy) / sy
    return float(ngx), float(ngy), ui_name


if __name__ == "__main__":
    # 自测：江南野外 (158,74) → 像素 (684,373) → 应在 UI 外？(684,373) 在中央，不在矩形
    gx, gy = 158.0, 74.0
    calib = get_map_calibration("江南野外")
    if calib:
        ox, oy, sx, sy = calib
        print(f"校准: origin=({ox},{oy}) scale=({sx},{sy})")
        px, py = ox + gx * sx, oy + gy * sy
        print(f"({gx},{gy}) → 像素 ({px:.0f},{py:.0f})")
        npx, npy, ui = resolve_pixel_ui("江南野外", px, py)
        print(f"UI 检测: {ui or '未命中'}")
        # 模拟一个落在矩形内的点：游戏坐标 → 像素在大地图内
        for tgx, tgy in [(200, 100), (250, 130)]:
            pxx, pyy = ox + tgx * sx, oy + tgy * sy
            ngx, ngy, name = map_coord_ui_avoid("江南野外", tgx, tgy)
            print(f"({tgx},{tgy}) → 像素({pxx:.0f},{pyy:.0f}) → {name or '未命中'}"
                  f" → 修正 ({ngx:.0f},{ngy:.0f})")
