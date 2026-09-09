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

from PyQt5.QtCore import pyqtSignal
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
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from config.config import config
from core.window_manager import window_manager
from utils.logger import logger

# 默认登录点击坐标序列（客户区坐标，1000×600 基准），沿用 core/relogin.DEFAULT_CLICK_POINTS
from core.relogin import DEFAULT_CLICK_POINTS as _DEFAULT_RELOGIN_POINTS


class ConfigPanel(QWidget):
    """
    配置面板：可视化编辑 settings.json 中的各项配置。

    通过 ``_load_config_to_ui`` 将 config 加载到界面控件，
    通过 ``_save_ui_to_config`` 将界面控件值写回 config。
    """

    # ★2026-09-01 定时重登：请求立即执行重登（由主窗口负责停/启任务与线程）
    relogin_requested = pyqtSignal()

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
        "relogin": {
            "enabled": False,
            "interval_min": 180,          # 定时重登间隔（分钟）
            "client_path": "",            # 游戏客户端 exe 路径（GUI 自定义）
            "click_points": _DEFAULT_RELOGIN_POINTS,  # 登录点击坐标序列（客户区）
            "click_gap": 1.2,             # 相邻点击间隔（秒）——压缩到 1 分钟内登录
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
        # 3. 定时重登组
        layout.addWidget(self._build_relogin_group())
        # 4. 按钮行
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
    # 定时重登组（2026-09-01）
    # ------------------------------------------------------------------
    def _build_relogin_group(self) -> QGroupBox:
        """构建"定时重登"分组：启用/间隔/客户端路径/登录坐标序列/立即重登。"""
        group = QGroupBox("定时重新登录")
        v = QVBoxLayout(group)
        v.setSpacing(6)

        # 启用 + 间隔
        sw = QHBoxLayout()
        self.relogin_enabled_check = QCheckBox("启用定时重新登录")
        self.relogin_enabled_check.setToolTip(
            "到点自动重启游戏客户端并自动登录（先停任务，登录完成后自动恢复运行）")
        sw.addWidget(self.relogin_enabled_check)
        sw.addSpacing(12)
        sw.addWidget(QLabel("间隔(分钟):"))
        self.relogin_interval_spin = QSpinBox()
        # ★2026-09-02 测试友好：最小 1 分钟（原 10 分钟起步，测定时不方便）
        self.relogin_interval_spin.setRange(1, 43200)
        self.relogin_interval_spin.setSuffix(" 分")
        sw.addWidget(self.relogin_interval_spin)
        sw.addStretch(1)
        v.addLayout(sw)

        # 客户端路径（GUI 自定义窗口）
        path_row = QHBoxLayout()
        path_row.addWidget(QLabel("客户端 exe:"))
        self.relogin_client_edit = QLineEdit()
        self.relogin_client_edit.setPlaceholderText(
            r"如 G:\00\快乐西游.exe 或多开器路径（重启时启动它）")
        path_row.addWidget(self.relogin_client_edit, 1)
        self.btn_browse_client = QPushButton("浏览")
        self.btn_browse_client.clicked.connect(self._on_browse_client)
        path_row.addWidget(self.btn_browse_client)
        v.addLayout(path_row)

        # 登录点击序列（可编辑，每行一个坐标 x,y）
        lbl = QLabel(
            "登录点击坐标（客户区坐标，每行一个 x,y，按顺序单击；"
            "默认 5 步：向导下一步→登录→下一步→选择角色→进入游戏）：")
        lbl.setWordWrap(True)
        v.addWidget(lbl)
        self.relogin_points_edit = QPlainTextEdit()
        self.relogin_points_edit.setMaximumHeight(110)
        self.relogin_points_edit.setPlaceholderText(
            "701,550\n507,420\n705,549\n635,284\n699,571")
        v.addWidget(self.relogin_points_edit)

        # 立即重登按钮
        btn_row = QHBoxLayout()
        self.btn_relogin_now = QPushButton("🔁 立即重新登录")
        self.btn_relogin_now.setToolTip(
            "立即杀旧客户端→启动新客户端→按上面坐标自动点击登录→网关重连→恢复任务")
        self.btn_relogin_now.clicked.connect(self._on_relogin_now)
        btn_row.addWidget(self.btn_relogin_now)
        btn_row.addStretch(1)
        v.addLayout(btn_row)

        return group

    # ------------------------------------------------------------------
    # 文件浏览回调
    # ------------------------------------------------------------------
    def _on_browse_client(self):
        """浏览选择游戏客户端 exe 文件。"""
        cur = self.relogin_client_edit.text().strip()
        start_dir = os.path.dirname(cur) if cur else r"G:\00"
        path, _ = QFileDialog.getOpenFileName(
            self, "选择游戏客户端程序", start_dir,
            "游戏程序 (*.exe);;所有文件 (*.*)",
        )
        if path:
            self.relogin_client_edit.setText(path)

    def _on_relogin_now(self):
        """立即重登：读 UI 配置→通知主窗口执行（主窗口负责停/启任务与后台线程）。"""
        logger.info("配置面板：用户点击立即重新登录")
        try:
            self._save_ui_to_config()
            config.save()
        except Exception as e:
            logger.error(f"保存重登配置失败: {e}")
        self.relogin_requested.emit()

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

        # -------- 定时重登 --------
        self.relogin_enabled_check.setChecked(
            bool(config.get("relogin.enabled", False))
        )
        self.relogin_interval_spin.setValue(
            int(config.get("relogin.interval_min", 180))
        )
        self.relogin_client_edit.setText(
            str(config.get("relogin.client_path", ""))
        )
        pts = config.get("relogin.click_points", _DEFAULT_RELOGIN_POINTS)
        try:
            lines = [f"{int(x)},{int(y)}" for x, y in (pts or [])]
        except Exception:
            lines = [f"{x},{y}" for x, y in _DEFAULT_RELOGIN_POINTS]
        self.relogin_points_edit.setPlainText("\n".join(lines))

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

        # -------- 定时重登 --------
        config.set("relogin.enabled", self.relogin_enabled_check.isChecked())
        config.set("relogin.interval_min", self.relogin_interval_spin.value())
        config.set("relogin.client_path", self.relogin_client_edit.text().strip())
        points = []
        for line in self.relogin_points_edit.toPlainText().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                x, y = [int(v) for v in line.replace("，", ",").split(",")[:2]]
                points.append([x, y])
            except Exception:
                continue
        config.set("relogin.click_points", points or _DEFAULT_RELOGIN_POINTS)

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
