# -*- coding: utf-8 -*-
"""
YOLO 目标检测模块。

提供 ``YoloDetector`` 类（单例模式），负责：
    - 加载 ultralytics YOLO 模型（.pt 文件）
    - 对屏幕截图或指定图像进行目标检测
    - 按类别筛选检测结果
    - 查找置信度最高的目标
    - 检测目标并点击其中心点

依赖：
    - ultralytics（可选依赖，未安装时所有检测方法优雅降级为返回空结果）
    - core.screen_capture.screen_capture（截图）
    - core.input_controller.input_controller（点击，延迟导入避免循环依赖）
    - config.config.config（读取模型路径与置信度阈值）
    - utils.logger.logger（日志）

坐标约定：
    - 所有返回的 ``bbox`` / ``center`` 均为 **客户区坐标**（左上角为 0,0）
    - 这是因为 ``screen_capture.capture()`` 截取的就是客户区图像，
      YOLO 输出的像素坐标天然就是客户区坐标系

使用方式::

    from core.yolo_detector import yolo_detector

    if yolo_detector.load_model("models/best.pt"):
        results = yolo_detector.detect()
        target = yolo_detector.find_best_target("npc")
        if target:
            yolo_detector.detect_and_click("npc")
"""
import os
import threading

# 尝试导入 ultralytics，未安装时置为 None，后续方法优雅降级
# 这样即使 ultralytics 未安装，模块仍可导入，仅检测功能不可用
try:
    from ultralytics import YOLO
    _ULTRALYTICS_AVAILABLE = True
    _IMPORT_ERROR = None
except ImportError as _e:
    YOLO = None
    _ULTRALYTICS_AVAILABLE = False
    _IMPORT_ERROR = _e

from config.config import config
from utils.logger import logger
from core.screen_capture import screen_capture


class YoloDetector:
    """
    YOLO 目标检测器（单例模式）。

    通过 ``_instance`` 与 ``_lock`` 实现线程安全的单例。
    使用时直接 ``from core.yolo_detector import yolo_detector`` 即可拿到全局实例。

    属性：
        model: ultralytics.YOLO 模型实例，未加载时为 None
        model_path: str，当前加载的模型路径，未加载时为空字符串
        is_loaded: bool，模型是否已成功加载
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        # 线程安全的单例实现
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        # 仅初始化一次
        if getattr(self, "_initialized", False):
            return
        # 模型实例与状态
        self.model = None
        self.model_path = ""
        self.is_loaded = False
        self._initialized = True

    # ------------------------------------------------------------------
    # 模型加载
    # ------------------------------------------------------------------
    def load_model(self, model_path=None) -> bool:
        """
        加载 YOLO 模型（.pt 文件）。

        :param model_path: 模型文件路径，为 None 时从 config 读取
                           ``recognition.yolo_model_path``
        :return: bool，是否加载成功

        失败情况（均返回 False 并记录错误日志）：
            - ultralytics 未安装
            - model_path 为空字符串
            - 模型文件不存在
            - YOLO 构造抛出异常
        """
        # 1. 检查 ultralytics 是否可用
        if not _ULTRALYTICS_AVAILABLE:
            logger.error(
                f"ultralytics 未安装，无法加载 YOLO 模型（原因: {_IMPORT_ERROR}）"
            )
            return False

        # 2. 确定模型路径：参数优先，否则读 config
        if model_path is None:
            model_path = config.get("recognition.yolo_model_path", "")

        # 3. 校验路径非空
        if not model_path:
            logger.error(
                "YOLO 模型路径为空，无法加载"
                "（请在 config 中设置 recognition.yolo_model_path）"
            )
            return False

        # 4. 校验文件存在
        if not os.path.isfile(model_path):
            logger.error(f"YOLO 模型文件不存在: {model_path}")
            return False

        # 5. 加载模型
        try:
            logger.info(f"正在加载 YOLO 模型: {model_path}")
            self.model = YOLO(model_path)
            self.model_path = model_path
            self.is_loaded = True
            logger.info(f"YOLO 模型加载成功: {model_path}")
            return True
        except Exception as e:
            # 加载失败时清理状态，避免残留半初始化的模型
            logger.exception(f"YOLO 模型加载失败: {model_path}，异常: {e}")
            self.model = None
            self.model_path = ""
            self.is_loaded = False
            return False

    # ------------------------------------------------------------------
    # 检测核心
    # ------------------------------------------------------------------
    def detect(self, image=None, confidence=None) -> list:
        """
        对图像进行目标检测。

        :param image: BGR numpy 数组，为 None 时调用 ``screen_capture.capture()`` 截图
        :param confidence: 置信度阈值，为 None 时从 config 读取
                           ``recognition.yolo_confidence``
        :return: 检测结果列表，按置信度降序排列。每个元素为::

            {
                "class": str,                       # 类别名
                "confidence": float,                # 置信度
                "bbox": (x1, y1, x2, y2),           # 左上右下，客户区坐标
                "center": (cx, cy)                  # 中心点，客户区坐标
            }

            模型未加载且自动加载失败、截图失败、推理失败或无检测结果时返回空列表。
        """
        # 1. 确保模型已加载；未加载则尝试自动加载
        if not self.is_loaded or self.model is None:
            logger.warning("模型未加载，尝试自动加载")
            if not self.load_model():
                logger.error("模型自动加载失败，detect 返回空列表")
                return []

        # 二次保护：load_model 成功标志为 True 但 model 仍为 None 的极端情况
        if self.model is None:
            logger.error("模型实例为 None，无法执行检测")
            return []

        # 2. 获取图像：参数优先，否则截图
        if image is None:
            image = screen_capture.capture()
            if image is None:
                logger.error("截图失败（窗口未绑定或截图异常），detect 返回空列表")
                return []

        # 3. 确定置信度阈值：参数优先，否则读 config
        if confidence is None:
            confidence = config.get("recognition.yolo_confidence", 0.5)
        # 防御性处理：阈值非法时回退默认值
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            logger.warning(f"置信度阈值非法: {confidence!r}，回退为 0.5")
            confidence = 0.5

        # 4. 执行推理
        try:
            # verbose=False 关闭 ultralytics 默认的推理日志输出
            results = self.model(image, conf=confidence, verbose=False)
        except Exception as e:
            logger.exception(f"YOLO 推理失败: {e}")
            return []

        # 5. 解析结果
        detections = self._parse_results(results)
        return detections

    def _parse_results(self, results) -> list:
        """
        解析 ultralytics 推理结果为标准字典列表。

        :param results: ``model(...)`` 返回的结果列表
        :return: 检测结果列表，按置信度降序排列
        """
        detections = []
        try:
            for result in results:
                boxes = result.boxes
                if boxes is None:
                    continue
                # boxes.cls: tensor[N]   类别索引
                # boxes.conf: tensor[N]  置信度
                # boxes.xyxy: tensor[N,4] 左上右下坐标
                cls_tensor = boxes.cls
                conf_tensor = boxes.conf
                xyxy_tensor = boxes.xyxy

                # 类别名映射：{idx: name}
                names = result.names if hasattr(result, "names") else {}

                n = len(cls_tensor)
                for i in range(n):
                    cls_idx = int(cls_tensor[i].item())
                    conf = float(conf_tensor[i].item())
                    x1 = float(xyxy_tensor[i][0].item())
                    y1 = float(xyxy_tensor[i][1].item())
                    x2 = float(xyxy_tensor[i][2].item())
                    y2 = float(xyxy_tensor[i][3].item())
                    # 类别名：优先用 names 映射，否则退化为索引字符串
                    cls_name = names.get(cls_idx, str(cls_idx))
                    cx = (x1 + x2) / 2.0
                    cy = (y1 + y2) / 2.0
                    detections.append({
                        "class": cls_name,
                        "confidence": conf,
                        "bbox": (int(x1), int(y1), int(x2), int(y2)),
                        "center": (int(cx), int(cy)),
                    })
        except Exception as e:
            logger.exception(f"解析 YOLO 结果失败: {e}")
            return []

        # 按置信度降序排列
        detections.sort(key=lambda d: d["confidence"], reverse=True)
        return detections

    # ------------------------------------------------------------------
    # 类别筛选
    # ------------------------------------------------------------------
    def detect_class(self, target_class, confidence=None) -> list:
        """
        只返回指定类别的检测结果。

        :param target_class: 目标类别名（字符串），需与模型训练时的类别名一致
        :param confidence: 置信度阈值，为 None 时从 config 读取
        :return: 检测结果列表，格式同 ``detect``，按置信度降序排列
        """
        if target_class is None:
            # target_class 为 None 时退化为返回全部结果，并给出警告
            logger.warning("detect_class 的 target_class 为 None，返回全部检测结果")
            return self.detect(confidence=confidence)

        all_detections = self.detect(confidence=confidence)
        # 类别名按字符串相等匹配
        filtered = [d for d in all_detections if d["class"] == target_class]
        # detect 已按置信度降序，过滤后顺序保持
        return filtered

    # ------------------------------------------------------------------
    # 最佳目标
    # ------------------------------------------------------------------
    def find_best_target(self, target_class=None, confidence=None):
        """
        返回置信度最高的目标。

        :param target_class: 目标类别名，为 None 时不限类别
        :param confidence: 置信度阈值，为 None 时从 config 读取
        :return: dict，格式为 ``{"class", "confidence", "bbox", "center"}``；
                 无检测结果时返回 None
        """
        if target_class is None:
            detections = self.detect(confidence=confidence)
        else:
            detections = self.detect_class(target_class, confidence=confidence)
        if not detections:
            return None
        # detect / detect_class 已按置信度降序，取第一个即最佳
        return detections[0]

    # ------------------------------------------------------------------
    # 检测并点击
    # ------------------------------------------------------------------
    def detect_and_click(self, target_class=None, confidence=None, button="left") -> bool:
        """
        检测目标并点击最佳目标的中心点。

        内部流程：检测 -> 取置信度最高目标 -> 调用
        ``input_controller.click(center_x, center_y, button)``。

        :param target_class: 目标类别名，为 None 时不限类别
        :param confidence: 置信度阈值，为 None 时从 config 读取
        :param button: 鼠标按钮，"left" / "right" / "middle"
        :return: bool，是否成功检测并点击
        """
        target = self.find_best_target(
            target_class=target_class, confidence=confidence
        )
        if target is None:
            logger.warning(
                f"未检测到目标（class={target_class!r}, button={button!r}），无法点击"
            )
            return False

        cx, cy = target["center"]

        # 延迟导入 input_controller 避免循环依赖
        try:
            from core.input_controller import input_controller
        except ImportError as e:
            logger.error(f"无法导入 input_controller: {e}")
            return False

        try:
            input_controller.click(cx, cy, button=button)
            logger.info(
                f"已点击目标 class={target['class']!r} "
                f"conf={target['confidence']:.3f} "
                f"center=({cx},{cy}) button={button!r}"
            )
            return True
        except Exception as e:
            logger.exception(f"点击失败: {e}")
            return False


# 模块级单例实例，供全局使用
yolo_detector = YoloDetector()
