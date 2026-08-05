# -*- coding: utf-8 -*-
"""P1 #2 回归：YOLO 事件真推理路径被选中并按 action 执行。

通过 mock yolo_detector 与 screen_capture，验证：
- 模型可用时走真推理（_execute_yolo_action），且 click 会调用 _do_click 命中目标中心；
- target_class 过滤生效（类别不匹配则不点击）；
- action=record 返回检测结果（method="yolo"）；
- action=wait 命中目标后可点击；
- 模型不可用时降级 _execute_yolo_fallback。
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core import task_engine
from core.task_engine import TaskEngine


class _FakeYolo:
    """模拟已加载模型的 yolo_detector：detect 忽略图像直接回检测列表。"""

    def __init__(self, detections):
        self.model = object()  # 真值：模型已加载
        self._detections = detections

    def detect(self, image=None, confidence=None):
        return self._detections


def _install_yolo(monkeypatch, detections):
    fake = _FakeYolo(detections)
    monkeypatch.setattr(task_engine, "_get_yolo_detector", lambda: fake)
    # screen_capture 是单例实例，patch 其 capture 方法返回非空假图
    from core.screen_capture import screen_capture as _sc
    monkeypatch.setattr(_sc, "capture", lambda: [0])
    return fake


def test_yolo_click_hits_target_center(monkeypatch):
    eng = TaskEngine()
    dets = [{"class": "npc", "confidence": 0.92,
             "bbox": (90, 190, 110, 210), "center": (100, 200)}]
    _install_yolo(monkeypatch, dets)
    clicked = []
    monkeypatch.setattr(
        eng, "_do_click",
        lambda c, b="left", d=0.0: clicked.append((c, b)) or True
    )

    ok, result = eng._execute_yolo_detect({"action": "click", "target_class": "npc"})
    assert ok is True
    assert clicked, "YOLO 真推理 click 必须调用 _do_click"
    assert clicked[0][0] == (100, 200)  # 命中目标中心
    assert "YOLO" in str(result)


def test_yolo_click_respects_target_class(monkeypatch):
    eng = TaskEngine()
    dets = [{"class": "monster", "confidence": 0.95, "center": (5, 5)}]
    _install_yolo(monkeypatch, dets)
    clicked = []
    monkeypatch.setattr(
        eng, "_do_click",
        lambda c, b="left", d=0.0: clicked.append(c) or True
    )

    ok, _ = eng._execute_yolo_detect({"action": "click", "target_class": "npc"})
    assert ok is False
    assert clicked == []  # 未匹配类别，不应点击


def test_yolo_record_returns_detections(monkeypatch):
    eng = TaskEngine()
    dets = [{"class": "npc", "confidence": 0.8, "center": (10, 20)}]
    _install_yolo(monkeypatch, dets)

    ok, result = eng._execute_yolo_detect({"action": "record"})
    assert ok is True
    assert result["method"] == "yolo"
    assert result["targets"] == dets


def test_yolo_wait_finds_and_clicks(monkeypatch):
    eng = TaskEngine()
    dets = [{"class": "npc", "confidence": 0.9, "center": (40, 50)}]
    _install_yolo(monkeypatch, dets)
    clicked = []
    monkeypatch.setattr(
        eng, "_do_click",
        lambda c, b="left", d=0.0: clicked.append(c) or True
    )

    ok, result = eng._execute_yolo_detect(
        {"action": "wait", "target_class": "npc", "click_on_found": True, "timeout": 2}
    )
    assert ok is True
    assert clicked == [(40, 50)]  # wait 命中后点击


def test_yolo_falls_back_when_model_missing(monkeypatch):
    eng = TaskEngine()
    monkeypatch.setattr(task_engine, "_get_yolo_detector", lambda: None)
    called = {}

    def _fb(p):
        called["fallback"] = True
        return (True, "fb")

    monkeypatch.setattr(eng, "_execute_yolo_fallback", _fb)

    ok, _ = eng._execute_yolo_detect({"action": "click"})
    assert called.get("fallback") is True
