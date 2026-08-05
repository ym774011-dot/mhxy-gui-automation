# -*- coding: utf-8 -*-
"""
OCR 引擎管理器线程安全测试 + 公开 API 委托验证。

验证 PR #6 的整改要点：
- 多线程并发首调只初始化引擎一次（无竞态重复构造）
- 首次初始化后结果被缓存，后续无锁直读
- 公开 API（is_ocr_available / read_coord_ocr）委托到线程安全单例
"""
import time
import threading

from unittest.mock import patch

import pytest

from core.ocr_coord_reader import (
    OCREngineManager,
    _ocr_engine_manager,
    is_ocr_available,
    read_coord_ocr,
)


def test_concurrent_init_only_once():
    """12 个线程并发首次调用，引擎初始化逻辑只应执行一次。"""
    mgr = OCREngineManager()
    init_calls: list = []
    orig = mgr._init_engine

    def counting(*_a, **_k):
        init_calls.append(1)
        time.sleep(0.02)  # 放大竞态窗口
        return orig(*_a, **_k)

    mgr._init_engine = counting

    results: list = []
    barrier = threading.Barrier(12)

    def worker():
        barrier.wait()
        results.append(mgr.get_engine())

    threads = [threading.Thread(target=worker) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 12, "所有并发调用都应拿到结果"
    assert len(init_calls) == 1, f"引擎只应初始化一次，实际 {len(init_calls)} 次"


def test_engine_cached_after_first_call():
    """首次调用后，后续调用不应再次触发初始化。"""
    mgr = OCREngineManager()
    init_calls: list = []
    mgr._init_engine = lambda *_a, **_k: (init_calls.append(1) or None)

    mgr.get_engine()
    mgr.get_engine()
    mgr.get_engine()

    assert len(init_calls) == 1, "初始化逻辑应仅执行一次（结果已缓存）"


def test_is_ocr_available_delegates_to_singleton():
    """is_ocr_available() 应委托到线程安全单例。"""
    with patch.object(_ocr_engine_manager, "get_engine", return_value=None):
        assert is_ocr_available() is False
    with patch.object(_ocr_engine_manager, "get_engine", return_value=object()):
        assert is_ocr_available() is True


def test_read_coord_ocr_returns_none_without_engine():
    """无 OCR 引擎时 read_coord_ocr 直接返回 None，且不抛异常。"""
    with patch.object(_ocr_engine_manager, "get_engine", return_value=None), \
         patch("core.ocr_coord_reader.screen_capture") as mock_sc:
        mock_sc.capture_region.return_value = None
        # 极小 timeout 仅验证快速失败路径（仍需一次截图返回 None）
        assert read_coord_ocr(timeout=0.01) is None
