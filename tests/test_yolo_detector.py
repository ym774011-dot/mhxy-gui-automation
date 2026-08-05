# -*- coding: utf-8 -*-
"""YOLO检测器功能测试模块。

测试 YoloDetector 单例类的功能，包括：
- 单例模式验证
- 模型加载（成功/失败场景）
- 目标检测（有/无模型）
- 检测结果解析
- 类别筛选
- 最佳目标查找
- 检测并点击
"""
import pytest
import numpy as np
from unittest.mock import Mock, patch, MagicMock
from core.yolo_detector import YoloDetector, yolo_detector


class TestYOLODetector:
    """YOLO检测器测试类。"""

    def setup_method(self):
        """每个测试方法执行前的设置。"""
        # 重置单例状态，确保测试隔离
        YoloDetector._instance = None
        self.detector = YoloDetector()

    def test_singleton_pattern(self):
        """测试单例模式。"""
        detector1 = YoloDetector()
        detector2 = YoloDetector()

        # 验证是同一个实例
        assert detector1 is detector2
        assert id(detector1) == id(detector2)

    def test_initial_state(self):
        """测试初始状态。"""
        assert self.detector.model is None
        assert self.detector.model_path == ""
        assert self.detector.is_loaded is False

    @patch('core.yolo_detector.YOLO')
    @patch('core.yolo_detector._ULTRALYTICS_AVAILABLE', True)
    @patch('os.path.isfile', return_value=True)
    def test_load_model_success(self, mock_isfile, mock_yolo):
        """测试模型加载成功。"""
        mock_model = Mock()
        mock_yolo.return_value = mock_model

        result = self.detector.load_model("model.pt")

        assert result is True
        assert self.detector.model is not None
        assert self.detector.model_path == "model.pt"
        assert self.detector.is_loaded is True
        mock_yolo.assert_called_once_with("model.pt")

    @patch('core.yolo_detector._ULTRALYTICS_AVAILABLE', False)
    def test_load_model_without_ultralytics(self):
        """测试ultralytics未安装时的模型加载。"""
        result = self.detector.load_model("model.pt")

        assert result is False
        assert self.detector.model is None
        assert self.detector.is_loaded is False

    @patch('core.yolo_detector.YOLO')
    @patch('core.yolo_detector._ULTRALYTICS_AVAILABLE', True)
    @patch('os.path.isfile', return_value=False)
    def test_load_model_file_not_found(self, mock_isfile, mock_yolo):
        """测试模型文件不存在时的加载。"""
        result = self.detector.load_model("invalid.pt")

        assert result is False
        assert self.detector.model is None
        assert self.detector.is_loaded is False
        mock_yolo.assert_not_called()

    @patch('core.yolo_detector.YOLO')
    @patch('core.yolo_detector._ULTRALYTICS_AVAILABLE', True)
    @patch('os.path.isfile', return_value=True)
    def test_load_model_failure(self, mock_isfile, mock_yolo):
        """测试模型加载失败。"""
        mock_yolo.side_effect = Exception("模型文件损坏")

        result = self.detector.load_model("corrupted.pt")

        assert result is False
        assert self.detector.model is None
        assert self.detector.model_path == ""
        assert self.detector.is_loaded is False

    @patch('core.yolo_detector.YOLO')
    @patch('core.yolo_detector._ULTRALYTICS_AVAILABLE', True)
    @patch('os.path.isfile', return_value=True)
    def test_load_model_with_config_path(self, mock_isfile, mock_yolo):
        """测试从config读取模型路径。"""
        mock_model = Mock()
        mock_yolo.return_value = mock_model

        with patch('core.yolo_detector.config.get', return_value="config_model.pt"):
            result = self.detector.load_model()

            assert result is True
            mock_yolo.assert_called_once_with("config_model.pt")

    @patch('core.yolo_detector.YOLO')
    @patch('core.yolo_detector._ULTRALYTICS_AVAILABLE', True)
    @patch('os.path.isfile', return_value=True)
    def test_detect_with_model(self, mock_isfile, mock_yolo):
        """测试有模型时的检测。"""
        # 设置模型已加载
        mock_model = Mock()
        mock_result = Mock()
        mock_result.boxes = Mock()
        mock_result.boxes.cls = []
        mock_result.boxes.conf = []
        mock_result.boxes.xyxy = []
        mock_result.names = {}
        mock_model.return_value = [mock_result]

        self.detector.model = mock_model
        self.detector.is_loaded = True

        screenshot = np.zeros((100, 100, 3), dtype=np.uint8)
        results = self.detector.detect(screenshot)

        assert isinstance(results, list)

    def test_detect_without_model(self):
        """测试无模型时的检测。"""
        # 模型未加载时，detect会尝试自动加载
        # 这里mock load_model返回False
        with patch.object(self.detector, 'load_model', return_value=False):
            screenshot = np.zeros((100, 100, 3), dtype=np.uint8)
            results = self.detector.detect(screenshot)

            assert results == []

    @patch('core.yolo_detector.YOLO')
    @patch('core.yolo_detector._ULTRALYTICS_AVAILABLE', True)
    @patch('os.path.isfile', return_value=True)
    def test_detect_parse_results(self, mock_isfile, mock_yolo):
        """测试检测结果解析。"""
        # Mock tensor数据
        mock_cls_tensor = MagicMock()
        mock_cls_tensor.__len__ = Mock(return_value=1)
        mock_cls_tensor.__getitem__ = Mock(return_value=MagicMock(item=Mock(return_value=0)))

        mock_conf_tensor = MagicMock()
        mock_conf_tensor.__len__ = Mock(return_value=1)
        mock_conf_tensor.__getitem__ = Mock(return_value=MagicMock(item=Mock(return_value=0.95)))

        mock_xyxy_tensor = MagicMock()
        mock_xyxy_tensor.__len__ = Mock(return_value=1)
        mock_xyxy_tensor.__getitem__ = Mock(return_value=[
            MagicMock(item=Mock(return_value=100)),
            MagicMock(item=Mock(return_value=200)),
            MagicMock(item=Mock(return_value=150)),
            MagicMock(item=Mock(return_value=250))
        ])

        mock_boxes = Mock()
        mock_boxes.cls = mock_cls_tensor
        mock_boxes.conf = mock_conf_tensor
        mock_boxes.xyxy = mock_xyxy_tensor

        mock_result = Mock()
        mock_result.boxes = mock_boxes
        mock_result.names = {0: "npc"}

        mock_model = Mock()
        mock_model.return_value = [mock_result]

        self.detector.model = mock_model
        self.detector.is_loaded = True

        screenshot = np.zeros((300, 300, 3), dtype=np.uint8)
        results = self.detector.detect(screenshot)

        assert len(results) > 0
        assert 'class' in results[0]
        assert 'confidence' in results[0]
        assert 'bbox' in results[0]
        assert 'center' in results[0]
        assert results[0]['class'] == 'npc'
        assert results[0]['confidence'] == 0.95

    @patch('core.yolo_detector.YOLO')
    @patch('core.yolo_detector._ULTRALYTICS_AVAILABLE', True)
    @patch('os.path.isfile', return_value=True)
    def test_detect_class(self, mock_isfile, mock_yolo):
        """测试类别筛选。"""
        # 模拟多个检测结果
        mock_model = Mock()

        # 创建多个检测结果
        def create_detection(cls_idx, conf, x1, y1, x2, y2, cls_name):
            mock_cls_tensor = MagicMock()
            mock_cls_tensor.__len__ = Mock(return_value=1)
            mock_cls_tensor.__getitem__ = Mock(return_value=MagicMock(item=Mock(return_value=cls_idx)))

            mock_conf_tensor = MagicMock()
            mock_conf_tensor.__len__ = Mock(return_value=1)
            mock_conf_tensor.__getitem__ = Mock(return_value=MagicMock(item=Mock(return_value=conf)))

            mock_xyxy_tensor = MagicMock()
            mock_xyxy_tensor.__getitem__ = Mock(return_value=[
                MagicMock(item=Mock(return_value=x1)),
                MagicMock(item=Mock(return_value=y1)),
                MagicMock(item=Mock(return_value=x2)),
                MagicMock(item=Mock(return_value=y2))
            ])
            mock_xyxy_tensor.__len__ = Mock(return_value=1)

            mock_boxes = Mock()
            mock_boxes.cls = mock_cls_tensor
            mock_boxes.conf = mock_conf_tensor
            mock_boxes.xyxy = mock_xyxy_tensor

            mock_result = Mock()
            mock_result.boxes = mock_boxes
            mock_result.names = {cls_idx: cls_name}
            return mock_result

        # 创建两个类别的检测结果
        result1 = create_detection(0, 0.9, 10, 10, 50, 50, "npc")
        result2 = create_detection(1, 0.85, 100, 100, 150, 150, "monster")

        mock_model.return_value = [result1, result2]
        self.detector.model = mock_model
        self.detector.is_loaded = True

        screenshot = np.zeros((200, 200, 3), dtype=np.uint8)

        # 测试筛选npc类别
        npc_results = self.detector.detect_class("npc", confidence=0.5)
        assert all(r['class'] == 'npc' for r in npc_results)

        # 测试筛选monster类别
        monster_results = self.detector.detect_class("monster", confidence=0.5)
        assert all(r['class'] == 'monster' for r in monster_results)

    @patch('core.yolo_detector.YOLO')
    @patch('core.yolo_detector._ULTRALYTICS_AVAILABLE', True)
    @patch('os.path.isfile', return_value=True)
    def test_find_best_target(self, mock_isfile, mock_yolo):
        """测试查找最佳目标。"""
        # 模拟多个检测结果，不同置信度
        mock_cls_tensor = MagicMock()
        mock_cls_tensor.__len__ = Mock(return_value=2)
        mock_cls_tensor.__getitem__ = Mock(side_effect=[
            MagicMock(item=Mock(return_value=0)),
            MagicMock(item=Mock(return_value=0))
        ])

        mock_conf_tensor = MagicMock()
        mock_conf_tensor.__len__ = Mock(return_value=2)
        mock_conf_tensor.__getitem__ = Mock(side_effect=[
            MagicMock(item=Mock(return_value=0.95)),
            MagicMock(item=Mock(return_value=0.85))
        ])

        mock_xyxy_tensor = MagicMock()
        mock_xyxy_tensor.__len__ = Mock(return_value=2)

        mock_boxes = Mock()
        mock_boxes.cls = mock_cls_tensor
        mock_boxes.conf = mock_conf_tensor
        mock_boxes.xyxy = mock_xyxy_tensor

        mock_result = Mock()
        mock_result.boxes = mock_boxes
        mock_result.names = {0: "npc"}

        mock_model = Mock()
        mock_model.return_value = [mock_result]

        self.detector.model = mock_model
        self.detector.is_loaded = True

        screenshot = np.zeros((200, 200, 3), dtype=np.uint8)

        # 手动构建检测结果来测试find_best_target
        with patch.object(self.detector, 'detect', return_value=[
            {'class': 'npc', 'confidence': 0.95, 'bbox': (10, 10, 50, 50), 'center': (30, 30)},
            {'class': 'npc', 'confidence': 0.85, 'bbox': (100, 100, 150, 150), 'center': (125, 125)}
        ]):
            best = self.detector.find_best_target()
            assert best is not None
            assert best['confidence'] == 0.95

    def test_find_best_target_empty(self):
        """测试无检测结果时的最佳目标查找。"""
        with patch.object(self.detector, 'detect', return_value=[]):
            best = self.detector.find_best_target()
            assert best is None

    @patch('core.yolo_detector.YOLO')
    @patch('core.yolo_detector._ULTRALYTICS_AVAILABLE', True)
    @patch('os.path.isfile', return_value=True)
    def test_detect_and_click_success(self, mock_isfile, mock_yolo):
        """测试检测并点击成功。"""
        self.detector.model = Mock()
        self.detector.is_loaded = True

        mock_target = {
            'class': 'npc',
            'confidence': 0.95,
            'bbox': (100, 100, 150, 150),
            'center': (125, 125)
        }

        with patch.object(self.detector, 'find_best_target', return_value=mock_target), \
             patch('core.input_controller.input_controller.click') as mock_click:

            result = self.detector.detect_and_click("npc")

            assert result is True
            mock_click.assert_called_once_with(125, 125, button="left")

    @patch('core.yolo_detector.YOLO')
    @patch('core.yolo_detector._ULTRALYTICS_AVAILABLE', True)
    @patch('os.path.isfile', return_value=True)
    def test_detect_and_click_right_button(self, mock_isfile, mock_yolo):
        """测试右键点击。"""
        self.detector.model = Mock()
        self.detector.is_loaded = True

        mock_target = {
            'class': 'npc',
            'confidence': 0.95,
            'bbox': (100, 100, 150, 150),
            'center': (125, 125)
        }

        with patch.object(self.detector, 'find_best_target', return_value=mock_target), \
             patch('core.input_controller.input_controller.click') as mock_click:

            result = self.detector.detect_and_click("npc", button="right")

            assert result is True
            mock_click.assert_called_once_with(125, 125, button="right")

    def test_detect_and_click_no_target(self):
        """测试未检测到目标时的点击。"""
        with patch.object(self.detector, 'find_best_target', return_value=None):
            result = self.detector.detect_and_click("npc")
            assert result is False

    @patch('core.yolo_detector.YOLO')
    @patch('core.yolo_detector._ULTRALYTICS_AVAILABLE', True)
    @patch('os.path.isfile', return_value=True)
    def test_detect_with_none_image(self, mock_isfile, mock_yolo):
        """测试图像参数为None时的检测（使用截图）。"""
        mock_model = Mock()
        mock_result = Mock()
        mock_result.boxes = Mock()
        mock_result.boxes.cls = []
        mock_result.boxes.conf = []
        mock_result.boxes.xyxy = []
        mock_result.names = {}
        mock_model.return_value = [mock_result]

        self.detector.model = mock_model
        self.detector.is_loaded = True

        with patch('core.yolo_detector.screen_capture.capture', return_value=np.zeros((100, 100, 3), dtype=np.uint8)):
            results = self.detector.detect()
            assert isinstance(results, list)

    @patch('core.yolo_detector.YOLO')
    @patch('core.yolo_detector._ULTRALYTICS_AVAILABLE', True)
    @patch('os.path.isfile', return_value=True)
    def test_detect_with_custom_confidence(self, mock_isfile, mock_yolo):
        """测试自定义置信度阈值。"""
        mock_model = Mock()
        mock_result = Mock()
        mock_result.boxes = Mock()
        mock_result.boxes.cls = []
        mock_result.boxes.conf = []
        mock_result.boxes.xyxy = []
        mock_result.names = {}
        mock_model.return_value = [mock_result]

        self.detector.model = mock_model
        self.detector.is_loaded = True

        screenshot = np.zeros((100, 100, 3), dtype=np.uint8)
        self.detector.detect(screenshot, confidence=0.8)

        # 验证模型调用时传入了正确的置信度
        mock_model.assert_called_once()
        call_args = mock_model.call_args
        assert call_args[1]['conf'] == 0.8

    @patch('core.yolo_detector.YOLO')
    @patch('core.yolo_detector._ULTRALYTICS_AVAILABLE', True)
    @patch('os.path.isfile', return_value=True)
    def test_detect_class_with_none_target(self, mock_isfile, mock_yolo):
        """测试target_class为None时的类别筛选（返回全部结果）。"""
        self.detector.model = Mock()
        self.detector.is_loaded = True

        mock_detections = [
            {'class': 'npc', 'confidence': 0.9, 'bbox': (10, 10, 50, 50), 'center': (30, 30)},
            {'class': 'monster', 'confidence': 0.85, 'bbox': (100, 100, 150, 150), 'center': (125, 125)}
        ]

        with patch.object(self.detector, 'detect', return_value=mock_detections):
            results = self.detector.detect_class(None)
            assert len(results) == 2

    @patch('core.yolo_detector.YOLO')
    @patch('core.yolo_detector._ULTRALYTICS_AVAILABLE', True)
    @patch('os.path.isfile', return_value=True)
    def test_model_inference_exception(self, mock_isfile, mock_yolo):
        """测试模型推理异常处理。"""
        mock_model = Mock()
        mock_model.side_effect = Exception("推理失败")
        self.detector.model = mock_model
        self.detector.is_loaded = True

        screenshot = np.zeros((100, 100, 3), dtype=np.uint8)
        results = self.detector.detect(screenshot)

        # 推理失败应返回空列表
        assert results == []

    def test_empty_model_path(self):
        """测试空模型路径。"""
        result = self.detector.load_model("")
        assert result is False

    def test_results_sorted_by_confidence(self):
        """测试检测结果按置信度降序排列。"""
        # 直接测试 _parse_results 方法
        # 使用更简单的方式模拟 tensor

        def create_mock_tensor_item(value):
            """创建模拟的 tensor item 对象"""
            mock = MagicMock()
            mock.item.return_value = value
            return mock

        # 创建模拟的检测结果（未排序）
        detection_data = [
            (0, 0.7, [10, 10, 50, 50]),
            (0, 0.95, [100, 100, 150, 150]),
            (0, 0.85, [200, 200, 250, 250])
        ]

        # 创建可索引的 mock 列表
        class MockTensorList:
            """模拟 tensor 列表"""
            def __init__(self, items):
                self._items = items

            def __len__(self):
                return len(self._items)

            def __getitem__(self, index):
                return self._items[index]

        # Mock cls tensor
        cls_items = [create_mock_tensor_item(d[0]) for d in detection_data]

        # Mock conf tensor
        conf_items = [create_mock_tensor_item(d[1]) for d in detection_data]

        # Mock xyxy tensor - 每个元素是一个包含 4 个 tensor 的列表
        xyxy_items = [
            [create_mock_tensor_item(v) for v in d[2]]
            for d in detection_data
        ]

        mock_boxes = Mock()
        mock_boxes.cls = MockTensorList(cls_items)
        mock_boxes.conf = MockTensorList(conf_items)
        mock_boxes.xyxy = MockTensorList(xyxy_items)

        mock_result = Mock()
        mock_result.boxes = mock_boxes
        mock_result.names = {0: "npc"}

        # 调用 _parse_results 方法
        results = self.detector._parse_results([mock_result])

        # 验证结果已按置信度降序排列
        assert len(results) == 3
        assert results[0]['confidence'] == 0.95
        assert results[1]['confidence'] == 0.85
        assert results[2]['confidence'] == 0.7

    @patch('core.yolo_detector.YOLO')
    @patch('core.yolo_detector._ULTRALYTICS_AVAILABLE', True)
    @patch('os.path.isfile', return_value=True)
    def test_detect_with_invalid_confidence(self, mock_isfile, mock_yolo):
        """测试非法置信度阈值的处理。"""
        mock_model = Mock()
        mock_result = Mock()
        mock_result.boxes = Mock()
        mock_result.boxes.cls = []
        mock_result.boxes.conf = []
        mock_result.boxes.xyxy = []
        mock_result.names = {}
        mock_model.return_value = [mock_result]

        self.detector.model = mock_model
        self.detector.is_loaded = True

        screenshot = np.zeros((100, 100, 3), dtype=np.uint8)

        # 测试非法置信度（字符串）
        self.detector.detect(screenshot, confidence="invalid")

        # 应该回退到默认值0.5
        call_args = mock_model.call_args
        assert call_args[1]['conf'] == 0.5