# -*- coding: utf-8 -*-
"""
JHRW - 江湖任务查找函数包（字模指纹方案）
=====================================================
替代外部旧内存版 JHRW.py：用屏幕字模指纹匹配识别任务追踪栏，
不再依赖任何内存地址（地址每次重启 / 切图都会变化，内存路线已证不可靠）。

核心函数：
    JHRW(target_location=None, target_coord=None, pid=None, verbose=False)

依赖：
    - core.jhrw_controller  （字模读取统一入口，内部含坐标 + 任务面板）
    - core.window_manager   （游戏窗口绑定，由引擎在启动时完成）

识别区域（客户区相对坐标，见 core.glyph_coord_reader.JHRW_ROI）：
    (837, 120, 159, 116) —— 即屏幕 (837,120) ~ (996,236) 的任务追踪栏
"""
from __future__ import annotations

import time
from typing import Optional, Tuple

from core.jhrw_controller import jhrw_controller
from core.window_manager import window_manager
from utils.logger import logger

__function_meta__ = {
    "JHRW": {
        "title": "江湖任务 - 字模指纹读取当前任务信息",
        "args": {
            "target_location": "可选，期望地图名（如 '建邺城'），不匹配则视为失败",
            "target_coord": "可选，期望坐标 (x, y)，不匹配则视为失败",
            "pid": "游戏进程 PID（字模方案改用 window_manager 绑定窗口，仅记录）",
            "verbose": "是否打印过程日志",
        },
    },
}


def JHRW(
    target_location: Optional[str] = None,
    target_coord: Optional[Tuple[int, int]] = None,
    pid: Optional[int] = None,
    verbose: bool = False,
):
    """
    读取当前江湖任务信息（字模指纹方案）。

    :param target_location: 可选期望地图名，用于匹配验证
    :param target_coord: 可选期望坐标 (x, y)，用于匹配验证
    :param pid: 游戏进程 PID，仅记录到返回结果
    :param verbose: 是否打印详细日志
    :return: dict，结构兼容 GUI 调用（与旧内存版字段一致）
    """
    t0 = time.time()
    state = jhrw_controller.read_state(force_refresh=True)

    quest_name = state.quest_name or ""
    target_location_out = state.target_location or ""
    target_coord_out = state.target_coord            # (x, y) or None
    progress = state.progress
    npc = state.npc_name or ""
    instruction = state.instruction or ""

    # 识别成功判据：任一有效字段即可
    ok = bool(quest_name or target_location_out or target_coord_out)

    # 匹配验证（保留旧版语义：传入期望值才做严格比对）
    has_expect = (target_location is not None) or (target_coord is not None)
    matched = True
    if target_location is not None and target_location_out:
        matched = matched and (str(target_location_out) == str(target_location))
    if target_coord is not None and target_coord_out is not None:
        try:
            matched = matched and (
                tuple(int(v) for v in target_coord_out)
                == tuple(int(v) for v in target_coord)
            )
        except (TypeError, ValueError):
            matched = False

    progress_text = f"当前第{progress}次" if progress is not None else ""

    result = {
        "success": ok,
        "pid": int(window_manager.pid or 0),
        "quest_name": quest_name,
        "target_location": target_location_out,
        "target_coord": target_coord_out,
        "progress_text": progress_text,
        "progress_num": progress if progress is not None else 0,
        "description": instruction,
        "desc_addr": 0,                       # 字模方案无内存地址
        "npc": npc,
        "matched": (matched if has_expect else ok),
        "message": "任务信息查找成功" if ok else "任务信息查找失败",
        "source": "glyph_fingerprint",
        "stale": False,
        "quest_name_confidence": 0.9 if quest_name else 0.0,
        "target_location_candidates": [target_location_out] if target_location_out else [],
        "quest_signatures": {},
    }

    if verbose:
        logger.info(f"[JHRW glyph] {result}")

    return result
