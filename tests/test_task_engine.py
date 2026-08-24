"""测试任务引擎"""
import pytest
import time
from unittest.mock import Mock, patch, MagicMock, call
from core.task_engine import TaskEngine
from models.event import Event, EventType
from models.task import Task


class TestTaskEngine:
    """任务引擎测试类"""

    def test_task_engine_initialization(self):
        """测试任务引擎初始化"""
        engine = TaskEngine()
        assert engine.current_task is None
        assert engine.is_running is False
        assert not engine.is_paused.is_set()
        assert not engine.should_stop.is_set()
        assert engine._last_result is None
        assert engine._var_context == {}

    # ==================================================================
    # 事件类型执行测试
    # ==================================================================

    @patch('core.task_engine.input_controller')
    @patch('core.window_manager.window_manager')
    def test_click_event_execution(self, mock_window_manager, mock_input_controller):
        """测试点击事件执行"""
        engine = TaskEngine()

        # 模拟窗口已绑定
        mock_window_manager.is_valid.return_value = True
        mock_input_controller.click = Mock(return_value=True)

        event = Event(
            name="测试点击",
            event_type=EventType.CLICK,
            params={"x": 100, "y": 200, "button": "left"}
        )

        success, result = engine._dispatch(event)

        assert success is True
        assert "点击" in result or "click" in result.lower()
        mock_input_controller.click.assert_called_once()

    @patch('core.task_engine.input_controller')
    def test_key_event_execution(self, mock_input_controller):
        """测试键盘事件执行"""
        engine = TaskEngine()

        # 模拟按键方法
        mock_input_controller.press_key = Mock(return_value=True)

        event = Event(
            name="测试按键",
            event_type=EventType.KEY,
            params={"keys": "alt+q"}
        )

        success, result = engine._dispatch(event)

        assert success is True
        assert "按键" in result or "key" in result.lower()
        mock_input_controller.press_key.assert_called_once_with("alt+q")

    @patch('core.task_engine.input_controller')
    def test_key_event_with_text(self, mock_input_controller):
        """测试键盘文本输入事件"""
        engine = TaskEngine()

        # 模拟文本输入方法
        mock_input_controller.type_text = Mock(return_value=True)

        event = Event(
            name="测试文本输入",
            event_type=EventType.KEY,
            params={"text": "hello world"}
        )

        success, result = engine._dispatch(event)

        assert success is True
        assert "文本" in result or "text" in result.lower()
        mock_input_controller.type_text.assert_called_once_with("hello world")

    def test_wait_event_execution(self):
        """测试等待事件执行"""
        engine = TaskEngine()

        # 使用较短的等待时间避免测试过长
        event = Event(
            name="测试等待",
            event_type=EventType.WAIT,
            params={"duration": 0.1}
        )

        start_time = time.time()
        success, result = engine._dispatch(event)
        elapsed = time.time() - start_time

        assert success is True
        assert "等待" in result or "wait" in result.lower()
        assert elapsed >= 0.1  # 验证确实等待了指定时间

    @patch('core.task_engine.image_recognition')
    def test_wait_for_image_event(self, mock_image_recognition):
        """测试等待图像事件"""
        engine = TaskEngine()

        # 模拟图像识别返回成功
        mock_image_recognition.wait_for_template = Mock(
            return_value=((100, 200), 0.95)
        )

        event = Event(
            name="等待图像出现",
            event_type=EventType.WAIT,
            params={
                "duration": 1.0,
                "wait_for_image": True,
                "image_path": "test.png",
                "timeout": 5.0
            }
        )

        success, result = engine._dispatch(event)

        assert success is True
        assert "图像出现" in result or "template" in result.lower()
        mock_image_recognition.wait_for_template.assert_called_once()

    # ==================================================================
    # 重试机制测试
    # ==================================================================

    def test_retry_mechanism_success_after_retry(self):
        """测试重试机制最终成功"""
        engine = TaskEngine()

        # Mock _do_click方法，第一次失败，第二次成功
        with patch.object(engine, '_do_click', side_effect=[False, True]):
            event = Event(
                name="重试测试",
                event_type=EventType.CLICK,
                params={"x": 100, "y": 200},
                on_error="retry",
                max_retries=2,
                retry_interval=0.1
            )

            success, result = engine._dispatch_with_retry(event)

            # 应该在重试后成功
            assert success is True

    def test_retry_mechanism_all_fail(self):
        """测试重试机制全部失败"""
        engine = TaskEngine()

        # Mock _do_click方法，所有尝试都失败
        with patch.object(engine, '_do_click', return_value=False):
            event = Event(
                name="重试失败测试",
                event_type=EventType.CLICK,
                params={"x": -1, "y": -1},  # 无效坐标
                on_error="retry",
                max_retries=2,
                retry_interval=0.1
            )

            success, result = engine._dispatch_with_retry(event)

            # 重试耗尽后失败
            assert success is False

    def test_retry_mechanism_with_exception(self):
        """测试重试机制处理异常"""
        engine = TaskEngine()

        # Mock _do_click方法抛出异常
        with patch.object(engine, '_do_click', side_effect=Exception("点击失败")):
            event = Event(
                name="异常重试测试",
                event_type=EventType.CLICK,
                params={"x": 100, "y": 200},
                on_error="retry",
                max_retries=1,
                retry_interval=0.1
            )

            success, result = engine._dispatch_with_retry(event)

            # 异常情况下应该失败
            assert success is False

    # ==================================================================
    # 异常处理策略测试
    # ==================================================================

    def test_error_strategy_retry(self):
        """测试错误重试策略"""
        engine = TaskEngine()

        # Mock _do_click返回失败
        with patch.object(engine, '_do_click', return_value=False):
            event = Event(
                name="重试策略测试",
                event_type=EventType.CLICK,
                params={"x": -1, "y": -1},
                on_error="retry",
                max_retries=1,
                retry_interval=0.1
            )

            success, result = engine._dispatch_with_retry(event)

            # retry策略：重试耗尽后返回失败
            assert success is False

    def test_error_strategy_skip(self):
        """测试错误跳过策略"""
        engine = TaskEngine()

        # Mock _do_click返回失败
        with patch.object(engine, '_do_click', return_value=False):
            event = Event(
                name="跳过策略测试",
                event_type=EventType.CLICK,
                params={"x": -1, "y": -1},
                on_error="skip"
            )

            success, result = engine._dispatch_with_retry(event)

            # skip策略：跳过视为成功
            assert success is True
            assert "skipped" in result.lower()

    def test_error_strategy_stop(self):
        """测试错误停止策略"""
        engine = TaskEngine()

        # Mock _do_click返回失败
        with patch.object(engine, '_do_click', return_value=False):
            event = Event(
                name="停止策略测试",
                event_type=EventType.CLICK,
                params={"x": -1, "y": -1},
                on_error="stop"
            )

            success, result = engine._dispatch_with_retry(event)

            # stop策略：返回失败，由上层决定停止
            assert success is False

    # ==================================================================
    # 图像识别事件测试
    # ==================================================================

    @patch('core.task_engine.image_recognition')
    @patch('core.task_engine.input_controller')
    @patch('core.window_manager.window_manager')
    @patch('os.path.isfile')
    def test_image_event_with_click(self, mock_isfile, mock_window_manager, mock_input_controller, mock_image_recognition):
        """测试图像识别+点击事件"""
        engine = TaskEngine()

        # 模拟文件存在
        mock_isfile.return_value = True

        # 模拟窗口已绑定
        mock_window_manager.is_valid.return_value = True

        # 模拟图像识别成功
        mock_image_recognition.find_template = Mock(
            return_value=((150, 250), 0.95)
        )
        mock_input_controller.click = Mock(return_value=True)

        event = Event(
            name="图像识别点击",
            event_type=EventType.IMAGE,
            params={
                "template_path": "test.png",
                "threshold": 0.8,
                "action": "click",
                "button": "left"
            }
        )

        success, result = engine._dispatch(event)

        assert success is True
        assert "图像识别" in result or "匹配" in result
        mock_image_recognition.find_template.assert_called_once()
        mock_input_controller.click.assert_called_once()

    @patch('core.task_engine.image_recognition')
    @patch('os.path.isfile')
    def test_image_event_not_found(self, mock_isfile, mock_image_recognition):
        """测试图像识别未找到"""
        engine = TaskEngine()

        # 模拟文件存在但图像未找到
        mock_isfile.return_value = True
        mock_image_recognition.find_template = Mock(
            return_value=(None, 0.0)
        )

        event = Event(
            name="图像未找到",
            event_type=EventType.IMAGE,
            params={
                "template_path": "test.png",
                "threshold": 0.8,
                "action": "click"
            }
        )

        success, result = engine._dispatch(event)

        assert success is False
        assert "未匹配" in result or "未找到" in result or "未解析" in result

    # ==================================================================
    # 函数调用事件测试
    # ==================================================================

    @patch('core.task_engine.task_library')
    def test_function_call_event(self, mock_task_library):
        """测试函数调用事件"""
        engine = TaskEngine()

        # 模拟函数调用成功
        mock_task_library.call_function = Mock(
            return_value=(True, {"result": "success"}, None)
        )

        event = Event(
            name="函数调用测试",
            event_type=EventType.FUNCTION,
            params={
                "module": "test_module",
                "function": "test_function",
                "args": [],
                "kwargs": {}
            }
        )

        success, result = engine._dispatch(event)

        assert success is True
        assert result == {"result": "success"}
        mock_task_library.call_function.assert_called_once()

    @patch('core.task_engine.task_library')
    def test_function_call_with_args(self, mock_task_library):
        """测试带参数的函数调用"""
        engine = TaskEngine()

        # 模拟函数调用成功
        mock_task_library.call_function = Mock(
            return_value=(True, {"coord": [100, 200]}, None)
        )

        event = Event(
            name="带参数的函数调用",
            event_type=EventType.FUNCTION,
            params={
                "module": "map_module",
                "function": "navigate",
                "args": [100, 200],
                "kwargs": {"speed": "fast"}
            }
        )

        success, result = engine._dispatch(event)

        assert success is True
        mock_task_library.call_function.assert_called_once()

    # ==================================================================
    # 条件分支事件测试
    # ==================================================================

    def test_condition_simple_true_branch(self):
        """测试condition简单模式true分支"""
        engine = TaskEngine()

        # 设置变量上下文
        engine._last_result = {"status": "success"}

        condition_event = Event(
            name="条件判断",
            event_type=EventType.CONDITION,
            params={
                "mode": "simple",
                "variable": "last_result",
                "operator": "==",
                "value": {"status": "success"},
                "true_branch": [
                    {
                        "name": "成功分支",
                        "event_type": "click",
                        "params": {"x": 100, "y": 100}
                    }
                ],
                "false_branch": [
                    {
                        "name": "失败分支",
                        "event_type": "click",
                        "params": {"x": 200, "y": 200}
                    }
                ]
            }
        )

        with patch.object(engine, '_execute_event_with_depth') as mock_exec:
            mock_exec.return_value = (True, "executed")
            success, result = engine._execute_condition(condition_event)

            assert success is True
            assert result.get("condition") is True

    def test_condition_simple_false_branch(self):
        """测试condition简单模式false分支"""
        engine = TaskEngine()

        # 设置变量上下文
        engine._last_result = {"status": "failed"}

        condition_event = Event(
            name="条件判断",
            event_type=EventType.CONDITION,
            params={
                "mode": "simple",
                "variable": "last_result",
                "operator": "==",
                "value": {"status": "success"},
                "true_branch": [],
                "false_branch": [
                    {
                        "name": "失败分支",
                        "event_type": "click",
                        "params": {"x": 200, "y": 200}
                    }
                ]
            }
        )

        with patch.object(engine, '_execute_event_with_depth') as mock_exec:
            mock_exec.return_value = (True, "executed")
            success, result = engine._execute_condition(condition_event)

            assert success is True
            assert result.get("condition") is False

    # ==================================================================
    # 模板变量解析测试
    # ==================================================================

    def test_resolve_template_params(self):
        """测试模板变量解析"""
        engine = TaskEngine()

        # 设置变量上下文
        engine._last_result = {"target_coord": [100, 200]}
        engine._var_context = {"JHRW": {"location": "长安城"}}

        # 测试解析完整变量
        params = {"x": "${result.target_coord.0}", "y": "${result.target_coord.1}"}
        resolved = engine._resolve_template_params(params)

        assert resolved["x"] == 100
        assert resolved["y"] == 200

    def test_resolve_value_nested_access(self):
        """测试嵌套变量访问"""
        engine = TaskEngine()

        # 设置嵌套结构
        engine._last_result = {
            "target_coord": [150, 250],
            "location": {
                "name": "长安城",
                "level": 50
            }
        }

        # 测试数组索引访问
        val1 = engine._resolve_value("result.target_coord.0")
        assert val1 == 150

        # 测试字典键访问
        val2 = engine._resolve_value("result.location.name")
        assert val2 == "长安城"

        # 测试嵌套访问
        val3 = engine._resolve_value("result.location.level")
        assert val3 == 50

    # ==================================================================
    # 统一点击逻辑测试
    # ==================================================================

    @patch('core.task_engine.input_controller')
    @patch('core.window_manager.window_manager')
    def test_do_click_left(self, mock_window_manager, mock_input_controller):
        """测试左键点击"""
        engine = TaskEngine()

        # 模拟窗口已绑定
        mock_window_manager.is_valid.return_value = True
        mock_input_controller.click = Mock(return_value=True)

        result = engine._do_click((100, 200), "left", 0.0)

        assert result is True
        mock_input_controller.click.assert_called_once()

    @patch('core.task_engine.input_controller')
    @patch('core.window_manager.window_manager')
    def test_do_click_right(self, mock_window_manager, mock_input_controller):
        """测试右键点击（2026-08-05：统一走 click(button='right') 以透传 press_delay）"""
        engine = TaskEngine()

        # 模拟窗口已绑定
        mock_window_manager.is_valid.return_value = True
        mock_input_controller.click = Mock(return_value=True)

        result = engine._do_click((150, 250), "right", 0.0)

        assert result is True
        mock_input_controller.click.assert_called_once()
        # 右键必须带 button="right" 和默认 press_delay
        args, kwargs = mock_input_controller.click.call_args
        assert kwargs.get("button") == "right"
        assert "press_delay" in kwargs

    @patch('core.task_engine.input_controller')
    @patch('core.window_manager.window_manager')
    def test_do_click_double(self, mock_window_manager, mock_input_controller):
        """测试双击"""
        engine = TaskEngine()

        # 模拟窗口已绑定
        mock_window_manager.is_valid.return_value = True
        mock_input_controller.double_click = Mock(return_value=True)

        result = engine._do_click((200, 300), "double", 0.0)

        assert result is True
        mock_input_controller.double_click.assert_called_once()

    @patch('core.window_manager.window_manager')
    def test_do_click_window_not_bound(self, mock_window_manager):
        """测试窗口未绑定时的点击"""
        engine = TaskEngine()

        # 模拟窗口未绑定
        mock_window_manager.is_valid.return_value = False

        result = engine._do_click((100, 200), "left", 0.0)

        # 应该返回False,表示点击失败
        assert result is False

    # ==================================================================
    # 控制流测试
    # ==================================================================

    def test_pause_and_resume(self):
        """测试暂停和恢复"""
        engine = TaskEngine()

        # 设置引擎为运行状态
        engine.is_running = True

        # 初始状态
        assert not engine.is_paused.is_set()

        # 暂停
        engine.pause()
        assert engine.is_paused.is_set()

        # 恢复
        engine.resume()
        assert not engine.is_paused.is_set()

    def test_stop(self):
        """测试停止"""
        engine = TaskEngine()
        engine.is_running = True

        engine.stop()

        assert engine.should_stop.is_set()
        assert not engine.is_paused.is_set()

    def test_interruptible_sleep(self):
        """测试可中断睡眠"""
        engine = TaskEngine()

        # 正常睡眠
        start = time.time()
        engine._interruptible_sleep(0.1)
        elapsed = time.time() - start
        assert elapsed >= 0.1

        # 停止信号中断睡眠
        engine.should_stop.set()
        start = time.time()
        engine._interruptible_sleep(1.0)
        elapsed = time.time() - start
        assert elapsed < 0.5  # 应该立即返回

    # ==================================================================
    # 边界情况测试
    # ==================================================================

    def test_disabled_event(self):
        """测试禁用的事件"""
        engine = TaskEngine()

        event = Event(
            name="禁用事件",
            event_type=EventType.CLICK,
            params={"x": 100, "y": 200},
            enabled=False
        )

        success, result = engine._execute_event(event)

        # 禁用事件应该被跳过
        assert success is True
        assert result == "skipped"

    def test_invalid_event_type(self):
        """测试无效的事件类型"""
        engine = TaskEngine()

        # Event类会将无效类型降级为CLICK
        event = Event(
            name="无效事件",
            event_type="invalid_type",
            params={}
        )

        # 验证事件类型被降级为CLICK
        assert event.event_type == EventType.CLICK

        # 执行时会使用默认参数
        success, result = engine._dispatch(event)

    def test_empty_params(self):
        """测试空参数"""
        engine = TaskEngine()

        event = Event(
            name="空参数事件",
            event_type=EventType.CLICK,
            params={}
        )

        # 空参数应该使用默认值
        success, result = engine._dispatch(event)

        # 即使参数为空也应该执行（使用默认值）
        # 具体行为取决于实现

    def test_max_retries_zero(self):
        """测试重试次数为0"""
        engine = TaskEngine()

        with patch('core.task_engine.input_controller') as mock_input:
            with patch('core.window_manager.window_manager') as mock_window_manager:
                # 模拟窗口已绑定
                mock_window_manager.is_valid.return_value = True
                mock_input.click = Mock(return_value=False)

                event = Event(
                    name="零重试",
                    event_type=EventType.CLICK,
                    params={"x": 100, "y": 200},
                    on_error="retry",
                    max_retries=0
                )

                success, result = engine._dispatch_with_retry(event)

                # 应该只执行1次（初始尝试）
                assert mock_input.click.call_count == 1