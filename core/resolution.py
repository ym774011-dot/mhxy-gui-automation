# -*- coding: utf-8 -*-
"""
resolution - 分辨率自适应缩放层（2026-08-25）

背景：脚本坐标体系以「设计基准分辨率」开发（默认 1000x600），
任务序列点击坐标、JHRW ROI、任务库硬编码坐标均按基准分辨率设计。
游戏窗口缩放到其他尺寸（如 800x600）时，这些逻辑坐标需要按
「当前客户区 / 基准分辨率」缩放，否则点击/识别位置偏移。

坐标体系约定：
- 逻辑坐标（logical）：基准分辨率下的坐标（任务序列 JSON、任务库硬编码）
- 物理坐标（client）：当前窗口客户区像素坐标（PostMessage 直接使用，
  模板匹配/YOLO 返回的坐标）

本模块提供 逻辑→物理 与 物理→逻辑 双向换算。物理路径（模板/YOLO）
不做缩放，逻辑路径（任务序列 click / JHRW ROI / 任务库硬编码）显式调用。
"""

import os

# 设计基准分辨率（可从 config/resolution.base_size 覆盖）
DEFAULT_BASE_SIZE = (1000, 600)


def base_size() -> tuple:
    """设计基准分辨率 (w, h)。优先读 config 的 resolution.base_size。"""
    try:
        from config.config import config
        v = config.get("resolution.base_size")
        if isinstance(v, (list, tuple)) and len(v) == 2:
            bw, bh = int(v[0]), int(v[1])
            if bw > 0 and bh > 0:
                return (bw, bh)
    except Exception:
        pass
    return DEFAULT_BASE_SIZE


def _client_size():
    """当前窗口客户区尺寸 (w, h)。"""
    try:
        from core.window_manager import window_manager
        w, h = window_manager.get_client_size()
        if w and h:
            return (int(w), int(h))
    except Exception:
        pass
    return None


def get_scale():
    """返回 (scale_x, scale_y)。未绑定窗口或窗口=基准时返回 (1.0, 1.0)。"""
    cs = _client_size()
    if not cs:
        return (1.0, 1.0)
    bw, bh = base_size()
    cw, ch = cs
    if cw <= 0 or ch <= 0:
        return (1.0, 1.0)
    return (cw / bw, ch / bh)


def logical_to_client(x, y):
    """逻辑坐标 → 窗口客户区物理坐标（后台 PostMessage 用）。"""
    sx, sy = get_scale()
    try:
        return (int(round(float(x) * sx)), int(round(float(y) * sy)))
    except (TypeError, ValueError):
        return (x, y)


def client_to_logical(x, y):
    """窗口客户区物理坐标 → 逻辑坐标（反向换算，调试用）。"""
    sx, sy = get_scale()
    try:
        return (int(round(float(x) / sx)), int(round(float(y) / sy)))
    except (TypeError, ValueError):
        return (x, y)


def logical_rect(x, y, w, h):
    """逻辑 ROI (x, y, w, h) → 物理 ROI。"""
    sx, sy = get_scale()
    try:
        return (int(round(float(x) * sx)), int(round(float(y) * sy)),
                int(round(float(w) * sx)), int(round(float(h) * sy)))
    except (TypeError, ValueError):
        return (x, y, w, h)


def scale_info() -> dict:
    """调试信息：当前客户区/基准/缩放系数。"""
    cs = _client_size()
    bw, bh = base_size()
    sx, sy = get_scale()
    return {
        "client_size": list(cs) if cs else None,
        "base_size": [bw, bh],
        "scale": [round(sx, 4), round(sy, 4)],
    }
