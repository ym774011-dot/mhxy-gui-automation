# -*- coding: utf-8 -*-
"""P1 #3 回归：condition 事件真分支控制流（运行时执行）。

验证 simple 模式执行 true/false 分支事件序列、switch 模式执行命中 case 的
子流程动作序列。通过 monkeypatch 引擎的 _dispatch 捕获分支内事件，避免真实点击。
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.task_engine import TaskEngine
from models.event import Event, EventType


def _make_event(et, params):
    return Event(event_type=et, params=params)


def test_simple_true_branch_executes(monkeypatch):
    eng = TaskEngine()
    dispatched = []
    monkeypatch.setattr(
        eng, "_dispatch", lambda e: dispatched.append(e) or (True, "ok")
    )
    child = _make_event(EventType.CLICK, {"x": 1, "y": 2})
    cond = _make_event(EventType.CONDITION, {
        "mode": "simple", "variable": "flag", "operator": "==", "value": "yes",
        "true_branch": [child.to_dict()], "false_branch": [],
    })
    monkeypatch.setattr(
        eng, "_evaluate_simple_condition",
        lambda p: (True, True, "yes", "yes")
    )

    ok, _ = eng._execute_condition(cond)
    assert ok is True
    assert len(dispatched) == 1
    assert dispatched[0].event_type == EventType.CLICK


def test_simple_false_branch_executes(monkeypatch):
    eng = TaskEngine()
    dispatched = []
    monkeypatch.setattr(
        eng, "_dispatch", lambda e: dispatched.append(e) or (True, "ok")
    )
    child = _make_event(EventType.CLICK, {"x": 9, "y": 9})
    cond = _make_event(EventType.CONDITION, {
        "mode": "simple", "variable": "flag", "operator": "==", "value": "yes",
        "true_branch": [], "false_branch": [child.to_dict()],
    })
    monkeypatch.setattr(
        eng, "_evaluate_simple_condition",
        lambda p: (True, False, "no", "yes")
    )

    ok, _ = eng._execute_condition(cond)
    assert ok is True
    assert len(dispatched) == 1
    assert dispatched[0].event_type == EventType.CLICK


def test_switch_subflow_executes(monkeypatch):
    eng = TaskEngine()
    dispatched = []
    monkeypatch.setattr(
        eng, "_dispatch", lambda e: dispatched.append(e) or (True, "ok")
    )
    case_click = _make_event(EventType.CLICK, {"x": 3, "y": 4})
    cond = _make_event(EventType.CONDITION, {
        "mode": "switch",
        "match_field": "target_location",
        "source_var": "JHRW",
        "cases": [
            {"match_value": "建邺城", "actions": [case_click.to_dict()]},
        ],
        "default_action": {"action": "none"},
    })
    eng._var_context["JHRW"] = {"target_location": "建邺城", "target_coord": [1, 2]}

    ok, _ = eng._execute_condition(cond)
    assert ok is True
    assert len(dispatched) == 1
    assert dispatched[0].event_type == EventType.CLICK
