# -*- coding: utf-8 -*-
"""PR #8 收口回归：7 种事件类型参数页 build/load/apply 全链路冒烟。

防止上帝类拆分后某个 ParamPage 漏导入控件、load/apply 逻辑错位导致运行期
NameError / AttributeError。每个事件类型都走一遍：构造对话框（触发 build+load）
→ _apply_to_event（触发 apply），断言无异常且写回成功。
"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt5")

from PyQt5.QtWidgets import QApplication

from gui.event_editor import EventEditorDialog
from gui.task_editor import _default_params
from models.event import Event, EventType


_EVENT_TYPES = [
    EventType.CLICK,
    EventType.KEY,
    EventType.WAIT,
    EventType.IMAGE,
    EventType.YOLO,
    EventType.FUNCTION,
    EventType.CONDITION,
]


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _roundtrip(event_type):
    """构造默认参数事件 → 打开对话框（build+load）→ apply 写回，返回写回结果。"""
    params = _default_params(event_type)
    event = Event(name=f"rt-{event_type}", event_type=event_type, params=params)
    dlg = EventEditorDialog(event)
    ok = dlg._apply_to_event(event)
    return event, params, ok


@pytest.mark.parametrize("event_type", _EVENT_TYPES)
def test_page_build_load_apply_no_error(app, event_type):
    """每个参数页 build/load/apply 必须无异常，且 apply 返回 True。"""
    event, _params, ok = _roundtrip(event_type)
    assert ok is True, f"{event_type} 参数页 apply 未成功（可能 JSON 解析失败）"
    assert isinstance(event.params, dict)


def test_click_roundtrip_preserves_coords(app):
    """click 页坐标/按键应在 load→apply 后原样保留（零行为变化）。"""
    event, params, ok = _roundtrip(EventType.CLICK)
    assert ok is True
    for key in ("x", "y", "click_type"):
        assert event.params.get(key) == params.get(key), (
            f"click 页字段 {key} 往返不一致：{event.params.get(key)} != {params.get(key)}"
        )


def test_wait_roundtrip_preserves_duration(app):
    """wait 页时长应在 load→apply 后原样保留。"""
    event, params, ok = _roundtrip(EventType.WAIT)
    assert ok is True
    assert event.params.get("duration") == params.get("duration")
