"""pytest配置文件，定义共享fixtures"""
import pytest
import sys
import os

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def sample_event():
    """示例事件fixture"""
    from models.event import Event, EventType
    return Event(
        event_type=EventType.CLICK,
        params={"x": 100, "y": 200, "click_type": "left"},
        max_retries=3
    )


@pytest.fixture
def sample_task():
    """示例任务fixture"""
    from models.task import Task
    return Task(name="测试任务")


@pytest.fixture
def temp_task_file(tmp_path):
    """临时任务文件fixture"""
    task_file = tmp_path / "test_task.json"
    task_file.write_text('{"name": "测试任务", "events": []}')
    return task_file


@pytest.fixture
def mock_window():
    """模拟窗口fixture"""
    class MockWindow:
        def __init__(self):
            self.left = 100
            self.top = 100
            self.width = 800
            self.height = 600
            self.title = "Test Window"

        def activate(self):
            pass

    return MockWindow()