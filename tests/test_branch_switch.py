# -*- coding: utf-8 -*-
"""switch 按 target_location 分流的回归测试。

- 引擎路由（纯逻辑，无需 GUI）：验证 source_var + 多 case actions 能正确命中。
- 编辑器序列化（需 PyQt5 + 显示）：验证 condition switch 页的 cases/子流程
  往返一致；无显示环境下自动跳过。
"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.task_engine import TaskEngine


def _patch_and_run(eng, params, jhrw_result):
    eng._var_context["JHRW"] = jhrw_result
    eng._last_result = jhrw_result
    captured = {}

    def fake(action_def, match_field, match_str, depth=0):
        captured["action_def"] = action_def
        captured["match_field"] = match_field
        captured["match_str"] = match_str
        return True, {"ok": True}

    eng._execute_switch_actions = fake
    eng._execute_switch_condition_with_depth(params, 0)
    return captured


def test_switch_routes_to_matched_case():
    eng = TaskEngine()
    params = {
        "mode": "switch",
        "match_field": "target_location",
        "source_var": "JHRW",
        "cases": [
            {"match_value": "建邺城", "actions": [{"event_type": "click", "params": {"x": 1}}]},
            {"match_value": "江南野外", "actions": [{"event_type": "click", "params": {"x": 2}}]},
            {"match_value": "东海湾", "actions": [
                {"event_type": "click", "params": {"x": 3}},
                {"event_type": "wait", "params": {"duration": 1}},
            ]},
        ],
        "default_action": {"action": "none"},
    }
    cap = _patch_and_run(eng, params, {"target_location": "东海湾", "target_coord": [47, 112]})
    assert cap["match_str"] == "东海湾"
    assert cap["action_def"]["actions"][0]["params"]["x"] == 3
    assert len(cap["action_def"]["actions"]) == 2


def test_switch_default_when_no_case():
    eng = TaskEngine()
    params = {
        "mode": "switch",
        "match_field": "target_location",
        "source_var": "JHRW",
        "cases": [{"match_value": "建邺城", "actions": [{"event_type": "click"}]}],
        "default_action": {"action": "none"},
    }
    cap = _patch_and_run(eng, params, {"target_location": "长寿村"})
    # 无 case 命中时不应执行任何 case 动作
    assert "action_def" not in cap


def test_switch_candidates_tight_no_overmatch():
    """target_location_candidates 必须只含活动地图，避免误匹配定义集群里的其它地图。

    实战场景：JHRW 读出的定义集群里有 傲来国/长安城/长寿村，但活动目标只有
    东海湾。若候选集把定义集群全带上，case='傲来国' 会误触发；收紧为 ['东海湾']
    后，只有 东海湾 case 命中。
    """
    eng = TaskEngine()
    params = {
        "mode": "switch",
        "match_field": "target_location",
        "source_var": "JHRW",
        "cases": [
            {"match_value": "傲来国", "actions": [{"event_type": "click", "params": {"x": 9}}]},
            {"match_value": "东海湾", "actions": [{"event_type": "click", "params": {"x": 3}}]},
            {"match_value": "建邺城", "actions": [{"event_type": "click", "params": {"x": 1}}]},
        ],
        "default_action": {"action": "none"},
    }
    cap = _patch_and_run(eng, params, {
        "target_location": "东海湾", "target_coord": [44, 69],
        "target_location_candidates": ["东海湾"],
    })
    assert cap["match_str"] == "东海湾"
    assert cap["action_def"]["actions"][0]["params"]["x"] == 3


def test_switch_empty_candidates_falls_back_to_exact():
    """候选集为空（离群法无法确信活动目标）时，退回精确匹配，不误命中。"""
    eng = TaskEngine()
    params = {
        "mode": "switch",
        "match_field": "target_location",
        "source_var": "JHRW",
        "cases": [
            {"match_value": "傲来国", "actions": [{"event_type": "click"}]},
            {"match_value": "东海湾", "actions": [{"event_type": "click", "params": {"x": 3}}]},
        ],
        "default_action": {"action": "none"},
    }
    cap = _patch_and_run(eng, params, {
        "target_location": "东海湾", "target_coord": [44, 69],
        "target_location_candidates": [],
    })
    assert cap["match_str"] == "东海湾"
    assert cap["action_def"]["actions"][0]["params"]["x"] == 3


def test_switch_source_var_isolates_variable():
    """source_var 应只从指定变量取字段，避免多函数事件歧义。"""
    eng = TaskEngine()
    # 另一个函数也写了 target_location，但 switch 指定 source_var=JHRW
    eng._var_context["OtherFn"] = {"target_location": "江南野外"}
    params = {
        "mode": "switch",
        "match_field": "target_location",
        "source_var": "JHRW",
        "cases": [
            {"match_value": "建邺城", "actions": [{"event_type": "click"}]},
            {"match_value": "东海湾", "actions": [{"event_type": "click"}]},
        ],
        "default_action": {"action": "none"},
    }
    cap = _patch_and_run(eng, params, {"target_location": "东海湾"})
    assert cap["match_str"] == "东海湾"


def test_editor_switch_serialization_roundtrip():
    pytest = __import__("pytest")
    PyQt5 = pytest.importorskip("PyQt5")
    from PyQt5.QtWidgets import QApplication
    from gui.event_editor import EventEditorDialog
    from models.event import Event
    import json

    app = QApplication.instance() or QApplication([])
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(here, "tasks", "chu_chu_jiang_hu_branch.json"),
              encoding="utf-8") as f:
        data = json.load(f)
    cond_event = Event.from_dict(data["tasks"][0]["events"][5])
    dlg = EventEditorDialog(cond_event)
    assert dlg._apply_to_event(cond_event) is True
    p = cond_event.params
    assert p["source_var"] == "JHRW"
    assert [c["match_value"] for c in p["cases"]] == ["建邺城", "江南野外", "东海湾"]
    assert all(len(c["actions"]) == 3 for c in p["cases"])
    assert p["default_action"]["action"] == "subflow"
    assert len(p["default_action"]["actions"]) == 1


def test_subflow_editor_instantiates():
    """SubFlowEditorDialog 必须能无错实例化（防止漏导入 QListWidget 等控件）。"""
    PyQt5 = pytest.importorskip("PyQt5")
    from PyQt5.QtWidgets import QApplication
    from gui.subflow_editor import SubFlowEditorDialog
    from models.event import Event
    app = QApplication.instance() or QApplication([])
    evs = [Event(name="步骤1", event_type="click", params={"x": 1, "y": 1})]
    dlg = SubFlowEditorDialog(evs, None, [])
    dlg._refresh_list()
    assert dlg._list.count() == 1


def test_subflow_editor_on_add(monkeypatch):
    """SubFlowEditorDialog._on_add 必须能新增事件（防止漏导入 _event_type_name）。"""
    pytest.importorskip("PyQt5")
    from PyQt5.QtWidgets import QApplication, QDialog

    import gui.task_editor
    from gui.subflow_editor import SubFlowEditorDialog
    from models.event import Event

    app = QApplication.instance() or QApplication([])

    class _FakeDlg:
        def __init__(self, parent=None):
            pass

        def exec_(self):
            return QDialog.Accepted

        def selected_type(self):
            return "click"

    monkeypatch.setattr(gui.task_editor, "EventTypeDialog", _FakeDlg)

    dlg = SubFlowEditorDialog([], None, [])
    before = len(dlg._events)
    dlg._on_add()
    assert len(dlg._events) == before + 1
    assert dlg._events[0].event_type == "click"


def test_subflow_editor_writes_back_on_accept():
    """SubFlowEditorDialog 关闭（accept）时必须把编辑结果写回原 events 引用。

    这是"按地图分流"子流程能正确保存的关键：父窗口传进来 self._case_subflows[row]
    的引用，对话框 OK 时必须原地更新，否则父窗口看到的永远是空子流程。
    """
    pytest.importorskip("PyQt5")
    from PyQt5.QtWidgets import QApplication, QDialog
    from gui.subflow_editor import SubFlowEditorDialog
    from models.event import Event

    app = QApplication.instance() or QApplication([])

    # 模拟父窗口持有的"case 子流程"引用
    case_subflow: list = []
    dlg = SubFlowEditorDialog(case_subflow, None, [])

    # 用户在子流程里加了两个事件
    dlg._events.append(Event(name="走坐标", event_type="click",
                             params={"x": 100, "y": 200, "button": "left"}))
    dlg._events.append(Event(name="等待", event_type="wait",
                             params={"duration": 0.5}))

    # 用户点 OK
    dlg.accept()

    # 关键断言：原引用被原地更新（自动保存）
    assert case_subflow == dlg._events, (
        "子流程编辑器的修改未写回原引用——"
        "父窗口 self._case_subflows[row] 永远为空，导致子流程不保存"
    )
    assert len(case_subflow) == 2
    assert case_subflow[0].event_type == "click"
    assert case_subflow[1].event_type == "wait"


def test_subflow_editor_inherits_parent_task_predecessors(monkeypatch):
    """子流程里编辑"函数调用"事件时，"承接参数"必须能引用父任务前序事件（如 JHRW）。

    链路：父任务 [YOLO接任务, JHRW函数, condition_switch] → 命中建邺城 case →
    子流程 [点击] → 编辑"点击"事件时承接参数应能看到 JHRW（而非空）。
    """
    pytest.importorskip("PyQt5")
    from PyQt5.QtWidgets import QApplication, QDialog
    from gui.subflow_editor import SubFlowEditorDialog
    from models.event import Event

    app = QApplication.instance() or QApplication([])

    # 父任务里 condition 事件之前的两个事件（其中 JHRW 是函数调用）
    jhrw = Event(name="读任务", event_type="function", params={"var_name": "JHRW"})
    prev_click = Event(name="YOLO接任务", event_type="yolo_detect",
                       params={"template": "accept"})
    parent_prev = [prev_click, jhrw]

    # 子流程里已有 1 个点击事件，要再编辑它
    subflow_click = Event(name="走坐标", event_type="click",
                          params={"x": 1, "y": 1})
    case_subflow = [subflow_click]

    dlg = SubFlowEditorDialog(case_subflow, None, parent_prev)

    # 选中子流程内的事件（QListWidget 默认无选中行，_on_edit 会弹 QMessageBox 报错）
    dlg._list.setCurrentRow(0)

    # 拦截 EventEditorDialog 的实例化，捕获 previous_events 参数
    captured = {}

    class _FakeEventEditor:
        def __init__(self, event, parent=None, previous_events=None):
            captured["event"] = event
            captured["previous_events"] = previous_events

        def exec_(self):
            return QDialog.Rejected  # 立刻关闭，不污染测试

    import gui.event_editor as event_editor_mod
    monkeypatch.setattr(event_editor_mod, "EventEditorDialog", _FakeEventEditor)

    # 触发 _on_edit
    dlg._on_edit()

    # 关键断言：previous_events 包含父任务 JHRW + 子流程内前面（空）
    prev = captured["previous_events"]
    assert prev is not None, "子流程 _on_edit 没把前序传给 EventEditorDialog"
    assert jhrw in prev, "父任务的 JHRW 函数调用没被合并进承接参数前序"
    assert prev_click in prev, "父任务前序点击事件丢失"
    # 顺序：父任务先跑（prev_click → jhrw），再子流程内（这里空）
    assert prev.index(prev_click) < prev.index(jhrw)


def test_subflow_editor_passes_parent_prev_via_helper(monkeypatch):
    """ConditionParamPage._edit_subflow_dialog 必须把父对话框 _previous_events 透传给子流程。

    验证父→子流程的接线正确：用户在父窗口编辑 condition 时打开的子流程编辑器，
    应拿到"父任务里 condition 之前的事件"作为 context_events。
    """
    pytest.importorskip("PyQt5")
    from PyQt5.QtWidgets import QApplication
    from gui.event_editor import EventEditorDialog
    from gui.subflow_editor import SubFlowEditorDialog
    from models.event import Event, EventType

    app = QApplication.instance() or QApplication([])

    # 模拟父 EventEditorDialog：携带 _previous_events 包含 JHRW
    parent_event = Event(name="条件分支", event_type="condition", params={})
    jhrw = Event(name="读任务", event_type="function", params={"var_name": "JHRW"})
    dlg_parent = EventEditorDialog(parent_event, None, [jhrw])

    # 拦截 SubFlowEditorDialog 构造，捕获 context_events
    captured = {}

    def _spy_init(self, events, parent=None, context_events=None):
        captured["context_events"] = context_events
        # 不真的初始化（避免触发 _init_ui 等）
        self._events_ref = events if events is not None else []
        self._events = list(self._events_ref)
        self._context_events = list(context_events) if context_events else []

    monkeypatch.setattr(SubFlowEditorDialog, "__init__", _spy_init)
    monkeypatch.setattr(SubFlowEditorDialog, "exec_", lambda self: 0)  # Rejected

    # 子流程编辑现由 EventEditorDialog._edit_subflow_dialog 发起（2026-08-04 统一为
    # gui.subflow_editor 的 7 按钮版，本文件重复类已删）。它把父对话框的
    # _previous_events（含 JHRW）透传给 SubFlowEditorDialog。
    dlg_parent._edit_subflow_dialog([])

    assert captured["context_events"] is not None
    assert jhrw in captured["context_events"], (
        "父 EventEditorDialog 没把 _previous_events 透传给 SubFlowEditorDialog，"
        "导致子流程里函数调用的承接参数看不到父任务上游结果"
    )
