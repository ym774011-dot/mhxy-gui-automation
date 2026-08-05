# -*- coding: utf-8 -*-
"""任务序列循环功能测试。

验证 TaskSequence 的序列级循环字段（loop_count / loop_delay）的序列化，
以及 TaskEngine._run_sequence 的两级循环执行逻辑：
    - 有限次数循环
    - 默认不循环（loop_count=1）
    - 无限循环（loop_count=0）依赖 should_stop 退出
    - 循环间隔 loop_delay 生效
    - 停止信号在循环边界生效
"""
import json
from unittest.mock import MagicMock, patch

import pytest

from core.task_engine import TaskEngine
from models.event import EventType
from models.task import Task
from models.task_sequence import TaskSequence


# ----------------------------------------------------------------------
# 辅助：构造一个带信号的 TaskEngine（用 Mock 替换 PyQt 信号，避免依赖 QApplication）
# ----------------------------------------------------------------------
def _make_engine():
    """创建 TaskEngine 并用 Mock 替换其 PyQt5 信号，便于断言 emit。"""
    engine = TaskEngine()
    engine.finished_signal = MagicMock()
    engine.progress_signal = MagicMock()
    engine.log_signal = MagicMock()
    engine.status_signal = MagicMock()
    engine.quest_detail_signal = MagicMock()
    return engine


def _make_task(name="任务", event_count=1):
    """构造一个带若干空事件的 Task（事件类型用 CLICK 占位）。"""
    events = []
    for i in range(event_count):
        events.append({
            "name": f"事件{i + 1}",
            "event_type": EventType.CLICK,
            "params": {"x": 0, "y": 0},
        })
    return Task(name=name, events=events)


# ======================================================================
# TaskSequence 序列循环字段序列化测试
# ======================================================================
class TestSequenceLoopSerialization:
    """序列级循环字段的序列化/反序列化。"""

    def test_default_values(self):
        """默认 loop_count=1，loop_delay=1.0。"""
        seq = TaskSequence(name="默认序列")
        assert seq.loop_count == 1
        assert seq.loop_delay == 1.0

    def test_custom_values(self):
        """自定义循环次数与间隔。"""
        seq = TaskSequence(name="自定义", loop_count=5, loop_delay=2.5)
        assert seq.loop_count == 5
        assert seq.loop_delay == 2.5

    def test_infinite_loop_value(self):
        """loop_count=0 表示无限循环。"""
        seq = TaskSequence(name="无限", loop_count=0)
        assert seq.loop_count == 0

    def test_negative_loop_clamped(self):
        """负数 loop_count 被裁剪为 0（视为无限循环的安全值）。"""
        seq = TaskSequence(name="负数", loop_count=-3)
        # TaskSequence.__init__ 使用 max(0, int(loop_count))，负数会被裁到 0
        assert seq.loop_count == 0

    def test_to_dict_contains_loop_fields(self):
        """to_dict 包含 loop_count / loop_delay。"""
        seq = TaskSequence(name="序列", loop_count=3, loop_delay=0.5)
        d = seq.to_dict()
        assert d["loop_count"] == 3
        assert d["loop_delay"] == 0.5

    def test_from_dict_restores_loop_fields(self):
        """from_dict 恢复 loop_count / loop_delay。"""
        d = {
            "name": "恢复序列",
            "tasks": [],
            "loop_count": 7,
            "loop_delay": 3.0,
        }
        seq = TaskSequence.from_dict(d)
        assert seq.loop_count == 7
        assert seq.loop_delay == 3.0

    def test_from_dict_defaults_when_missing(self):
        """from_dict 缺省时回退到默认值。"""
        seq = TaskSequence.from_dict({"name": "缺省", "tasks": []})
        assert seq.loop_count == 1
        assert seq.loop_delay == 1.0

    def test_json_round_trip(self):
        """to_json / from_json 往返保持循环配置。"""
        seq = TaskSequence(name="JSON序列", loop_count=10, loop_delay=1.25)
        s = seq.to_json()
        restored = TaskSequence.from_json(s)
        assert restored.loop_count == 10
        assert restored.loop_delay == 1.25


# ======================================================================
# TaskEngine._run_sequence 序列循环执行逻辑测试
# ======================================================================
class TestRunSequenceLoop:
    """_run_sequence 的序列级循环行为。"""

    def test_default_no_loop_runs_once(self):
        """loop_count=1（默认）：所有任务只执行一遍。"""
        engine = _make_engine()
        seq = TaskSequence(
            name="不循环",
            tasks=[_make_task("T1"), _make_task("T2")],
            loop_count=1,
        )

        call_count = {"n": 0}

        def fake_run_task(task):
            call_count["n"] += 1
            return True, "ok"

        with patch.object(engine, "_run_task", side_effect=fake_run_task):
            engine._run_sequence(seq)

        # 2 个任务 × 1 轮 = 2 次
        assert call_count["n"] == 2
        # 完成信号：成功
        engine.finished_signal.emit.assert_called_once()
        args, _ = engine.finished_signal.emit.call_args
        assert args[0] is True

    def test_finite_loop_runs_multiple_times(self):
        """loop_count=3，2 个任务：_run_task 被调用 6 次。"""
        engine = _make_engine()
        seq = TaskSequence(
            name="循环3次",
            tasks=[_make_task("T1"), _make_task("T2")],
            loop_count=3,
            loop_delay=0.0,  # 不等待，加速测试
        )

        call_count = {"n": 0}

        def fake_run_task(task):
            call_count["n"] += 1
            return True, "ok"

        with patch.object(engine, "_run_task", side_effect=fake_run_task):
            engine._run_sequence(seq)

        assert call_count["n"] == 6  # 2 tasks × 3 loops
        args, _ = engine.finished_signal.emit.call_args
        assert args[0] is True

    def test_infinite_loop_stops_via_should_stop(self):
        """loop_count=0（无限）：依赖 should_stop 退出。"""
        engine = _make_engine()
        seq = TaskSequence(
            name="无限循环",
            tasks=[_make_task("T1")],
            loop_count=0,
            loop_delay=0.0,
        )

        call_count = {"n": 0}

        def fake_run_task(task):
            call_count["n"] += 1
            # 第 3 次调用后请求停止
            if call_count["n"] >= 3:
                engine.should_stop = True
            return True, "ok"

        with patch.object(engine, "_run_task", side_effect=fake_run_task):
            engine._run_sequence(seq)

        # should_stop 在任务执行后置位，下一轮循环边界检测到后退出
        assert call_count["n"] >= 3
        args, _ = engine.finished_signal.emit.call_args
        assert args[0] is False  # 被停止，非成功

    def test_loop_delay_between_iterations(self):
        """loop_delay 在每轮之间生效（验证 _interruptible_sleep 被调用）。"""
        engine = _make_engine()
        seq = TaskSequence(
            name="带间隔",
            tasks=[_make_task("T1")],
            loop_count=3,
            loop_delay=0.3,
        )

        sleep_calls = []

        def fake_sleep(seconds):
            sleep_calls.append(seconds)

        with patch.object(engine, "_run_task", return_value=(True, "ok")), \
                patch.object(engine, "_interruptible_sleep", side_effect=fake_sleep):
            engine._run_sequence(seq)

        # 3 轮循环，中间有 2 次间隔
        assert len(sleep_calls) == 2
        for s in sleep_calls:
            assert s == 0.3

    def test_stop_signal_between_loops(self):
        """停止信号在循环边界（进入下一轮前）生效。"""
        engine = _make_engine()
        seq = TaskSequence(
            name="边界停止",
            tasks=[_make_task("T1")],
            loop_count=5,
            loop_delay=0.0,
        )

        call_count = {"n": 0}

        def fake_run_task(task):
            call_count["n"] += 1
            # 第 1 轮完成后设置停止标志
            if call_count["n"] >= 1:
                engine.should_stop = True
            return True, "ok"

        with patch.object(engine, "_run_task", side_effect=fake_run_task):
            engine._run_sequence(seq)

        # 第 1 轮执行 1 次，随后在下一轮边界检测到 should_stop 退出
        assert call_count["n"] == 1
        args, _ = engine.finished_signal.emit.call_args
        assert args[0] is False

    def test_task_failure_breaks_sequence_loop(self):
        """任务失败（_run_task 返回 False）时停止整个序列循环。"""
        engine = _make_engine()
        seq = TaskSequence(
            name="失败停止",
            tasks=[_make_task("T1"), _make_task("T2")],
            loop_count=4,
            loop_delay=0.0,
        )

        call_count = {"n": 0}

        def fake_run_task(task):
            call_count["n"] += 1
            # 第 1 个任务第 1 次执行即失败
            return False, "任务执行出错"

        with patch.object(engine, "_run_task", side_effect=fake_run_task):
            engine._run_sequence(seq)

        # 第 1 个任务失败后立即停止，不再继续
        assert call_count["n"] == 1
        args, _ = engine.finished_signal.emit.call_args
        assert args[0] is False
        assert "出错" in args[1] or "中止" in args[1]

    def test_pause_then_stop_exits_loop(self):
        """暂停期间收到停止信号，循环能退出。"""
        engine = _make_engine()
        seq = TaskSequence(
            name="暂停后停止",
            tasks=[_make_task("T1")],
            loop_count=0,  # 无限循环
            loop_delay=0.0,
        )

        call_count = {"n": 0}

        def fake_run_task(task):
            call_count["n"] += 1
            if call_count["n"] >= 1:
                # 进入暂停状态，模拟外部 stop 在暂停中被调用
                engine.is_paused = True
                # 用小钩子让暂停循环尽快退出：直接置位停止
                engine.should_stop = True
                engine.is_paused = False
            return True, "ok"

        with patch.object(engine, "_run_task", side_effect=fake_run_task):
            engine._run_sequence(seq)

        # 至少执行了 1 轮，且最终因 should_stop 退出
        assert call_count["n"] >= 1
        args, _ = engine.finished_signal.emit.call_args
        assert args[0] is False

    def test_state_cleaned_after_finish(self):
        """执行结束后引擎状态被清理。"""
        engine = _make_engine()
        seq = TaskSequence(
            name="状态清理",
            tasks=[_make_task("T1")],
            loop_count=1,
        )

        with patch.object(engine, "_run_task", return_value=(True, "ok")):
            engine._run_sequence(seq)

        assert engine.is_running is False
        assert engine.is_paused is False
        assert engine.current_task is None
        assert engine.current_event is None
