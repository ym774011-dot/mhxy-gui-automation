# -*- coding: utf-8 -*-
"""
MHXY GUI 自动化脚本平台 - 配置面板（Task 14）。

本模块实现 ``ConfigPanel(QWidget)``，作为主窗口的第 4 个标签页（"配置"），
提供对 settings.json 中各项配置的可视化编辑能力。

布局（垂直，使用 QGroupBox 分组）：
    1. 窗口配置组：
       - 窗口标题输入框 + 绑定按钮
       - 进程 PID 输入框（QSpinBox 0-99999）+ 绑定按钮
       - 输入模式选择（前台 / 后台）
       - 窗口状态显示标签
    2. 识别参数组：
       - 模板匹配阈值（0.0-1.0，步长 0.05）
       - YOLO 置信度阈值（0.0-1.0，步长 0.05）
       - YOLO 模型路径（+ 浏览按钮，选择 .pt 文件）
       - 截图间隔（0.1-10.0 秒，步长 0.1）
    3. 日志配置组：
       - 日志级别（DEBUG/INFO/WARNING/ERROR）
       - 日志文件路径（+ 浏览按钮）
    4. 按钮行：保存配置 / 重新加载 / 恢复默认

核心交互：
    - 通过 ``config`` 单例读写 settings.json
    - 通过 ``window_manager`` 单例绑定目标窗口
"""
import os

from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from config.config import config
from core.window_manager import window_manager
from utils.logger import logger


class ConfigPanel(QWidget):
    """
    配置面板：可视化编辑 settings.json 中的各项配置。

    通过 ``_load_config_to_ui`` 将 config 加载到界面控件，
    通过 ``_save_ui_to_config`` 将界面控件值写回 config。
    """

    # ==================================================================
    # 默认配置（供"恢复默认"使用）
    # ==================================================================
    # 注意：window.pid 默认为 0，保存时会被转换为 null（未设置）
    _DEFAULTS = {
        "window": {
            "title": "",
            "pid": 0,
            "input_mode": "background",
        },
        "recognition": {
            "template_threshold": 0.8,
            "yolo_confidence": 0.5,
            "yolo_model_path": "",
            "screenshot_interval": 0.5,
        },
        "logging": {
            "level": "INFO",
            "file_path": "logs/automation.log",
            "auto_clean_days": 7,
        },
    }

    # ==================================================================
    # 初始化
    # ==================================================================
    def __init__(self, parent=None):
        super().__init__(parent)
        # 构建 UI
        self._init_ui()
        # 加载当前配置到界面
        self._load_config_to_ui()
        logger.info("配置面板初始化完成")

    # ==================================================================
    # UI 构建
    # ==================================================================
    def _init_ui(self):
        """构建整体 UI：识别参数组 + 日志配置组 + 按钮行。"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # 1. 识别参数组
        layout.addWidget(self._build_recognition_group())
        # 2. 日志配置组
        layout.addWidget(self._build_logging_group())
        # 3. 按钮行
        layout.addLayout(self._build_button_row())
        # 弹性底部空间，让配置组顶部对齐
        layout.addStretch(1)

    # ------------------------------------------------------------------
    # 识别参数组
    # ------------------------------------------------------------------
    def _build_recognition_group(self) -> QGroupBox:
        """构建"识别参数"分组。"""
        group = QGroupBox("识别参数")
        v = QVBoxLayout(group)
        v.setSpacing(6)

        # 模板匹配阈值
        tpl_row = QHBoxLayout()
        tpl_row.addWidget(QLabel("模板匹配阈值:"))
        self.template_threshold_spin = QDoubleSpinBox()
        self.template_threshold_spin.setRange(0.0, 1.0)
        self.template_threshold_spin.setSingleStep(0.05)
        self.template_threshold_spin.setDecimals(2)
        tpl_row.addWidget(self.template_threshold_spin, 1)
        v.addLayout(tpl_row)

        # YOLO 置信度阈值
        yolo_row = QHBoxLayout()
        yolo_row.addWidget(QLabel("YOLO 置信度:"))
        self.yolo_confidence_spin = QDoubleSpinBox()
        self.yolo_confidence_spin.setRange(0.0, 1.0)
        self.yolo_confidence_spin.setSingleStep(0.05)
        self.yolo_confidence_spin.setDecimals(2)
        yolo_row.addWidget(self.yolo_confidence_spin, 1)
        v.addLayout(yolo_row)

        # YOLO 模型路径
        model_row = QHBoxLayout()
        model_row.addWidget(QLabel("YOLO 模型:"))
        self.yolo_model_edit = QLineEdit()
        self.yolo_model_edit.setPlaceholderText("选择 .pt 模型文件路径")
        model_row.addWidget(self.yolo_model_edit, 1)
        self.btn_browse_model = QPushButton("浏览")
        self.btn_browse_model.clicked.connect(self._on_browse_model)
        model_row.addWidget(self.btn_browse_model)
        v.addLayout(model_row)

        # 截图间隔
        interval_row = QHBoxLayout()
        interval_row.addWidget(QLabel("截图间隔(秒):"))
        self.screenshot_interval_spin = QDoubleSpinBox()
        self.screenshot_interval_spin.setRange(0.1, 10.0)
        self.screenshot_interval_spin.setSingleStep(0.1)
        self.screenshot_interval_spin.setDecimals(2)
        interval_row.addWidget(self.screenshot_interval_spin, 1)
        v.addLayout(interval_row)

        return group

    # ------------------------------------------------------------------
    # 日志配置组
    # ------------------------------------------------------------------
    def _build_logging_group(self) -> QGroupBox:
        """构建"日志配置"分组。"""
        group = QGroupBox("日志配置")
        v = QVBoxLayout(group)
        v.setSpacing(6)

        # 日志级别
        level_row = QHBoxLayout()
        level_row.addWidget(QLabel("日志级别:"))
        self.log_level_combo = QComboBox()
        self.log_level_combo.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        level_row.addWidget(self.log_level_combo, 1)
        v.addLayout(level_row)

        # 日志文件路径
        path_row = QHBoxLayout()
        path_row.addWidget(QLabel("日志文件:"))
        self.log_file_edit = QLineEdit()
        self.log_file_edit.setPlaceholderText("日志文件路径（如 logs/automation.log）")
        path_row.addWidget(self.log_file_edit, 1)
        self.btn_browse_log = QPushButton("浏览")
        self.btn_browse_log.clicked.connect(self._on_browse_log)
        path_row.addWidget(self.btn_browse_log)
        v.addLayout(path_row)

        # 自动清理天数（0 = 禁用）
        clean_row = QHBoxLayout()
        clean_row.addWidget(QLabel("自动清理(天):"))
        self.auto_clean_spin = QSpinBox()
        self.auto_clean_spin.setRange(0, 365)
        self.auto_clean_spin.setSpecialValueText("禁用")
        self.auto_clean_spin.setSuffix(" 天")
        clean_row.addWidget(self.auto_clean_spin, 1)
        v.addLayout(clean_row)

        return group

    # ------------------------------------------------------------------
    # 按钮行
    # ------------------------------------------------------------------
    def _build_button_row(self) -> QHBoxLayout:
        """构建底部按钮行：保存配置 / 重新加载 / 恢复默认。"""
        row = QHBoxLayout()
        # 右对齐：先放弹性空间
        row.addStretch(1)

        self.btn_save = QPushButton("保存配置")
        self.btn_save.clicked.connect(self._on_save)
        row.addWidget(self.btn_save)

        self.btn_reload = QPushButton("重新加载")
        self.btn_reload.clicked.connect(self._on_reload)
        row.addWidget(self.btn_reload)

        self.btn_reset = QPushButton("恢复默认")
        self.btn_reset.clicked.connect(self._on_reset)
        row.addWidget(self.btn_reset)

        return row

    # ==================================================================
    # 配置 <-> UI 同步
    # ==================================================================
    def _load_config_to_ui(self):
        """从 config 单例读取值，加载到界面控件。"""
        # -------- 识别参数 --------
        self.template_threshold_spin.setValue(
            float(config.get("recognition.template_threshold", 0.8))
        )
        self.yolo_confidence_spin.setValue(
            float(config.get("recognition.yolo_confidence", 0.5))
        )
        self.yolo_model_edit.setText(
            str(config.get("recognition.yolo_model_path", ""))
        )
        self.screenshot_interval_spin.setValue(
            float(config.get("recognition.screenshot_interval", 0.5))
        )

        # -------- 日志配置 --------
        level = str(config.get("logging.level", "INFO"))
        idx = self.log_level_combo.findText(level)
        self.log_level_combo.setCurrentIndex(idx if idx >= 0 else 1)
        self.log_file_edit.setText(
            str(config.get("logging.file_path", "logs/automation.log"))
        )
        self.auto_clean_spin.setValue(
            int(config.get("logging.auto_clean_days", 7))
        )

    def _save_ui_to_config(self):
        """从界面控件读取值，写入 config 单例（内存，不落盘）。"""
        # -------- 识别参数 --------
        config.set(
            "recognition.template_threshold",
            round(self.template_threshold_spin.value(), 4),
        )
        config.set(
            "recognition.yolo_confidence",
            round(self.yolo_confidence_spin.value(), 4),
        )
        config.set(
            "recognition.yolo_model_path", self.yolo_model_edit.text().strip()
        )
        config.set(
            "recognition.screenshot_interval",
            round(self.screenshot_interval_spin.value(), 4),
        )

        # -------- 日志配置 --------
        config.set("logging.level", self.log_level_combo.currentText())
        config.set("logging.file_path", self.log_file_edit.text().strip())
        config.set("logging.auto_clean_days", self.auto_clean_spin.value())

    # ==================================================================
    # 文件浏览回调
    # ==================================================================
    def _on_browse_model(self):
        """浏览选择 YOLO 模型文件（.pt）。"""
        # 默认目录：当前已填路径所在目录，否则项目根目录
        cur = self.yolo_model_edit.text().strip()
        start_dir = os.path.dirname(cur) if cur else config.project_root
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 YOLO 模型文件", start_dir,
            "YOLO 模型 (*.pt);;所有文件 (*.*)",
        )
        if path:
            self.yolo_model_edit.setText(path)

    def _on_browse_log(self):
        """浏览选择日志文件路径（保存对话框，允许选择新文件）。"""
        cur = self.log_file_edit.text().strip()
        start_dir = os.path.dirname(cur) if cur else config.project_root
        path, _ = QFileDialog.getSaveFileName(
            self, "选择日志文件", start_dir,
            "日志文件 (*.log);;所有文件 (*.*)",
        )
        if path:
            self.log_file_edit.setText(path)

    # ==================================================================
    # 按钮行回调
    # ==================================================================
    def _on_save(self):
        """保存配置：UI -> config -> settings.json。"""
        logger.info("配置面板：用户请求保存配置")
        try:
            self._save_ui_to_config()
            ok = config.save()
            if ok:
                logger.info("配置已保存到 settings.json")
                QMessageBox.information(self, "保存配置", "配置已保存。")
            else:
                QMessageBox.warning(self, "保存配置", "配置保存失败。")
        except Exception as e:
            logger.error(f"保存配置异常: {e}")
            QMessageBox.critical(self, "保存配置", f"保存配置异常：\n{e}")

    def _on_reload(self):
        """重新加载：从 settings.json 重新加载并刷新界面。"""
        logger.info("配置面板：用户请求重新加载配置")
        try:
            config.load()
            self._load_config_to_ui()
            QMessageBox.information(self, "重新加载", "配置已重新加载。")
        except Exception as e:
            logger.error(f"重新加载配置异常: {e}")
            QMessageBox.critical(self, "重新加载", f"重新加载配置异常：\n{e}")

    def _on_reset(self):
        """
        恢复默认：将默认值写入 config 内存并刷新界面。

        注意：不立即落盘，需用户点击"保存配置"才会持久化到 settings.json，
        避免误操作覆盖现有配置。
        """
        logger.info("配置面板：用户请求恢复默认配置")
        reply = QMessageBox.question(
            self, "恢复默认",
            "将界面配置重置为默认值（不会立即写文件，"
            "需点击\"保存配置\"持久化）。是否继续？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        try:
            # 将默认值写入 config 内存
            self._apply_defaults_to_config()
            # 同步到界面
            self._load_config_to_ui()
            QMessageBox.information(
                self, "恢复默认",
                "已恢复默认配置。请点击\"保存配置\"以持久化到 settings.json。",
            )
        except Exception as e:
            logger.error(f"恢复默认配置异常: {e}")
            QMessageBox.critical(self, "恢复默认", f"恢复默认配置异常：\n{e}")

    # ==================================================================
    # 辅助方法
    # ==================================================================
    def _apply_defaults_to_config(self):
        """将默认配置写入 config 内存（点分路径写入）。"""
        for section, items in self._DEFAULTS.items():
            for k, v in items.items():
                config.set(f"{section}.{k}", v)
