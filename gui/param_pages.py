# -*- coding: utf-8 -*-
"""
事件参数页策略模式实现（event_editor 上帝类拆分 PR #8 收口）。

将 ``EventEditorDialog`` 中按事件类型散落的「参数页构建 / 加载 / 写回」三类方法，
收敛为统一的 ``BaseParamPage`` 策略接口。每个事件类型对应一个 ``ParamPage`` 子类，
自行持有控件引用；对话框只负责按事件类型路由到对应页面实例、提供跨页共享辅助方法。

设计要点：
    - 页面通过 ``host`` 引用访问 dialog 级共享辅助方法（``_on_browse_file`` /
      ``_on_browse_dir`` / ``_get_previous_function_events`` / ``_set_combo_by_data`` /
      ``_try_parse_value``），不复制 dialog 状态；
    - ``page.widget`` 即构建出的 ``QWidget``（image 页为 ``QScrollArea``），
      由 dialog 加入 ``QStackedWidget``；
    - ``load(params)`` / ``apply(event)`` 与旧 ``_load_*_params`` / ``_apply_*_params``
      签名一致，行为完全等价，只是控件引用从 dialog 迁到了各自页面实例上。
"""
from __future__ import annotations

import json
import os
import functools
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, List, Optional

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from models.event import Event, EventType
from utils.logger import logger
from config.config import config

# 子流程编辑器（独立模块，避免与 event_editor 形成循环导入）
from gui.subflow_editor import SubFlowEditorDialog

if TYPE_CHECKING:  # 仅用于类型标注，避免运行时循环导入
    from gui.event_editor import EventEditorDialog

# 尝试导入 task_library 单例；导入失败时使用 None，函数页会优雅降级
try:
    from core.task_library_manager import task_library
except Exception:  # pragma: no cover - 依赖缺失时的兜底
    task_library = None


def _legacy_case_to_event(case: dict) -> Event:
    """
    将旧格式（单动作）switch case 升级为一个 Event，便于在子流程模式下编辑。

    - click / 默认        -> CLICK 事件
    - file_lookup         -> 退化为 CLICK 并告警（旧格式无对应事件类型，
                              请在编辑器中重新配置"从坐标文件查找"语义）

    :param case: 旧格式 case 字典（含 action/x/y/button/delay）
    :return: 对应的 Event 实例
    """
    action = str(case.get("action", "click") or "click").lower()
    x = case.get("x")
    y = case.get("y")
    button = str(case.get("button", "left") or "left")
    delay = case.get("delay", 0) or 0

    if action == "file_lookup":
        logger.warning(
            "switch case 旧格式 file_lookup 已升级为子流程模式，"
            "请在编辑器中重新配置坐标文件查找"
        )
        return Event(
            name="坐标文件查找(已废弃-请重配)",
            event_type=EventType.CLICK,
            params={"x": 0, "y": 0, "button": "left"},
        )

    try:
        xv = int(x) if x is not None else 0
    except (TypeError, ValueError):
        xv = 0
    try:
        yv = int(y) if y is not None else 0
    except (TypeError, ValueError):
        yv = 0
    try:
        dv = float(delay) / 1000.0 if delay else 0.5
    except (TypeError, ValueError):
        dv = 0.5

    return Event(
        name=f"点击 ({xv},{yv})",
        event_type=EventType.CLICK,
        params={"x": xv, "y": yv, "button": button},
        post_delay=dv,
    )


class BaseParamPage(ABC):
    """参数页策略基类。

    dialog 在 ``_build_params_group`` 中按事件类型实例化各页面，
    并把 ``page.widget`` 加入 ``QStackedWidget``；加载/写回时按事件类型
    调 ``page.load(params)`` / ``page.apply(event)``。

    :param host: 宿主 ``EventEditorDialog`` 实例，用于访问 dialog 级共享辅助方法。
    """

    def __init__(self, host: "EventEditorDialog") -> None:
        self.host = host
        self.widget: QWidget = self.build()

    @abstractmethod
    def build(self) -> QWidget:
        """构建并返回该事件类型的参数页控件（控件引用存于 ``self``）。"""
        ...

    @abstractmethod
    def load(self, params: dict) -> None:
        """将 ``params`` 加载到本页控件。"""
        ...

    @abstractmethod
    def apply(self, event: Event) -> bool:
        """将本页控件值写回 ``event.params``，返回是否成功。"""
        ...


class ClickParamPage(BaseParamPage):
    """鼠标点击参数页（已从 EventEditorDialog 抽出，PR #8 收口）。"""

    def build(self) -> QWidget:
        """鼠标点击参数页：X / Y + 承接参数快速选择器。"""
        page = QWidget()
        form = QFormLayout(page)
        form.setLabelAlignment(Qt.AlignRight)

        self._click_x_edit = QLineEdit()
        self._click_x_edit.setPlaceholderText("整数或 ${变量}，如 100 或 ${result.x}")
        form.addRow("X 坐标：", self._click_x_edit)

        self._click_y_edit = QLineEdit()
        self._click_y_edit.setPlaceholderText("整数或 ${变量}，如 200 或 ${result.y}")
        form.addRow("Y 坐标：", self._click_y_edit)

        self._click_button_combo = QComboBox()
        self._click_button_combo.addItem("左键单击", "left")
        self._click_button_combo.addItem("右键单击", "right")
        self._click_button_combo.addItem("双击", "double")
        form.addRow("点击类型：", self._click_button_combo)

        self._click_background_check = QCheckBox("后台点击（不激活窗口）")
        form.addRow("", self._click_background_check)

        # —— 点击验证（2026-08-18 像素颜色对比确认点击生效）——
        verify_group = QGroupBox("点击验证（颜色对比确认生效）")
        verify_layout = QFormLayout(verify_group)

        self._click_verify_check = QCheckBox(
            "启用验证：点击后验证点颜色变化才算成功，未变自动重试"
        )
        verify_layout.addRow("", self._click_verify_check)

        probe_row = QHBoxLayout()
        self._click_probe_x_edit = QLineEdit()
        self._click_probe_x_edit.setPlaceholderText("验证点 X（整数或 ${变量}）")
        probe_row.addWidget(self._click_probe_x_edit, 1)
        self._click_probe_y_edit = QLineEdit()
        self._click_probe_y_edit.setPlaceholderText("验证点 Y（整数或 ${变量}）")
        probe_row.addWidget(self._click_probe_y_edit, 1)
        self._click_probe_fill_btn = QPushButton("=点击点")
        self._click_probe_fill_btn.setToolTip("验证点设为点击点坐标（仅调试用，见下方说明）")
        self._click_probe_fill_btn.clicked.connect(self._fill_probe_from_click)
        probe_row.addWidget(self._click_probe_fill_btn)
        verify_layout.addRow("验证点：", probe_row)

        self._click_verify_retries_spin = QSpinBox()
        self._click_verify_retries_spin.setRange(0, 10)
        self._click_verify_retries_spin.setValue(3)
        verify_layout.addRow("失败重试次数：", self._click_verify_retries_spin)

        self._click_verify_threshold_spin = QSpinBox()
        self._click_verify_threshold_spin.setRange(1, 441)
        self._click_verify_threshold_spin.setValue(30)
        verify_layout.addRow("颜色变化阈值：", self._click_verify_threshold_spin)

        verify_hint = QLabel(
            "验证点应选「点击后颜色会持久变化」的位置（弹出的对话框 / NPC 气泡 /\n"
            "按钮高亮区）。不要用点击点本身：按下会高亮、释放后恢复原色，会误判。"
        )
        verify_hint.setStyleSheet("color: #666; font-size: 10px;")
        verify_hint.setWordWrap(True)
        verify_layout.addRow("", verify_hint)

        form.addRow(verify_group)

        # —— 承接参数：列出前序函数调用事件 ——
        form.addRow(QLabel(""))
        inherit_group = QGroupBox("承接参数（从前序函数调用结果中取值）")
        inherit_layout = QVBoxLayout(inherit_group)

        # 获取前序函数调用事件
        func_events = self.host._get_previous_function_events()

        if not func_events:
            no_event_label = QLabel(
                "暂无前置函数调用事件。\n"
                "请先在当前任务中添加「函数调用」事件。"
            )
            no_event_label.setStyleSheet("color: #999; font-size: 11px;")
            no_event_label.setWordWrap(True)
            inherit_layout.addWidget(no_event_label)
        else:
            # 事件选择 + 字段选择
            row1 = QHBoxLayout()
            row1.addWidget(QLabel("来源事件："))
            self._click_source_combo = QComboBox()
            self._click_source_combo.setMinimumWidth(150)
            for evt in func_events:
                label = f"{evt.name or '未命名'} (var={evt.var_name or 'auto'})"
                self._click_source_combo.addItem(label, evt)
            row1.addWidget(self._click_source_combo, 1)

            row1.addWidget(QLabel("字段："))
            self._click_field_combo = QComboBox()
            self._click_field_combo.setMinimumWidth(140)
            self._click_field_combo.addItem("目标坐标 X", "target_coord.0")
            self._click_field_combo.addItem("目标坐标 Y", "target_coord.1")
            self._click_field_combo.addItem("目标地点", "target_location")
            self._click_field_combo.addItem("进度数值", "progress_num")
            self._click_field_combo.addItem("自定义...", "__custom__")
            row1.addWidget(self._click_field_combo, 1)

            self._click_field_combo.currentIndexChanged.connect(
                self._on_click_field_changed
            )

            self._click_fill_x_btn = QPushButton("填入 X")
            self._click_fill_x_btn.clicked.connect(lambda: self._fill_click_coord("x"))
            row1.addWidget(self._click_fill_x_btn)

            self._click_fill_y_btn = QPushButton("填入 Y")
            self._click_fill_y_btn.clicked.connect(lambda: self._fill_click_coord("y"))
            row1.addWidget(self._click_fill_y_btn)

            inherit_row1 = QWidget()
            inherit_row1.setLayout(row1)
            inherit_layout.addWidget(inherit_row1)

            # 一键填入坐标对
            row2 = QHBoxLayout()
            self._click_fill_xy_btn = QPushButton(
                "一键填入坐标 (X=coord.0, Y=coord.1)"
            )
            self._click_fill_xy_btn.setStyleSheet(
                "QPushButton { background: #E3F2FD; padding: 6px; }"
            )
            self._click_fill_xy_btn.clicked.connect(self._fill_click_coord_xy)
            row2.addWidget(self._click_fill_xy_btn)
            inherit_row2 = QWidget()
            inherit_row2.setLayout(row2)
            inherit_layout.addWidget(inherit_row2)

            # 自定义字段
            self._click_custom_field_edit = QLineEdit()
            self._click_custom_field_edit.setPlaceholderText(
                "自定义字段，如 custom_field 或 nested.key"
            )
            self._click_custom_field_edit.setVisible(False)
            inherit_layout.addWidget(self._click_custom_field_edit)

        inherit_container = QWidget()
        inherit_container_layout = QVBoxLayout(inherit_container)
        inherit_container_layout.setContentsMargins(0, 0, 0, 0)
        inherit_container_layout.addWidget(inherit_group)
        form.addRow("", inherit_container)

        # —— 位置数据容器快捷选择 ——
        form.addRow(QLabel(""))
        location_group = QGroupBox("位置数据容器（从函数调用结果中提取的位置）")
        location_layout = QVBoxLayout(location_group)

        # 地图选择
        loc_row1 = QHBoxLayout()
        loc_row1.addWidget(QLabel("地图："))
        self._loc_map_combo = QComboBox()
        self._loc_map_combo.setMinimumWidth(150)
        self._loc_map_combo.addItem("江南野外", "江南野外")
        self._loc_map_combo.addItem("建邺城", "建邺城")
        self._loc_map_combo.addItem("东海湾", "东海湾")
        self._loc_map_combo.setEditable(True)
        loc_row1.addWidget(self._loc_map_combo)
        loc_row1.addStretch()
        location_layout.addLayout(loc_row1)

        # 操作按钮
        loc_row2 = QHBoxLayout()
        self._loc_fill_x_btn = QPushButton("填入 X 坐标")
        self._loc_fill_x_btn.setStyleSheet(
            "QPushButton { background: #4CAF50; color: white; padding: 6px; }"
        )
        self._loc_fill_x_btn.clicked.connect(
            lambda: self._fill_location_coord("x")
        )
        loc_row2.addWidget(self._loc_fill_x_btn)

        self._loc_fill_y_btn = QPushButton("填入 Y 坐标")
        self._loc_fill_y_btn.setStyleSheet(
            "QPushButton { background: #4CAF50; color: white; padding: 6px; }"
        )
        self._loc_fill_y_btn.clicked.connect(
            lambda: self._fill_location_coord("y")
        )
        loc_row2.addWidget(self._loc_fill_y_btn)

        self._loc_fill_xy_btn = QPushButton("填入坐标对 (X, Y)")
        self._loc_fill_xy_btn.setStyleSheet(
            "QPushButton { background: #2196F3; color: white; padding: 6px; }"
        )
        self._loc_fill_xy_btn.clicked.connect(
            self._fill_location_coord_xy
        )
        loc_row2.addWidget(self._loc_fill_xy_btn)

        self._loc_fill_all_btn = QPushButton("填入地图名")
        self._loc_fill_all_btn.setStyleSheet(
            "QPushButton { background: #FF9800; color: white; padding: 6px; }"
        )
        self._loc_fill_all_btn.clicked.connect(
            self._fill_location_name
        )
        loc_row2.addWidget(self._loc_fill_all_btn)

        loc_row2.addStretch()
        location_layout.addLayout(loc_row2)

        # 提示说明
        loc_hint = QLabel(
            "使用方式：选择地图后点击按钮，自动生成 ${location.地图名.x} 模板变量\n"
            "说明：位置数据在函数调用事件执行后自动存入容器"
        )
        loc_hint.setStyleSheet("color: #666; font-size: 10px;")
        loc_hint.setWordWrap(True)
        location_layout.addWidget(loc_hint)

        form.addRow("", location_group)

        return page

    # ------------------------------------------------------------------
    # 前序事件辅助方法
    # ------------------------------------------------------------------
    def _get_selected_source_event(self):
        """获取当前选择的来源事件。"""
        if not hasattr(self, '_click_source_combo'):
            return None
        return self._click_source_combo.currentData()

    def _get_selected_field(self):
        """获取当前选择的字段路径。"""
        if not hasattr(self, '_click_field_combo'):
            return ""
        data = self._click_field_combo.currentData()
        if data == "__custom__":
            return self._click_custom_field_edit.text().strip()
        return data or ""

    def _build_template(self, field_path):
        """根据选择的来源事件和字段构建模板字符串。"""
        src = self._get_selected_source_event()
        if src is None or not field_path:
            return None
        var_name = src.var_name if src.var_name else src.name.replace(" ", "").replace("_", "")
        return f"${{{var_name}.{field_path}}}"

    def _on_click_field_changed(self, index):
        """字段选择变化时显示/隐藏自定义输入框。"""
        if hasattr(self, '_click_custom_field_edit'):
            data = self._click_field_combo.itemData(index)
            self._click_custom_field_edit.setVisible(data == "__custom__")

    def _fill_click_coord(self, target):
        """将选择的承接字段填入 X 或 Y。"""
        field = self._get_selected_field()
        template = self._build_template(field)
        if not template:
            QMessageBox.warning(self.host, "提示", "请先选择来源事件和字段")
            return
        if target == "x":
            self._click_x_edit.setText(template)
        elif target == "y":
            self._click_y_edit.setText(template)

    def _fill_click_coord_xy(self):
        """一键填入坐标对。"""
        src = self._get_selected_source_event()
        if src is None:
            QMessageBox.warning(self.host, "提示", "请先选择来源事件")
            return
        var_name = src.var_name if src.var_name else src.name.replace(" ", "").replace("_", "")
        self._click_x_edit.setText(f"${{{var_name}.target_coord.0}}")
        self._click_y_edit.setText(f"${{{var_name}.target_coord.1}}")

    def _fill_probe_from_click(self) -> None:
        """验证点 = 点击点（复制 X/Y 输入框当前值，含 ${变量} 原样拷贝）。"""
        self._click_probe_x_edit.setText(self._click_x_edit.text())
        self._click_probe_y_edit.setText(self._click_y_edit.text())

    # ------------------------------------------------------------------
    # 位置数据容器辅助方法
    # ------------------------------------------------------------------
    def _get_selected_location_map(self) -> str:
        """获取当前选择的地图名称。"""
        if hasattr(self, '_loc_map_combo'):
            return self._loc_map_combo.currentData() or self._loc_map_combo.currentText()
        return ""

    def _fill_location_coord(self, target: str) -> None:
        """从位置数据容器填入坐标到 X 或 Y 输入框。"""
        map_name = self._get_selected_location_map()
        if not map_name:
            QMessageBox.warning(self.host, "提示", "请先选择地图")
            return
        template = f"${{location.{map_name}.{target}}}"
        if target == "x":
            self._click_x_edit.setText(template)
        elif target == "y":
            self._click_y_edit.setText(template)

    def _fill_location_coord_xy(self) -> None:
        """从位置数据容器填入坐标对 (X, Y)。"""
        map_name = self._get_selected_location_map()
        if not map_name:
            QMessageBox.warning(self.host, "提示", "请先选择地图")
            return
        self._click_x_edit.setText(f"${{location.{map_name}.x}}")
        self._click_y_edit.setText(f"${{location.{map_name}.y}}")

    def _fill_location_name(self) -> None:
        """从位置数据容器填入地图名。"""
        map_name = self._get_selected_location_map()
        if not map_name:
            QMessageBox.warning(self.host, "提示", "请先选择地图")
            return
        template = f"${{location.{map_name}.location}}"
        # 地图名通常用于承接参数或其他文本字段，这里填充到一个提示位置
        QMessageBox.information(
            self.host,
            "模板变量",
            f"地图名模板变量：\n{template}\n\n可复制到需要的地方使用。",
        )

    def load(self, params: dict) -> None:
        """加载鼠标点击参数到控件。X/Y 支持数字或 ${变量} 字符串。"""
        self._click_x_edit.setText(str(params.get("x", 0) or 0))
        self._click_y_edit.setText(str(params.get("y", 0) or 0))
        self.host._set_combo_by_data(
            self._click_button_combo, params.get("button", "left"), "left"
        )
        self._click_background_check.setChecked(bool(params.get("background", False)))
        # 2026-08-18 点击验证参数（旧事件无这些字段 → 默认不验证）
        self._click_verify_check.setChecked(bool(params.get("verify", False)))
        self._click_probe_x_edit.setText(str(params.get("probe_x", 0) or 0))
        self._click_probe_y_edit.setText(str(params.get("probe_y", 0) or 0))
        self._click_verify_retries_spin.setValue(int(params.get("verify_retries", 3)))
        self._click_verify_threshold_spin.setValue(int(params.get("verify_threshold", 30)))

    def apply(self, event: Event) -> bool:
        """将鼠标点击参数写回 Event.params。X/Y 可能是字符串（含模板变量）。"""
        x_text = self._click_x_edit.text().strip()
        y_text = self._click_y_edit.text().strip()

        # 如果不含 ${} 模板变量，尝试转为整数
        def _try_int(text, default=0):
            if "${" in text:
                return text  # 保留模板变量字符串
            try:
                return int(text)
            except (TypeError, ValueError):
                return default

        event.params = {
            "x": _try_int(x_text),
            "y": _try_int(y_text),
            "button": self._click_button_combo.currentData() or "left",
            "background": self._click_background_check.isChecked(),
            # 2026-08-18 点击验证（像素颜色对比确认生效）
            "verify": self._click_verify_check.isChecked(),
            "probe_x": _try_int(self._click_probe_x_edit.text().strip()),
            "probe_y": _try_int(self._click_probe_y_edit.text().strip()),
            "verify_retries": self._click_verify_retries_spin.value(),
            "verify_threshold": self._click_verify_threshold_spin.value(),
        }
        return True


class KeyParamPage(BaseParamPage):
    """键盘输入参数页（已从 EventEditorDialog 抽出，PR #8 收口）。"""

    def build(self) -> QWidget:
        """键盘输入参数页：按键组合 / 输入文本 / 持续时间。"""
        page = QWidget()
        form = QFormLayout(page)
        form.setLabelAlignment(Qt.AlignRight)

        self._key_keys_edit = QLineEdit()
        self._key_keys_edit.setPlaceholderText("如 alt+q, ctrl+c, f1（多个键用 + 连接）")
        form.addRow("按键组合：", self._key_keys_edit)

        self._key_text_edit = QLineEdit()
        self._key_text_edit.setPlaceholderText("需要输入的文本内容")
        form.addRow("输入文本：", self._key_text_edit)

        self._key_duration_spin = QDoubleSpinBox()
        self._key_duration_spin.setRange(0.0, 10.0)
        self._key_duration_spin.setSingleStep(0.1)
        self._key_duration_spin.setDecimals(3)
        self._key_duration_spin.setSuffix(" 秒")
        form.addRow("按键持续时间：", self._key_duration_spin)

        return page

    def load(self, params: dict) -> None:
        """加载键盘输入参数到控件。"""
        self._key_keys_edit.setText(str(params.get("keys", "") or ""))
        self._key_text_edit.setText(str(params.get("text", "") or ""))
        try:
            duration = float(params.get("duration", 0.0) or 0.0)
        except (TypeError, ValueError):
            duration = 0.0
        self._key_duration_spin.setValue(duration)

    def apply(self, event: Event) -> bool:
        """将键盘输入参数写回 Event.params。"""
        event.params = {
            "keys": self._key_keys_edit.text(),
            "text": self._key_text_edit.text(),
            "duration": self._key_duration_spin.value(),
        }
        return True


class WaitParamPage(BaseParamPage):
    """等待延迟参数页（已从 EventEditorDialog 抽出，PR #8 Phase 1）。"""

    def build(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setLabelAlignment(Qt.AlignRight)

        self._wait_duration_spin = QDoubleSpinBox()
        self._wait_duration_spin.setRange(0.0, 86400.0)
        self._wait_duration_spin.setSingleStep(0.1)
        self._wait_duration_spin.setDecimals(3)
        self._wait_duration_spin.setSuffix(" 秒")
        form.addRow("等待时长：", self._wait_duration_spin)

        self._wait_for_image_check = QCheckBox("等待图像出现（否则为纯时长等待）")
        form.addRow("", self._wait_for_image_check)

        # 图像路径：QLineEdit + 浏览按钮
        image_row = QHBoxLayout()
        self._wait_image_edit = QLineEdit()
        self._wait_image_edit.setPlaceholderText("等待图像的路径（可选）")
        image_row.addWidget(self._wait_image_edit, 1)
        browse_btn = QPushButton("浏览...")
        browse_btn.clicked.connect(
            lambda: self.host._on_browse_file(
                self._wait_image_edit,
                "图片 (*.png *.jpg *.bmp *.jpeg);;所有文件 (*.*)",
            )
        )
        image_row.addWidget(browse_btn)
        image_container = QWidget()
        image_container.setLayout(image_row)
        form.addRow("图像路径：", image_container)

        self._wait_timeout_spin = QDoubleSpinBox()
        self._wait_timeout_spin.setRange(0.0, 86400.0)
        self._wait_timeout_spin.setSingleStep(1.0)
        self._wait_timeout_spin.setDecimals(2)
        self._wait_timeout_spin.setSuffix(" 秒")
        form.addRow("超时时间：", self._wait_timeout_spin)

        # 搜索区域（客户区坐标）
        region_row = QHBoxLayout()
        region_row.addWidget(QLabel("X:"))
        self._wait_region_x_spin = QSpinBox()
        self._wait_region_x_spin.setRange(0, 9999)
        region_row.addWidget(self._wait_region_x_spin)
        region_row.addWidget(QLabel("Y:"))
        self._wait_region_y_spin = QSpinBox()
        self._wait_region_y_spin.setRange(0, 9999)
        region_row.addWidget(self._wait_region_y_spin)
        region_row.addWidget(QLabel("宽:"))
        self._wait_region_w_spin = QSpinBox()
        self._wait_region_w_spin.setRange(0, 9999)
        self._wait_region_w_spin.setSpecialValueText("全屏")
        region_row.addWidget(self._wait_region_w_spin)
        region_row.addWidget(QLabel("高:"))
        self._wait_region_h_spin = QSpinBox()
        self._wait_region_h_spin.setRange(0, 9999)
        self._wait_region_h_spin.setSpecialValueText("全屏")
        region_row.addWidget(self._wait_region_h_spin)
        region_row.addStretch()
        self._wait_region_container = QWidget()
        self._wait_region_container.setLayout(region_row)
        form.addRow("搜索区域：", self._wait_region_container)

        return page

    def load(self, params: dict) -> None:
        try:
            duration = float(params.get("duration", 1.0) or 0.0)
        except (TypeError, ValueError):
            duration = 0.0
        self._wait_duration_spin.setValue(duration)
        self._wait_for_image_check.setChecked(bool(params.get("wait_for_image", False)))
        self._wait_image_edit.setText(str(params.get("image_path", "") or ""))
        try:
            timeout = float(params.get("timeout", 10.0) or 0.0)
        except (TypeError, ValueError):
            timeout = 0.0
        self._wait_timeout_spin.setValue(timeout)
        # 搜索区域
        region = params.get("region") or []
        try:
            self._wait_region_x_spin.setValue(int(region[0] or 0))
            self._wait_region_y_spin.setValue(int(region[1] or 0))
            self._wait_region_w_spin.setValue(int(region[2] or 0))
            self._wait_region_h_spin.setValue(int(region[3] or 0))
        except (IndexError, TypeError, ValueError):
            self._wait_region_x_spin.setValue(0)
            self._wait_region_y_spin.setValue(0)
            self._wait_region_w_spin.setValue(0)
            self._wait_region_h_spin.setValue(0)

    def apply(self, event: Event) -> bool:
        event.params = {
            "duration": self._wait_duration_spin.value(),
            "wait_for_image": self._wait_for_image_check.isChecked(),
            "image_path": self._wait_image_edit.text(),
            "timeout": self._wait_timeout_spin.value(),
            "region": [
                self._wait_region_x_spin.value(),
                self._wait_region_y_spin.value(),
                self._wait_region_w_spin.value(),
                self._wait_region_h_spin.value(),
            ],
        }
        return True


class ImageParamPage(BaseParamPage):
    """图像识别参数页（已从 EventEditorDialog 抽出，PR #8 收口）。"""

    def build(self) -> QWidget:
        """
        图像识别参数页：模板路径 / 阈值 / 动作 / 点击类型 / 点击规则。

        支持：
        - 直接指定模板路径
        - 动态构建路径（根据前序函数调用结果自动匹配图片）
        - 目录批量识别（扫描目录下所有图片逐个匹配点击）
        - 自定义点击规则（偏移、次数、间隔、随机偏移）
        """
        page = QWidget()
        form = QFormLayout(page)
        form.setLabelAlignment(Qt.AlignRight)

        # ---- 模板来源选择 ----
        self._image_source_mode_combo = QComboBox()
        self._image_source_mode_combo.addItem("直接指定路径", "direct")
        self._image_source_mode_combo.addItem("动态构建（根据函数调用结果）", "dynamic")
        self._image_source_mode_combo.addItem("目录批量识别（扫描所有图片）", "batch")
        self._image_source_mode_combo.currentIndexChanged.connect(
            self._on_image_source_mode_changed
        )
        form.addRow("模板来源：", self._image_source_mode_combo)

        # ---- 模式 1: 直接指定路径 ----
        self._image_direct_widget = QWidget()
        direct_layout = QHBoxLayout(self._image_direct_widget)
        direct_layout.setContentsMargins(0, 0, 0, 0)
        self._image_template_edit = QLineEdit()
        self._image_template_edit.setPlaceholderText("模板图片路径")
        direct_layout.addWidget(self._image_template_edit, 1)
        browse_btn = QPushButton("浏览...")
        browse_btn.clicked.connect(
            lambda: self.host._on_browse_file(
                self._image_template_edit,
                "图片 (*.png *.jpg *.bmp *.jpeg);;所有文件 (*.*)",
            )
        )
        direct_layout.addWidget(browse_btn)
        form.addRow("模板图片路径：", self._image_direct_widget)

        # ---- 模式 2: 动态构建路径 ----
        self._image_dynamic_widget = QWidget()
        dynamic_layout = QVBoxLayout(self._image_dynamic_widget)
        dynamic_layout.setContentsMargins(0, 0, 0, 0)

        # 来源事件
        prev_func_events = self.host._get_previous_function_events()
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("来源事件："))
        self._image_dyn_source_combo = QComboBox()
        self._image_dyn_source_combo.setMinimumWidth(150)
        for evt in prev_func_events:
            label = f"{evt.name or '未命名'} (var={evt.var_name or 'auto'})"
            self._image_dyn_source_combo.addItem(label, evt)
        row1.addWidget(self._image_dyn_source_combo, 1)
        dynamic_layout.addLayout(row1)

        # 选择字段
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("选择字段："))
        self._image_dyn_field_combo = QComboBox()
        self._image_dyn_field_combo.setMinimumWidth(140)
        self._image_dyn_field_combo.addItem("目标地点", "target_location")
        self._image_dyn_field_combo.addItem("任务名称", "quest_name")
        self._image_dyn_field_combo.addItem("进度数值", "progress_num")
        self._image_dyn_field_combo.addItem("自定义...", "__custom__")
        self._image_dyn_field_combo.currentIndexChanged.connect(
            self._on_image_dyn_field_changed
        )
        row2.addWidget(self._image_dyn_field_combo, 1)
        dynamic_layout.addLayout(row2)

        # 自定义字段输入
        self._image_dyn_custom_field_edit = QLineEdit()
        self._image_dyn_custom_field_edit.setPlaceholderText(
            "自定义字段，如 custom_field"
        )
        self._image_dyn_custom_field_edit.setVisible(False)
        dynamic_layout.addWidget(self._image_dyn_custom_field_edit)

        # 图片目录 + 后缀 + 前缀
        row3 = QHBoxLayout()
        row3.addWidget(QLabel("前缀："))
        self._image_dyn_prefix_edit = QLineEdit()
        self._image_dyn_prefix_edit.setPlaceholderText("路径前缀")
        self._image_dyn_prefix_edit.setMaximumWidth(120)
        row3.addWidget(self._image_dyn_prefix_edit)
        row3.addWidget(QLabel("图片目录："))
        self._image_dyn_dir_edit = QLineEdit()
        self._image_dyn_dir_edit.setPlaceholderText("E:/图片/")
        self._image_dyn_dir_edit.setMinimumWidth(200)
        row3.addWidget(self._image_dyn_dir_edit, 1)
        dir_browse_btn = QPushButton("浏览...")
        dir_browse_btn.clicked.connect(
            lambda: self.host._on_browse_dir(self._image_dyn_dir_edit)
        )
        row3.addWidget(dir_browse_btn)
        row3.addWidget(QLabel("后缀："))
        self._image_dyn_suffix_edit = QLineEdit(".bmp")
        self._image_dyn_suffix_edit.setMaximumWidth(60)
        row3.addWidget(self._image_dyn_suffix_edit)
        dynamic_layout.addLayout(row3)

        # 构建预览
        row4 = QHBoxLayout()
        self._image_dyn_preview_btn = QPushButton("预览构建结果")
        self._image_dyn_preview_btn.clicked.connect(self._on_image_dyn_preview)
        row4.addWidget(self._image_dyn_preview_btn)
        self._image_dyn_preview_label = QLabel("")
        self._image_dyn_preview_label.setStyleSheet("color: #2196F3; font-size: 11px;")
        self._image_dyn_preview_label.setWordWrap(True)
        row4.addWidget(self._image_dyn_preview_label, 1)
        dynamic_layout.addLayout(row4)

        form.addRow("动态路径配置：", self._image_dynamic_widget)

        # ---- 地图白名单配置 ----
        self._image_allowed_maps_check = QCheckBox("启用地图白名单（只识别指定地图）")
        self._image_allowed_maps_edit = QLineEdit()
        self._image_allowed_maps_edit.setPlaceholderText(
            "江南野外,建邺城,东海湾（逗号分隔）"
        )
        self._image_allowed_maps_edit.setVisible(False)
        self._image_allowed_maps_check.stateChanged.connect(
            lambda state: self._image_allowed_maps_edit.setVisible(
                state == Qt.Checked
            )
        )
        form.addRow("地图白名单：", self._image_allowed_maps_check)
        form.addRow("", self._image_allowed_maps_edit)

        # ---- 识别重试配置 ----
        self._image_recognize_retries_container = QWidget()
        retry_row = QHBoxLayout()
        retry_row.setContentsMargins(0, 0, 0, 0)
        retry_row.addWidget(QLabel("识别重试次数："))
        self._image_recognize_retries_spin = QSpinBox()
        self._image_recognize_retries_spin.setRange(0, 10)
        self._image_recognize_retries_spin.setValue(2)
        self._image_recognize_retries_spin.setToolTip("匹配失败时自动重试次数")
        retry_row.addWidget(self._image_recognize_retries_spin)
        retry_row.addWidget(QLabel("重试间隔(秒)："))
        self._image_recognize_retry_interval_spin = QDoubleSpinBox()
        self._image_recognize_retry_interval_spin.setRange(0.1, 10.0)
        self._image_recognize_retry_interval_spin.setValue(0.5)
        self._image_recognize_retry_interval_spin.setSingleStep(0.1)
        retry_row.addWidget(self._image_recognize_retry_interval_spin)
        retry_row.addStretch()
        self._image_recognize_retries_container.setLayout(retry_row)
        form.addRow("识别重试：", self._image_recognize_retries_container)

        # ---- 模式 3: 目录批量识别 ----
        self._image_batch_widget = QWidget()
        batch_layout = QVBoxLayout(self._image_batch_widget)
        batch_layout.setContentsMargins(0, 0, 0, 0)

        # 目录路径
        batch_row1 = QHBoxLayout()
        batch_row1.addWidget(QLabel("目录路径："))
        self._image_batch_dir_edit = QLineEdit()
        self._image_batch_dir_edit.setPlaceholderText("E:/图片/")
        self._image_batch_dir_edit.setMinimumWidth(200)
        batch_row1.addWidget(self._image_batch_dir_edit, 1)
        batch_dir_browse_btn = QPushButton("浏览...")
        batch_dir_browse_btn.clicked.connect(
            lambda: self.host._on_browse_dir(self._image_batch_dir_edit)
        )
        batch_row1.addWidget(batch_dir_browse_btn)
        batch_layout.addLayout(batch_row1)

        # 图片扩展名筛选
        batch_row2 = QHBoxLayout()
        batch_row2.addWidget(QLabel("图片扩展名："))
        self._image_batch_ext_edit = QLineEdit()
        self._image_batch_ext_edit.setPlaceholderText(".bmp,.png,.jpg")
        self._image_batch_ext_edit.setText(".bmp")
        batch_row2.addWidget(self._image_batch_ext_edit, 1)
        batch_layout.addLayout(batch_row2)

        # 动态变量替换：使用函数调用结果作为目录或文件名的一部分
        batch_row3 = QHBoxLayout()
        self._image_batch_use_var_check = QCheckBox("使用函数调用结果作为文件名筛选")
        self._image_batch_use_var_check.stateChanged.connect(
            self._on_image_batch_var_changed
        )
        batch_row3.addWidget(self._image_batch_use_var_check)
        batch_layout.addLayout(batch_row3)

        # 变量筛选配置
        self._image_batch_var_widget = QWidget()
        batch_var_layout = QHBoxLayout(self._image_batch_var_widget)
        batch_var_layout.setContentsMargins(0, 0, 0, 0)
        batch_var_layout.addWidget(QLabel("筛选字段："))
        self._image_batch_var_combo = QComboBox()
        self._image_batch_var_combo.setMinimumWidth(140)
        self._image_batch_var_combo.addItem("目标地点", "target_location")
        self._image_batch_var_combo.addItem("任务名称", "quest_name")
        batch_var_layout.addWidget(self._image_batch_var_combo, 1)
        self._image_batch_var_widget.setVisible(False)
        batch_layout.addWidget(self._image_batch_var_widget)

        # 排序方式
        batch_row4 = QHBoxLayout()
        batch_row4.addWidget(QLabel("匹配排序："))
        self._image_batch_sort_combo = QComboBox()
        self._image_batch_sort_combo.addItem("按文件名排序", "name")
        self._image_batch_sort_combo.addItem("随机顺序", "random")
        self._image_batch_sort_combo.addItem("按匹配度排序", "score")
        batch_row4.addWidget(self._image_batch_sort_combo, 1)
        batch_layout.addLayout(batch_row4)

        # 点击模式
        batch_row5 = QHBoxLayout()
        batch_row5.addWidget(QLabel("点击模式："))
        self._image_batch_click_mode_combo = QComboBox()
        self._image_batch_click_mode_combo.addItem("点击所有匹配", "all")
        self._image_batch_click_mode_combo.addItem("只点击第一个匹配", "first")
        self._image_batch_click_mode_combo.addItem("逐个点击后等待确认", "each_wait")
        batch_row5.addWidget(self._image_batch_click_mode_combo, 1)
        batch_layout.addLayout(batch_row5)

        form.addRow("批量识别配置：", self._image_batch_widget)

        # 根据模式显示/隐藏
        self._image_dynamic_widget.setVisible(False)
        self._image_batch_widget.setVisible(False)

        # ---- 匹配阈值 ----
        self._image_threshold_spin = QDoubleSpinBox()
        self._image_threshold_spin.setRange(0.0, 1.0)
        self._image_threshold_spin.setSingleStep(0.05)
        self._image_threshold_spin.setDecimals(3)
        form.addRow("匹配阈值：", self._image_threshold_spin)

        # ---- 识别后动作 ----
        self._image_action_combo = QComboBox()
        self._image_action_combo.addItem("点击目标", "click")
        self._image_action_combo.addItem("等待出现", "wait")
        self._image_action_combo.addItem("等待消失", "wait_disappear")
        self._image_action_combo.addItem("仅记录", "record")
        self._image_action_combo.currentIndexChanged.connect(
            self._on_image_action_changed
        )
        form.addRow("识别后动作：", self._image_action_combo)

        # ---- 点击类型 ----
        self._image_button_combo = QComboBox()
        self._image_button_combo.addItem("左键点击", "left")
        self._image_button_combo.addItem("右键点击", "right")
        self._image_button_combo.addItem("双击", "double")

        self._image_button_container = QWidget()
        button_layout = QHBoxLayout(self._image_button_container)
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.addWidget(self._image_button_combo)
        # 点击后延迟
        button_layout.addWidget(QLabel("点击后延迟(ms)："))
        self._image_click_delay_spin = QSpinBox()
        self._image_click_delay_spin.setRange(0, 10000)
        self._image_click_delay_spin.setValue(1000)
        self._image_click_delay_spin.setToolTip("每次鼠标点击后等待的毫秒数，避免点击太快游戏反应不过来")
        button_layout.addWidget(self._image_click_delay_spin)
        self._image_button_label = QLabel("点击类型：")
        form.addRow(self._image_button_label, self._image_button_container)

        # ---- 附加点击操作 ----
        self._image_rules_group = QGroupBox("附加点击操作（图像识别点击后执行）")
        rules_layout = QVBoxLayout(self._image_rules_group)

        # 启用附加点击
        self._image_additional_click_check = QCheckBox("启用附加点击")
        self._image_additional_click_check.stateChanged.connect(
            self._on_additional_click_changed
        )
        rules_layout.addWidget(self._image_additional_click_check)

        # 附加点击模式
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("附加点击模式："))
        self._image_add_mode_combo = QComboBox()
        self._image_add_mode_combo.addItem("直接输入坐标", "direct")
        self._image_add_mode_combo.addItem("从地图坐标文件查找", "file_lookup")
        self._image_add_mode_combo.currentIndexChanged.connect(
            self._on_additional_mode_changed
        )
        mode_row.addWidget(self._image_add_mode_combo, 1)
        rules_layout.addLayout(mode_row)

        # ---- 模式 1: 直接输入坐标 ----
        self._image_add_direct_widget = QWidget()
        direct_layout = QVBoxLayout(self._image_add_direct_widget)
        direct_layout.setContentsMargins(0, 0, 0, 0)

        add_coord_row = QHBoxLayout()
        add_coord_row.addWidget(QLabel("X："))
        self._image_add_x_edit = QLineEdit()
        self._image_add_x_edit.setPlaceholderText("整数或 ${变量}，如 ${JHRW.target_coord.0}")
        self._image_add_x_edit.setMinimumWidth(180)
        add_coord_row.addWidget(self._image_add_x_edit, 1)
        add_coord_row.addWidget(QLabel("Y："))
        self._image_add_y_edit = QLineEdit()
        self._image_add_y_edit.setPlaceholderText("整数或 ${变量}，如 ${JHRW.target_coord.1}")
        self._image_add_y_edit.setMinimumWidth(180)
        add_coord_row.addWidget(self._image_add_y_edit, 1)
        direct_layout.addLayout(add_coord_row)

        rules_layout.addWidget(self._image_add_direct_widget)

        # ---- 模式 2: 从地图坐标文件查找 ----
        self._image_add_file_widget = QWidget()
        file_layout = QVBoxLayout(self._image_add_file_widget)
        file_layout.setContentsMargins(0, 0, 0, 0)

        # 文件路径
        file_row1 = QHBoxLayout()
        file_row1.addWidget(QLabel("坐标文件："))
        self._image_coord_file_edit = QLineEdit()
        self._image_coord_file_edit.setPlaceholderText(config.map_coord_file)
        self._image_coord_file_edit.setText(
            config.map_coord_file
        )
        self._image_coord_file_edit.setMinimumWidth(250)
        file_row1.addWidget(self._image_coord_file_edit, 1)
        file_browse_btn = QPushButton("浏览...")
        file_browse_btn.clicked.connect(
            lambda: self.host._on_browse_file(
                self._image_coord_file_edit,
                "文本文件 (*.txt);;所有文件 (*.*)",
            )
        )
        file_row1.addWidget(file_browse_btn)
        file_layout.addLayout(file_row1)

        # 匹配字段：从函数调用结果中取哪个字段的值来匹配文件名
        file_row2 = QHBoxLayout()
        file_row2.addWidget(QLabel("匹配字段："))
        self._image_match_field_combo = QComboBox()
        self._image_match_field_combo.setMinimumWidth(150)
        self._image_match_field_combo.addItem("目标地点", "target_location")
        self._image_match_field_combo.addItem("任务名称", "quest_name")
        self._image_match_field_combo.addItem("地图名称", "map_name")
        self._image_match_field_combo.addItem("自定义...", "__custom__")
        self._image_match_field_combo.currentIndexChanged.connect(
            self._on_match_field_changed
        )
        file_row2.addWidget(self._image_match_field_combo, 1)
        file_layout.addLayout(file_row2)

        # 自定义字段
        self._image_match_custom_field_edit = QLineEdit()
        self._image_match_custom_field_edit.setPlaceholderText(
            "自定义字段名，如 custom_field"
        )
        self._image_match_custom_field_edit.setVisible(False)
        file_layout.addWidget(self._image_match_custom_field_edit)

        # 文件格式说明
        file_hint = QLabel(
            "💡 文件格式：每行 \"地图名  X,Y\"（空格或Tab分隔）\n"
            "示例：东海湾   735,383\n"
            "将从函数调用结果中取\"匹配字段\"的值，在文件中查找对应坐标"
        )
        file_hint.setStyleSheet("color: #2196F3; font-size: 11px;")
        file_hint.setWordWrap(True)
        file_layout.addWidget(file_hint)

        # 预览文件内容
        self._image_preview_file_btn = QPushButton("预览文件内容")
        self._image_preview_file_btn.clicked.connect(self._on_preview_coord_file)
        file_layout.addWidget(self._image_preview_file_btn)

        self._image_preview_label = QLabel("")
        self._image_preview_label.setStyleSheet("color: #666; font-size: 11px;")
        self._image_preview_label.setWordWrap(True)
        file_layout.addWidget(self._image_preview_label)

        rules_layout.addWidget(self._image_add_file_widget)

        # ---- 共用：点击类型 + 延迟 ----
        add_config_row = QHBoxLayout()
        add_config_row.addWidget(QLabel("点击类型："))
        self._image_add_button_combo = QComboBox()
        self._image_add_button_combo.addItem("左键点击", "left")
        self._image_add_button_combo.addItem("右键点击", "right")
        self._image_add_button_combo.addItem("双击", "double")
        add_config_row.addWidget(self._image_add_button_combo)
        add_config_row.addWidget(QLabel("延迟(ms)："))
        self._image_add_delay_spin = QSpinBox()
        self._image_add_delay_spin.setRange(0, 10000)
        self._image_add_delay_spin.setValue(200)
        add_config_row.addWidget(self._image_add_delay_spin)
        add_config_row.addStretch(1)
        rules_layout.addLayout(add_config_row)

        # 初始隐藏附加点击控件
        self._on_additional_click_changed(Qt.Unchecked)
        self._on_additional_mode_changed(0)

        form.addRow("", self._image_rules_group)

        # ---- 识别区域 ----
        region_row = QHBoxLayout()
        self._image_region_x_spin = QSpinBox()
        self._image_region_x_spin.setRange(0, 9999)
        self._image_region_y_spin = QSpinBox()
        self._image_region_y_spin.setRange(0, 9999)
        self._image_region_w_spin = QSpinBox()
        self._image_region_w_spin.setRange(0, 9999)
        self._image_region_h_spin = QSpinBox()
        self._image_region_h_spin.setRange(0, 9999)
        region_row.addWidget(QLabel("X:"))
        region_row.addWidget(self._image_region_x_spin)
        region_row.addWidget(QLabel("Y:"))
        region_row.addWidget(self._image_region_y_spin)
        region_row.addWidget(QLabel("宽:"))
        region_row.addWidget(self._image_region_w_spin)
        region_row.addWidget(QLabel("高:"))
        region_row.addWidget(self._image_region_h_spin)
        region_row.addStretch(1)
        region_container = QWidget()
        region_container.setLayout(region_row)
        form.addRow("识别区域：", region_container)

        # ---- 提示 ----
        var_hint = QLabel(
            "💡 提示：\n"
            "  · 直接指定：选择本地单个图片文件\n"
            "  · 动态构建：根据前序函数调用结果自动拼接路径\n"
            "  · 目录批量：扫描目录下所有图片逐个匹配点击\n"
            "  · 示例：字段='东海湾' + 前缀='E:/道具/' + 后缀='.bmp'\n"
            "    → 自动构建 E:/道具/东海湾.bmp"
        )
        var_hint.setStyleSheet("color: #2196F3; font-size: 11px;")
        var_hint.setWordWrap(True)
        form.addRow("", var_hint)

        # 初始化点击类型和规则可见性
        self._on_image_action_changed(0)
        self._on_image_source_mode_changed(0)

        # 包装进滚动区域，解决内容过多显示不全的问题
        scroll = QScrollArea()
        scroll.setWidget(page)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)  # 无边框，视觉上与原页面一致
        return scroll

    # ------------------------------------------------------------------
    # 图像识别页面辅助方法
    # ------------------------------------------------------------------
    def _on_image_source_mode_changed(self, index):
        """模板来源模式切换时更新控件可见性。"""
        mode = self._image_source_mode_combo.currentData()
        self._image_direct_widget.setVisible(mode == "direct")
        self._image_dynamic_widget.setVisible(mode == "dynamic")
        self._image_batch_widget.setVisible(mode == "batch")

    def _on_image_action_changed(self, index):
        """识别后动作变化时更新点击类型控件的可见性。"""
        action = self._image_action_combo.currentData()
        # 点击类型（左键/右键/双击）仅在 action=click 时显示
        show_click_type = (action == "click")
        self._image_button_container.setVisible(show_click_type)
        self._image_button_label.setVisible(show_click_type)
        # 附加点击操作在 click/wait/wait_disappear 时都显示
        show_additional = action in ("click", "wait", "wait_disappear")
        self._image_rules_group.setVisible(show_additional)

    def _on_image_random_offset_changed(self, state):
        """随机偏移开关变化时更新范围输入可用状态。"""
        self._image_random_range_spin.setEnabled(state == Qt.Checked)

    def _on_additional_click_changed(self, state):
        """附加点击开关变化时更新控件可见性。"""
        enabled = (state == Qt.Checked)
        self._image_add_mode_combo.setEnabled(enabled)
        self._image_add_button_combo.setEnabled(enabled)
        self._image_add_delay_spin.setEnabled(enabled)
        self._on_additional_mode_changed(
            self._image_add_mode_combo.currentIndex()
        )

    def _on_additional_mode_changed(self, index):
        """附加点击模式切换时更新控件可见性。"""
        mode = self._image_add_mode_combo.currentData()
        is_direct = (mode == "direct")
        is_file = (mode == "file_lookup")
        # 直接输入坐标模式
        self._image_add_direct_widget.setVisible(is_direct)
        # 文件查找模式
        self._image_add_file_widget.setVisible(is_file)

        enabled = self._image_additional_click_check.isChecked()
        self._image_add_mode_combo.setEnabled(enabled)
        self._image_add_button_combo.setEnabled(enabled)
        self._image_add_delay_spin.setEnabled(enabled)
        if is_direct:
            self._image_add_x_edit.setEnabled(enabled)
            self._image_add_y_edit.setEnabled(enabled)
        if is_file:
            self._image_coord_file_edit.setEnabled(enabled)
            self._image_match_field_combo.setEnabled(enabled)
            self._image_preview_file_btn.setEnabled(enabled)
            # 自定义字段
            match_data = self._image_match_field_combo.currentData()
            self._image_match_custom_field_edit.setEnabled(
                enabled and match_data == "__custom__"
            )

    def _on_match_field_changed(self, index):
        """匹配字段选择变化时显示/隐藏自定义输入框。"""
        data = self._image_match_field_combo.itemData(index)
        self._image_match_custom_field_edit.setVisible(data == "__custom__")

    def _on_preview_coord_file(self):
        """预览坐标文件内容。"""
        file_path = self._image_coord_file_edit.text().strip()
        if not file_path:
            self._image_preview_label.setText("⚠️ 请先指定坐标文件路径")
            self._image_preview_label.setStyleSheet("color: #FF8C00; font-size: 11px;")
            return
        if not os.path.isfile(file_path):
            self._image_preview_label.setText(f"⚠️ 文件不存在: {file_path}")
            self._image_preview_label.setStyleSheet("color: #FF8C00; font-size: 11px;")
            return
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                lines = f.readlines()[:10]
            preview = "文件内容预览（前10行）:\n" + "".join(lines)
            self._image_preview_label.setText(preview.strip())
            self._image_preview_label.setStyleSheet("color: #333; font-size: 11px;")
        except Exception as e:
            self._image_preview_label.setText(f"⚠️ 读取失败: {e}")
            self._image_preview_label.setStyleSheet("color: #FF8C00; font-size: 11px;")

    def _on_image_dyn_field_changed(self, index):
        """动态构建字段选择变化时显示/隐藏自定义输入框。"""
        data = self._image_dyn_field_combo.itemData(index)
        self._image_dyn_custom_field_edit.setVisible(data == "__custom__")

    def _on_image_batch_var_changed(self, state):
        """批量模式变量筛选开关变化时更新配置控件可见性。"""
        self._image_batch_var_widget.setVisible(state == Qt.Checked)

    def _on_image_dyn_preview(self):
        """预览动态路径构建结果。"""
        src = self._image_dyn_source_combo.currentData()
        if src is None:
            self._image_dyn_preview_label.setText("⚠️ 请先选择来源事件")
            self._image_dyn_preview_label.setStyleSheet("color: #FF8C00; font-size: 11px;")
            return
        field = self._image_dyn_field_combo.currentData()
        if field == "__custom__":
            field = self._image_dyn_custom_field_edit.text().strip()
        if not field:
            self._image_dyn_preview_label.setText("⚠️ 请先选择或输入字段")
            self._image_dyn_preview_label.setStyleSheet("color: #FF8C00; font-size: 11px;")
            return

        var_name = src.var_name if src.var_name else src.name.replace(" ", "").replace("_", "")
        prefix = self._image_dyn_prefix_edit.text().strip()
        dir_path = self._image_dyn_dir_edit.text().strip()
        suffix = self._image_dyn_suffix_edit.text().strip()

        if dir_path:
            template = f"{prefix}${{{var_name}.{field}}}{suffix}"
            full_path = f"{dir_path.rstrip('/').rstrip('\\\\')}/{prefix}${{{var_name}.{field}}}{suffix}"
            self._image_dyn_preview_label.setText(
                f"模板变量: {template}\n"
                f"完整路径: {full_path}"
            )
        else:
            template = f"{prefix}${{{var_name}.{field}}}{suffix}"
            self._image_dyn_preview_label.setText(f"模板变量: {template}")
        self._image_dyn_preview_label.setStyleSheet("color: #2196F3; font-size: 11px;")

    def load(self, params: dict) -> None:
        """加载图像识别参数到控件。"""
        # 模板来源模式
        source_mode = params.get("source_mode", "direct")
        self.host._set_combo_by_data(self._image_source_mode_combo, source_mode, "direct")

        # 直接指定路径
        self._image_template_edit.setText(str(params.get("template_path", "") or ""))

        # 动态构建参数
        self._image_dyn_prefix_edit.setText(str(params.get("prefix", "") or ""))
        self._image_dyn_dir_edit.setText(str(params.get("dir_path", "") or ""))
        self._image_dyn_suffix_edit.setText(str(params.get("suffix", ".bmp") or ".bmp"))

        # 动态来源事件和字段（仅加载索引信息，实际选择需要事件列表存在）
        dyn_field = params.get("dyn_field", "target_location")
        dyn_field_data = dyn_field if dyn_field else "target_location"
        # 检查是否为自定义字段
        if dyn_field_data == "__custom__":
            self.host._set_combo_by_data(self._image_dyn_field_combo, "__custom__", "target_location")
            self._image_dyn_custom_field_edit.setText(
                str(params.get("dyn_custom_field", "") or "")
            )
        else:
            self.host._set_combo_by_data(self._image_dyn_field_combo, dyn_field_data, "target_location")

        # 批量识别参数
        self._image_batch_dir_edit.setText(str(params.get("batch_dir", "") or ""))
        self._image_batch_ext_edit.setText(str(params.get("batch_ext", ".bmp") or ".bmp"))
        self._image_batch_use_var_check.setChecked(
            bool(params.get("batch_use_var", False))
        )
        self._on_image_batch_var_changed(self._image_batch_use_var_check.isChecked())
        self.host._set_combo_by_data(
            self._image_batch_var_combo,
            params.get("batch_var_field", "target_location"),
            "target_location"
        )
        self.host._set_combo_by_data(
            self._image_batch_sort_combo,
            params.get("batch_sort", "name"),
            "name"
        )
        self.host._set_combo_by_data(
            self._image_batch_click_mode_combo,
            params.get("batch_click_mode", "all"),
            "all"
        )

        # 阈值
        try:
            threshold = float(params.get("threshold", 0.8) or 0.0)
        except (TypeError, ValueError):
            threshold = 0.0
        self._image_threshold_spin.setValue(threshold)

        # 动作
        self.host._set_combo_by_data(
            self._image_action_combo, params.get("action", "click"), "click"
        )
        # 点击类型
        self.host._set_combo_by_data(
            self._image_button_combo, params.get("button", "left"), "left"
        )
        # 点击后延迟
        try:
            click_delay = int(params.get("click_delay", 300))
        except (TypeError, ValueError):
            click_delay = 300
        self._image_click_delay_spin.setValue(click_delay)
        # 更新点击类型和规则可见性
        self._on_image_action_changed(self._image_action_combo.currentIndex())
        self._on_image_source_mode_changed(self._image_source_mode_combo.currentIndex())

        # 附加点击操作
        self._image_additional_click_check.setChecked(
            bool(params.get("additional_click_enabled", False))
        )
        # 附加点击模式
        add_mode = str(params.get("additional_mode", "direct") or "direct")
        self.host._set_combo_by_data(self._image_add_mode_combo, add_mode, "direct")
        # 直接输入坐标
        self._image_add_x_edit.setText(str(params.get("additional_x", "") or ""))
        self._image_add_y_edit.setText(str(params.get("additional_y", "") or ""))
        # 文件查找
        self._image_coord_file_edit.setText(
            str(params.get("coord_file", "") or config.map_coord_file)
        )
        match_field = str(params.get("match_field", "target_location") or "target_location")
        self.host._set_combo_by_data(self._image_match_field_combo, match_field, "target_location")
        self._image_match_custom_field_edit.setText(
            str(params.get("match_custom_field", "") or "")
        )
        # 点击类型
        self.host._set_combo_by_data(
            self._image_add_button_combo,
            params.get("additional_button", "left"),
            "left"
        )
        try:
            add_delay = int(params.get("additional_delay", 200) or 200)
        except (TypeError, ValueError):
            add_delay = 200
        self._image_add_delay_spin.setValue(add_delay)
        # 更新附加点击控件可用状态
        self._on_additional_click_changed(
            self._image_additional_click_check.isChecked()
        )
        self._on_match_field_changed(self._image_match_field_combo.currentIndex())

        # 识别区域 [x, y, w, h]
        region = params.get("region", [0, 0, 0, 0]) or [0, 0, 0, 0]
        if not isinstance(region, (list, tuple)) or len(region) < 4:
            region = [0, 0, 0, 0]
        self._image_region_x_spin.setValue(int(region[0] or 0))
        self._image_region_y_spin.setValue(int(region[1] or 0))
        self._image_region_w_spin.setValue(int(region[2] or 0))
        self._image_region_h_spin.setValue(int(region[3] or 0))

        # 地图白名单
        allowed_maps = params.get("allowed_maps", None)
        if allowed_maps and isinstance(allowed_maps, list) and len(allowed_maps) > 0:
            self._image_allowed_maps_check.setChecked(True)
            self._image_allowed_maps_edit.setText(",".join(allowed_maps))
        else:
            self._image_allowed_maps_check.setChecked(False)
            self._image_allowed_maps_edit.clear()

        # 识别重试
        try:
            recognize_retries = int(params.get("recognize_retries", 2))
        except (TypeError, ValueError):
            recognize_retries = 2
        self._image_recognize_retries_spin.setValue(recognize_retries)

        try:
            recognize_retry_interval = float(params.get("recognize_retry_interval", 0.5))
        except (TypeError, ValueError):
            recognize_retry_interval = 0.5
        self._image_recognize_retry_interval_spin.setValue(recognize_retry_interval)

    def apply(self, event: Event) -> bool:
        """将图像识别参数写回 Event.params。"""
        # 模板来源模式
        source_mode = self._image_source_mode_combo.currentData() or "direct"

        # 基础参数
        template_path = self._image_template_edit.text()
        threshold = self._image_threshold_spin.value()
        action = self._image_action_combo.currentData() or "click"
        button = self._image_button_combo.currentData() or "left"
        click_delay = self._image_click_delay_spin.value()

        # 动态构建参数
        dyn_field_data = self._image_dyn_field_combo.currentData() or "target_location"
        dyn_custom_field = ""
        if dyn_field_data == "__custom__":
            dyn_field_data = "__custom__"
            dyn_custom_field = self._image_dyn_custom_field_edit.text().strip()

        # 附加点击操作
        additional_click_enabled = self._image_additional_click_check.isChecked()
        additional_mode = self._image_add_mode_combo.currentData() or "direct"
        additional_x = self._image_add_x_edit.text().strip()
        additional_y = self._image_add_y_edit.text().strip()
        coord_file = self._image_coord_file_edit.text().strip()
        # 默认值不写入 JSON，避免绝对路径污染持久化数据（运行时回退 config.map_coord_file）
        if coord_file == config.map_coord_file:
            coord_file = ""
        match_field = self._image_match_field_combo.currentData() or "target_location"
        match_custom_field = ""
        if match_field == "__custom__":
            match_field = "__custom__"
            match_custom_field = self._image_match_custom_field_edit.text().strip()
        additional_button = self._image_add_button_combo.currentData() or "left"
        additional_delay = self._image_add_delay_spin.value()

        # 构建参数字典
        # 地图白名单
        allowed_maps = None
        if self._image_allowed_maps_check.isChecked():
            allowed_maps_text = self._image_allowed_maps_edit.text().strip()
            if allowed_maps_text:
                allowed_maps = [m.strip() for m in allowed_maps_text.split(",") if m.strip()]

        # 识别重试
        recognize_retries = self._image_recognize_retries_spin.value()
        recognize_retry_interval = self._image_recognize_retry_interval_spin.value()

        event.params = {
            # 基础
            "source_mode": source_mode,
            "template_path": template_path,
            "threshold": threshold,
            "action": action,
            "button": button,
            "click_delay": click_delay,
            "region": [
                self._image_region_x_spin.value(),
                self._image_region_y_spin.value(),
                self._image_region_w_spin.value(),
                self._image_region_h_spin.value(),
            ],
            # 动态构建
            "prefix": self._image_dyn_prefix_edit.text(),
            "dir_path": self._image_dyn_dir_edit.text(),
            "suffix": self._image_dyn_suffix_edit.text(),
            "dyn_field": dyn_field_data,
            "dyn_custom_field": dyn_custom_field,
            # 地图白名单
            "allowed_maps": allowed_maps,
            # 识别重试
            "recognize_retries": recognize_retries,
            "recognize_retry_interval": recognize_retry_interval,
            # 批量识别
            "batch_dir": self._image_batch_dir_edit.text(),
            "batch_ext": self._image_batch_ext_edit.text(),
            "batch_use_var": self._image_batch_use_var_check.isChecked(),
            "batch_var_field": self._image_batch_var_combo.currentData() or "target_location",
            "batch_sort": self._image_batch_sort_combo.currentData() or "name",
            "batch_click_mode": self._image_batch_click_mode_combo.currentData() or "all",
            # 附加点击操作
            "additional_click_enabled": additional_click_enabled,
            "additional_mode": additional_mode,
            "additional_x": additional_x,
            "additional_y": additional_y,
            "coord_file": coord_file,
            "match_field": match_field,
            "match_custom_field": match_custom_field,
            "additional_button": additional_button,
            "additional_delay": additional_delay,
        }
        return True


class YoloParamPage(BaseParamPage):
    """YOLO 检测参数页（图片识别方式，已从 EventEditorDialog 抽出，PR #8 收口）。"""

    def build(self) -> QWidget:
        """YOLO 检测参数页（图片识别方式）：模板路径 / 阈值 / 动作 / 识别区域。"""
        page = QWidget()
        form = QFormLayout(page)
        form.setLabelAlignment(Qt.AlignRight)

        # 模板图片路径：QTextEdit + 浏览按钮（支持多图，每行一个路径）
        tpl_col = QVBoxLayout()
        tpl_col.setContentsMargins(0, 0, 0, 0)
        self._yolo_template_edit = QTextEdit()
        self._yolo_template_edit.setPlaceholderText(
            "每行一个模板图片路径（PNG/JPG/BMP），支持多图同时检测\n"
            "例：\nimage/monster1.png\nimage/monster2.png"
        )
        self._yolo_template_edit.setFixedHeight(80)
        tpl_col.addWidget(self._yolo_template_edit)
        # 浏览按钮行
        btn_row = QHBoxLayout()
        browse_btn = QPushButton("浏览...")
        browse_btn.clicked.connect(
            lambda: self.host._on_browse_file(
                self._yolo_template_edit,
                "图片 (*.png *.jpg *.bmp *.jpeg);;所有文件 (*.*)",
                multi=True,
            )
        )
        btn_row.addWidget(browse_btn)
        btn_row.addStretch()
        tpl_col.addLayout(btn_row)
        tpl_container = QWidget()
        tpl_container.setLayout(tpl_col)
        form.addRow("模板图片路径：", tpl_container)

        self._yolo_threshold_spin = QDoubleSpinBox()
        self._yolo_threshold_spin.setRange(0.0, 1.0)
        self._yolo_threshold_spin.setSingleStep(0.05)
        self._yolo_threshold_spin.setDecimals(3)
        form.addRow("匹配阈值：", self._yolo_threshold_spin)

        self._yolo_action_combo = QComboBox()
        self._yolo_action_combo.addItem("点击目标", "click")
        self._yolo_action_combo.addItem("等待出现", "wait")
        self._yolo_action_combo.addItem("等待消失", "wait_disappear")
        self._yolo_action_combo.addItem("仅记录", "record")
        self._yolo_action_combo.currentIndexChanged.connect(
            self._on_yolo_action_changed
        )
        form.addRow("识别后动作：", self._yolo_action_combo)

        # 点击类型（仅当 action=click 时显示）
        self._yolo_button_combo = QComboBox()
        self._yolo_button_combo.addItem("左键点击", "left")
        self._yolo_button_combo.addItem("右键点击", "right")
        self._yolo_button_combo.addItem("双击", "double")

        self._yolo_button_container = QWidget()
        yolo_button_layout = QHBoxLayout(self._yolo_button_container)
        yolo_button_layout.setContentsMargins(0, 0, 0, 0)
        yolo_button_layout.addWidget(self._yolo_button_combo)
        self._yolo_button_label = QLabel("点击类型：")
        form.addRow(self._yolo_button_label, self._yolo_button_container)

        # 初始化点击类型可见性
        self._on_yolo_action_changed(0)

        # 识别区域：4 个 QSpinBox（x, y, 宽, 高）
        region_row = QHBoxLayout()
        self._yolo_region_x_spin = QSpinBox()
        self._yolo_region_x_spin.setRange(0, 9999)
        self._yolo_region_y_spin = QSpinBox()
        self._yolo_region_y_spin.setRange(0, 9999)
        self._yolo_region_w_spin = QSpinBox()
        self._yolo_region_w_spin.setRange(0, 9999)
        self._yolo_region_h_spin = QSpinBox()
        self._yolo_region_h_spin.setRange(0, 9999)
        region_row.addWidget(QLabel("X:"))
        region_row.addWidget(self._yolo_region_x_spin)
        region_row.addWidget(QLabel("Y:"))
        region_row.addWidget(self._yolo_region_y_spin)
        region_row.addWidget(QLabel("宽:"))
        region_row.addWidget(self._yolo_region_w_spin)
        region_row.addWidget(QLabel("高:"))
        region_row.addWidget(self._yolo_region_h_spin)
        region_row.addStretch(1)
        region_container = QWidget()
        region_container.setLayout(region_row)
        form.addRow("识别区域：", region_container)

        # 模板变量提示（用户也可手动输入 ${变量} 模板）
        var_hint = QLabel(
            "💡 提示：\n"
            "  · 点击「浏览...」选择本地图片文件即可\n"
            "  · 也可使用模板变量，如 ${JHRW.target_location}.bmp"
        )
        var_hint.setStyleSheet("color: #2196F3; font-size: 11px;")
        var_hint.setWordWrap(True)
        form.addRow("", var_hint)

        return page

    # ------------------------------------------------------------------
    # YOLO 页面辅助方法
    # ------------------------------------------------------------------
    def _on_yolo_action_changed(self, index):
        """YOLO 识别后动作变化时更新点击类型控件的可见性。"""
        action = self._yolo_action_combo.currentData()
        show_click_type = (action == "click")
        self._yolo_button_container.setVisible(show_click_type)
        self._yolo_button_label.setVisible(show_click_type)

    def _on_yolo_field_changed(self, index):
        """字段选择变化时显示/隐藏自定义输入框。"""
        if hasattr(self, '_yolo_custom_field_edit'):
            data = self._yolo_field_combo.itemData(index)
            self._yolo_custom_field_edit.setVisible(data == "__custom__")

    def _get_yolo_selected_field(self):
        """获取 YOLO 页面当前选择的字段路径。"""
        if not hasattr(self, '_yolo_field_combo'):
            return ""
        data = self._yolo_field_combo.currentData()
        if data == "__custom__":
            return self._yolo_custom_field_edit.text().strip()
        return data or ""

    def _on_yolo_fill_template(self):
        """根据来源事件+字段+前缀+后缀生成模板路径并填入（保留兼容）。"""
        if not hasattr(self, '_yolo_source_combo'):
            QMessageBox.warning(self.host, "提示", "无前置函数调用事件")
            return
        src = self._yolo_source_combo.currentData()
        if src is None:
            QMessageBox.warning(self.host, "提示", "请先选择来源事件")
            return
        field = self._get_yolo_selected_field()
        if not field:
            QMessageBox.warning(self.host, "提示", "请先选择字段")
            return
        var_name = src.var_name if src.var_name else src.name.replace(" ", "").replace("_", "")
        prefix = self._yolo_prefix_edit.text().strip()
        suffix = self._yolo_suffix_edit.text().strip()
        template = f"{prefix}${{{var_name}.{field}}}{suffix}"
        self._yolo_template_edit.setText(template)

    def _parse_yolo_template_paths(self, text: str) -> list:
        """解析 YOLO 模板路径文本（每行一个路径）为列表。"""
        if not text:
            return []
        paths = [line.strip() for line in text.splitlines()]
        return [p for p in paths if p]

    def load(self, params: dict) -> None:
        """加载 YOLO 检测（图片识别方式）参数到控件。"""
        # 模板路径：兼容单字符串和列表两种格式
        tpl = params.get("template_path", "")
        if isinstance(tpl, list):
            self._yolo_template_edit.setPlainText("\n".join(str(p) for p in tpl if p))
        else:
            self._yolo_template_edit.setPlainText(str(tpl or ""))
        try:
            threshold = float(params.get("threshold", 0.8) or 0.0)
        except (TypeError, ValueError):
            threshold = 0.0
        self._yolo_threshold_spin.setValue(threshold)
        self.host._set_combo_by_data(
            self._yolo_action_combo, params.get("action", "click"), "click"
        )
        # 点击类型
        self.host._set_combo_by_data(
            self._yolo_button_combo, params.get("button", "left"), "left"
        )
        # 更新点击类型可见性
        self._on_yolo_action_changed(self._yolo_action_combo.currentIndex())
        # 识别区域 [x, y, w, h]
        region = params.get("region", [0, 0, 0, 0]) or [0, 0, 0, 0]
        if not isinstance(region, (list, tuple)) or len(region) < 4:
            region = [0, 0, 0, 0]
        self._yolo_region_x_spin.setValue(int(region[0] or 0))
        self._yolo_region_y_spin.setValue(int(region[1] or 0))
        self._yolo_region_w_spin.setValue(int(region[2] or 0))
        self._yolo_region_h_spin.setValue(int(region[3] or 0))

    def apply(self, event: Event) -> bool:
        """将 YOLO 检测（图片识别方式）参数写回 Event.params。"""
        # 模板路径：从 QTextEdit 解析为列表
        template_paths = self._parse_yolo_template_paths(
            self._yolo_template_edit.toPlainText()
        )
        # 单条时存为字符串（向后兼容），多条时存为列表
        if len(template_paths) == 1:
            tpl_value = template_paths[0]
        elif len(template_paths) > 1:
            tpl_value = template_paths
        else:
            tpl_value = ""

        event.params = {
            "template_path": tpl_value,
            "template_paths": template_paths,  # 始终存列表，引擎层读取
            "threshold": self._yolo_threshold_spin.value(),
            "action": self._yolo_action_combo.currentData() or "click",
            "button": self._yolo_button_combo.currentData() or "left",
            "region": [
                self._yolo_region_x_spin.value(),
                self._yolo_region_y_spin.value(),
                self._yolo_region_w_spin.value(),
                self._yolo_region_h_spin.value(),
            ],
        }
        return True


class FunctionParamPage(BaseParamPage):
    """
    函数调用参数页（已从 EventEditorDialog 抽出，PR #8 收口）。

    模块下拉从 ``task_library.get_enabled_modules()`` 获取，模块切换时
    刷新函数下拉；若 task_library 不可用或无模块，下拉为空并给出提示。
    """

    def build(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setLabelAlignment(Qt.AlignRight)

        # 模块下拉
        self._func_module_combo = QComboBox()
        # 函数下拉
        self._func_function_combo = QComboBox()
        # 模块切换时刷新函数列表
        self._func_module_combo.currentIndexChanged.connect(
            self._on_function_module_changed
        )

        form.addRow("模块：", self._func_module_combo)
        form.addRow("函数：", self._func_function_combo)

        # 提示标签（task_library 不可用或无模块时显示）
        self._func_hint_label = QLabel("")
        self._func_hint_label.setStyleSheet("color: #FF8C00;")
        self._func_hint_label.setWordWrap(True)
        form.addRow("", self._func_hint_label)

        # 位置参数 (JSON)
        self._func_args_edit = QLineEdit()
        self._func_args_edit.setPlaceholderText("[arg1, arg2]")
        form.addRow("位置参数 (JSON)：", self._func_args_edit)

        # 关键字参数 (JSON)
        self._func_kwargs_edit = QLineEdit()
        self._func_kwargs_edit.setPlaceholderText('{"key": "value"}')
        form.addRow("关键字参数 (JSON)：", self._func_kwargs_edit)

        # —— 承接参数：从前序函数调用结果中取值 ——
        form.addRow(QLabel(""))
        func_inherit_group = QGroupBox("承接参数（从前序函数调用结果中取值）")
        func_inherit_layout = QVBoxLayout(func_inherit_group)

        func_events = self.host._get_previous_function_events()

        if not func_events:
            no_event_label = QLabel(
                "暂无前置函数调用事件。\n"
                "请先在当前任务中添加「函数调用」事件。"
            )
            no_event_label.setStyleSheet("color: #999; font-size: 11px;")
            no_event_label.setWordWrap(True)
            func_inherit_layout.addWidget(no_event_label)
        else:
            # 来源事件 + 字段选择
            row1 = QHBoxLayout()
            row1.addWidget(QLabel("来源事件："))
            self._func_source_combo = QComboBox()
            self._func_source_combo.setMinimumWidth(150)
            for evt in func_events:
                label = f"{evt.name or '未命名'} (var={evt.var_name or 'auto'})"
                self._func_source_combo.addItem(label, evt)
            row1.addWidget(self._func_source_combo, 1)

            row1.addWidget(QLabel("字段："))
            self._func_field_combo = QComboBox()
            self._func_field_combo.setMinimumWidth(140)
            self._func_field_combo.addItem("目标地点", "target_location")
            self._func_field_combo.addItem("目标坐标 X", "target_coord.0")
            self._func_field_combo.addItem("目标坐标 Y", "target_coord.1")
            self._func_field_combo.addItem("任务名称", "quest_name")
            self._func_field_combo.addItem("自定义...", "__custom__")
            row1.addWidget(self._func_field_combo, 1)

            self._func_field_combo.currentIndexChanged.connect(
                self._on_func_field_changed
            )

            self._func_fill_args_btn = QPushButton("填入位置参数")
            self._func_fill_args_btn.clicked.connect(self._on_func_fill_args)
            row1.addWidget(self._func_fill_args_btn)

            self._func_fill_kwargs_btn = QPushButton("填入关键字参数")
            self._func_fill_kwargs_btn.clicked.connect(self._on_func_fill_kwargs)
            row1.addWidget(self._func_fill_kwargs_btn)

            func_row1 = QWidget()
            func_row1.setLayout(row1)
            func_inherit_layout.addWidget(func_row1)

            # 多字段同时填入（坐标对等）
            row2 = QHBoxLayout()
            self._func_fill_multi_btn = QPushButton(
                "填入坐标对 (args=[coord.0, coord.1])"
            )
            self._func_fill_multi_btn.setStyleSheet(
                "QPushButton { background: #E3F2FD; padding: 6px; }"
            )
            self._func_fill_multi_btn.clicked.connect(self._on_func_fill_multi)
            row2.addWidget(self._func_fill_multi_btn)
            func_row2 = QWidget()
            func_row2.setLayout(row2)
            func_inherit_layout.addWidget(func_row2)

            # 自定义字段
            self._func_custom_field_edit = QLineEdit()
            self._func_custom_field_edit.setPlaceholderText(
                "自定义字段，如 custom_field 或 nested.key"
            )
            self._func_custom_field_edit.setVisible(False)
            func_inherit_layout.addWidget(self._func_custom_field_edit)

        func_inherit_container = QWidget()
        func_inherit_container_layout = QVBoxLayout(func_inherit_container)
        func_inherit_container_layout.setContentsMargins(0, 0, 0, 0)
        func_inherit_container_layout.addWidget(func_inherit_group)
        form.addRow("", func_inherit_container)

        # —— 结果验证配置：重试直到返回有效值 ——
        form.addRow(QLabel(""))
        validate_group = QGroupBox("结果验证（返回值不在白名单时重试函数调用）")
        validate_layout = QVBoxLayout(validate_group)

        # 启用开关
        self._func_validate_check = QCheckBox("启用结果验证")
        self._func_validate_check.stateChanged.connect(
            self._on_func_validate_changed
        )
        validate_layout.addWidget(self._func_validate_check)

        # 验证字段选择
        validate_row1 = QHBoxLayout()
        validate_row1.addWidget(QLabel("验证字段："))
        self._func_validate_field_combo = QComboBox()
        self._func_validate_field_combo.setMinimumWidth(150)
        self._func_validate_field_combo.addItem("目标地点 target_location", "target_location")
        self._func_validate_field_combo.addItem("任务名称 quest_name", "quest_name")
        self._func_validate_field_combo.addItem("是否成功 success", "success")
        validate_row1.addWidget(self._func_validate_field_combo)
        validate_row1.addStretch()
        validate_layout.addLayout(validate_row1)

        # 白名单输入
        validate_row2 = QHBoxLayout()
        validate_row2.addWidget(QLabel("有效值白名单："))
        self._func_validate_whitelist_edit = QLineEdit()
        self._func_validate_whitelist_edit.setPlaceholderText(
            "江南野外,建邺城,东海湾（逗号分隔）"
        )
        self._func_validate_whitelist_edit.setMinimumWidth(200)
        validate_row2.addWidget(self._func_validate_whitelist_edit)
        validate_layout.addLayout(validate_row2)

        # 重试配置
        validate_row3 = QHBoxLayout()
        validate_row3.addWidget(QLabel("重试次数："))
        self._func_validate_retries_spin = QSpinBox()
        self._func_validate_retries_spin.setRange(0, 20)
        self._func_validate_retries_spin.setValue(3)
        self._func_validate_retries_spin.setToolTip(
            "返回值不在白名单时，最多重新调用函数的次数"
        )
        validate_row3.addWidget(self._func_validate_retries_spin)
        validate_row3.addWidget(QLabel("重试间隔(秒)："))
        self._func_validate_retry_interval_spin = QDoubleSpinBox()
        self._func_validate_retry_interval_spin.setRange(0.1, 10.0)
        self._func_validate_retry_interval_spin.setValue(0.5)
        self._func_validate_retry_interval_spin.setSingleStep(0.1)
        validate_row3.addWidget(self._func_validate_retry_interval_spin)
        validate_row3.addStretch()
        validate_layout.addLayout(validate_row3)

        form.addRow("", validate_group)

        # —— 自动等待到达配置 ——
        form.addRow(QLabel(""))
        wait_group = QGroupBox("自动等待到达（函数调用成功后等待角色移动到目标位置）")
        wait_layout = QVBoxLayout(wait_group)

        # 启用开关
        self._auto_wait_check = QCheckBox("启用自动等待到达")
        self._auto_wait_check.setToolTip(
            "函数调用成功后自动检测角色移动状态，"
            "当角色停止移动且靠近目标坐标时判定到达"
        )
        self._auto_wait_check.stateChanged.connect(
            self._on_auto_wait_changed
        )
        wait_layout.addWidget(self._auto_wait_check)

        # 配置参数
        wait_row1 = QHBoxLayout()
        wait_row1.addWidget(QLabel("移动兜底超时(秒)："))
        self._auto_wait_timeout_spin = QDoubleSpinBox()
        self._auto_wait_timeout_spin.setRange(0.0, 120.0)
        self._auto_wait_timeout_spin.setValue(0.0)
        self._auto_wait_timeout_spin.setSingleStep(5.0)
        self._auto_wait_timeout_spin.setToolTip(
            "角色持续移动超过此时间仍未停止则判定失败（防寻路死循环）。\n"
            "0 = 按距离自动估算（推荐），日常用 0 即可。"
        )
        wait_row1.addWidget(self._auto_wait_timeout_spin)

        wait_row1.addWidget(QLabel("坐标容差："))
        self._auto_wait_tolerance_spin = QDoubleSpinBox()
        self._auto_wait_tolerance_spin.setRange(0.5, 20.0)
        self._auto_wait_tolerance_spin.setValue(3.0)
        self._auto_wait_tolerance_spin.setSingleStep(0.5)
        wait_row1.addWidget(self._auto_wait_tolerance_spin)

        wait_row1.addWidget(QLabel("静止确认(秒)："))
        self._auto_wait_stable_spin = QDoubleSpinBox()
        self._auto_wait_stable_spin.setRange(0.3, 5.0)
        self._auto_wait_stable_spin.setValue(1.0)
        self._auto_wait_stable_spin.setSingleStep(0.1)
        self._auto_wait_stable_spin.setToolTip(
            "坐标连续静止多少秒判定为‘已停止’（事件驱动核心）。\n"
            "默认 1.0s；较短更灵敏，较长更稳。"
        )
        wait_row1.addWidget(self._auto_wait_stable_spin)

        wait_row1.addWidget(QLabel("采样间隔(秒)："))
        self._auto_wait_interval_spin = QDoubleSpinBox()
        self._auto_wait_interval_spin.setRange(0.05, 2.0)
        self._auto_wait_interval_spin.setValue(0.2)
        self._auto_wait_interval_spin.setSingleStep(0.05)
        wait_row1.addWidget(self._auto_wait_interval_spin)

        wait_row1.addWidget(QLabel("到达失败重试："))
        self._auto_wait_retries_spin = QSpinBox()
        self._auto_wait_retries_spin.setRange(0, 10)
        self._auto_wait_retries_spin.setValue(3)
        self._auto_wait_retries_spin.setToolTip(
            "到达失败后重新执行函数调用的次数（任务级重试，不是 verifier 内部重试）。\n"
            "0 = 不重试。"
        )
        wait_row1.addWidget(self._auto_wait_retries_spin)
        wait_row1.addStretch()
        wait_layout.addLayout(wait_row1)

        form.addRow("", wait_group)

        # 初始禁用自动等待配置控件
        self._on_auto_wait_changed(Qt.Unchecked)

        # 初始禁用验证配置控件
        self._on_func_validate_changed(Qt.Unchecked)

        # 加载模块列表到下拉框
        self._load_function_modules()

        return page

    # ------------------------------------------------------------------
    # FUNCTION 页面承接参数辅助方法
    # ------------------------------------------------------------------
    def _on_func_field_changed(self, index):
        """字段选择变化时显示/隐藏自定义输入框。"""
        if hasattr(self, '_func_custom_field_edit'):
            data = self._func_field_combo.itemData(index)
            self._func_custom_field_edit.setVisible(data == "__custom__")

    def _on_func_validate_changed(self, state):
        """结果验证开关变化时启用/禁用配置控件。"""
        enabled = (state == Qt.Checked)
        if hasattr(self, '_func_validate_field_combo'):
            self._func_validate_field_combo.setEnabled(enabled)
        if hasattr(self, '_func_validate_whitelist_edit'):
            self._func_validate_whitelist_edit.setEnabled(enabled)
        if hasattr(self, '_func_validate_retries_spin'):
            self._func_validate_retries_spin.setEnabled(enabled)
        if hasattr(self, '_func_validate_retry_interval_spin'):
            self._func_validate_retry_interval_spin.setEnabled(enabled)

    def _on_auto_wait_changed(self, state):
        """自动等待到达开关变化时启用/禁用配置控件。"""
        enabled = (state == Qt.Checked)
        if hasattr(self, '_auto_wait_timeout_spin'):
            self._auto_wait_timeout_spin.setEnabled(enabled)
        if hasattr(self, '_auto_wait_tolerance_spin'):
            self._auto_wait_tolerance_spin.setEnabled(enabled)
        if hasattr(self, '_auto_wait_stable_spin'):
            self._auto_wait_stable_spin.setEnabled(enabled)
        if hasattr(self, '_auto_wait_interval_spin'):
            self._auto_wait_interval_spin.setEnabled(enabled)
        if hasattr(self, '_auto_wait_retries_spin'):
            self._auto_wait_retries_spin.setEnabled(enabled)

    def _get_func_selected_field(self):
        """获取 FUNCTION 页面当前选择的字段路径。"""
        if not hasattr(self, '_func_field_combo'):
            return ""
        data = self._func_field_combo.currentData()
        if data == "__custom__":
            return self._func_custom_field_edit.text().strip()
        return data or ""

    def _build_func_template(self, field_path):
        """根据选择的来源事件和字段构建模板字符串。"""
        if not hasattr(self, '_func_source_combo'):
            return None
        src = self._func_source_combo.currentData()
        if src is None or not field_path:
            return None
        var_name = src.var_name if src.var_name else src.name.replace(" ", "").replace("_", "")
        return f"${{{var_name}.{field_path}}}"

    def _on_func_fill_args(self):
        """将选择的承接字段填入位置参数。"""
        field = self._get_func_selected_field()
        template = self._build_func_template(field)
        if not template:
            QMessageBox.warning(self.host, "提示", "请先选择来源事件和字段")
            return
        current = self._func_args_edit.text().strip()
        # 如果当前有内容，追加；否则新建
        if current and current != "[]":
            # 解析现有 JSON 并追加
            try:
                args = json.loads(current)
                if isinstance(args, list):
                    args.append(template)
                    self._func_args_edit.setText(json.dumps(args, ensure_ascii=False))
                    return
            except Exception:
                pass
        # 直接设置为单元素列表
        self._func_args_edit.setText(f'["{template}"]')

    def _on_func_fill_kwargs(self):
        """将选择的承接字段填入关键字参数。"""
        field = self._get_func_selected_field()
        template = self._build_func_template(field)
        if not template:
            QMessageBox.warning(self.host, "提示", "请先选择来源事件和字段")
            return
        # 自动推断关键字名
        # 注意：key 必须与目标函数签名一致。
        #   - JHRW 等接受 target_location（不是 location）
        #   - JNYW/ALG/BXG/CSC/DHW/JYC/XLNR/ZZG 等点击函数不接受任何 location
        #     类参数（它们通过 args 接收坐标元组），多余的 kwargs 会被
        #     task_library_manager.call_function 的 _filter_kwargs 自动剔除。
        if field == "target_location":
            key = "target_location"
        elif field == "target_coord.0":
            key = "x"
        elif field == "target_coord.1":
            key = "y"
        elif field == "quest_name":
            key = "quest"
        else:
            key = field.replace(".", "_")

        current = self._func_kwargs_edit.text().strip()
        if current and current != "{}":
            try:
                kwargs = json.loads(current)
                if isinstance(kwargs, dict):
                    kwargs[key] = template
                    self._func_kwargs_edit.setText(json.dumps(kwargs, ensure_ascii=False))
                    return
            except Exception:
                pass
        self._func_kwargs_edit.setText(json.dumps({key: template}, ensure_ascii=False))

    def _on_func_fill_multi(self):
        """填入坐标对到位置参数。"""
        if not hasattr(self, '_func_source_combo'):
            QMessageBox.warning(self.host, "提示", "无前置函数调用事件")
            return
        src = self._func_source_combo.currentData()
        if src is None:
            QMessageBox.warning(self.host, "提示", "请先选择来源事件")
            return
        var_name = src.var_name if src.var_name else src.name.replace(" ", "").replace("_", "")
        template = f'["${{{var_name}.target_coord.0}}", "${{{var_name}.target_coord.1}}"]'
        self._func_args_edit.setText(template)

    def _load_function_modules(self):
        """
        从 task_library 加载已启用模块列表到模块下拉框。

        task_library 不可用或无模块时，下拉框为空并显示提示信息。
        """
        self._func_module_combo.blockSignals(True)
        try:
            self._func_module_combo.clear()
            # 占位项
            self._func_module_combo.addItem("（请选择模块）", "")

            # 添加自动匹配选项
            self._func_module_combo.addItem("【自动匹配地图】 auto", "auto")

            if task_library is None:
                self._func_hint_label.setText(
                    "提示：task_library 模块未加载，无法选择函数。"
                )
                return

            try:
                modules = task_library.get_enabled_modules()
            except Exception as e:
                logger.error(f"获取已启用模块失败: {e}")
                self._func_hint_label.setText(f"提示：获取模块列表失败 - {e}")
                return

            if not modules:
                self._func_hint_label.setText(
                    "提示：当前无已启用的任务库模块，请先在「任务库」标签页中导入并启用模块。"
                )
                return

            # 按模块名排序，便于查找
            for name in sorted(modules.keys()):
                self._func_module_combo.addItem(name, name)
            self._func_hint_label.setText("")
        finally:
            self._func_module_combo.blockSignals(False)

        # 手动触发一次函数列表刷新（因为 blockSignals 跳过了信号）
        self._refresh_function_combo(self._func_module_combo.currentData() or "")

    def _on_function_module_changed(self, _index: int):
        """模块下拉切换时刷新函数下拉。"""
        module_name = self._func_module_combo.currentData() or ""
        self._refresh_function_combo(module_name)

    def _refresh_function_combo(self, module_name: str):
        """
        刷新函数下拉框，列出指定模块的函数。

        :param module_name: 模块名，为空时清空函数下拉
        """
        self._func_function_combo.blockSignals(True)
        try:
            self._func_function_combo.clear()

            # 自动匹配模式：显示说明
            if module_name.lower() == "auto":
                self._func_function_combo.addItem(
                    "（自动匹配 - 留空使用模块名）", ""
                )
                self._func_hint_label.setText(
                    "自动匹配模式：\n"
                    "  运行时将根据上一次函数调用结果中的中文地图名\n"
                    "  在所有地图模块中自动搜索匹配的模块并执行。\n"
                    "  函数名留空则使用匹配到的模块名作为函数名。"
                )
                self._func_hint_label.setStyleSheet("color: #2196F3;")
                return

            self._func_hint_label.setStyleSheet("color: #FF8C00;")

            # 占位项
            self._func_function_combo.addItem("（请选择函数）", "")

            if not module_name or task_library is None:
                return

            try:
                functions = task_library.get_functions(module_name)
            except Exception as e:
                logger.error(f"获取模块 {module_name!r} 的函数列表失败: {e}")
                return

            # functions: [(函数名, 函数对象, 函数签名), ...]
            # 函数签名 sig 已被 manager 加注中文标题（格式: "中文标题 | 原签名"），
            # 因此直接用 sig 作为显示文本，避免重复显示函数名。
            for fname, _fobj, sig in functions:
                display = sig if sig else fname
                self._func_function_combo.addItem(display, fname)
        finally:
            self._func_function_combo.blockSignals(False)

    def load(self, params: dict) -> None:
        """加载函数调用参数到控件。"""
        module_name = str(params.get("module", "") or "")
        function_name = str(params.get("function", "") or "")

        # 选中对应模块（会触发函数列表刷新）
        self.host._set_combo_by_data(self._func_module_combo, module_name, "")
        # 刷新函数下拉后选中对应函数
        self._refresh_function_combo(module_name)
        self.host._set_combo_by_data(self._func_function_combo, function_name, "")

        # args / kwargs 序列化为 JSON 字符串展示
        args_value = params.get("args", [])
        kwargs_value = params.get("kwargs", {})
        try:
            self._func_args_edit.setText(
                json.dumps(args_value, ensure_ascii=False)
                if args_value else ""
            )
        except (TypeError, ValueError):
            self._func_args_edit.setText("")
        try:
            self._func_kwargs_edit.setText(
                json.dumps(kwargs_value, ensure_ascii=False)
                if kwargs_value else ""
            )
        except (TypeError, ValueError):
            self._func_kwargs_edit.setText("")

        # 结果验证配置
        validate_field = params.get("result_validate_field", None)
        validate_whitelist = params.get("result_validate_whitelist", None)
        validate_retries = params.get("result_validate_retries", 3)
        validate_interval = params.get("result_validate_retry_interval", 0.5)

        if validate_field and validate_whitelist:
            self._func_validate_check.setChecked(True)
            self.host._set_combo_by_data(self._func_validate_field_combo, validate_field, "target_location")
            self._func_validate_whitelist_edit.setText(",".join(validate_whitelist))
            self._func_validate_retries_spin.setValue(int(validate_retries))
            self._func_validate_retry_interval_spin.setValue(float(validate_interval))
        else:
            self._func_validate_check.setChecked(False)
            self._func_validate_whitelist_edit.clear()

        # 自动等待到达配置（事件驱动版，2026-08-05）
        auto_wait = params.get("auto_wait_arrival", False)
        self._auto_wait_check.setChecked(bool(auto_wait))
        self._auto_wait_timeout_spin.setValue(
            float(params.get("wait_arrival_timeout", 0.0))
        )
        self._auto_wait_tolerance_spin.setValue(
            float(params.get("wait_arrival_tolerance", 3.0))
        )
        # 静止确认秒数（新逻辑）；向后兼容老任务的 wait_arrival_stable_count
        _stable = params.get("wait_arrival_stop_confirm_s")
        if _stable is None:
            _stable = params.get("wait_arrival_stable_count")
            if _stable is not None:
                # 老字段是次数（默认 5 次 ≈ 1 秒），转换为秒数
                _stable = float(_stable) / 5.0
        self._auto_wait_stable_spin.setValue(float(_stable if _stable is not None else 1.0))
        self._auto_wait_interval_spin.setValue(
            float(params.get("wait_arrival_sample_interval", 0.2))
        )
        self._auto_wait_retries_spin.setValue(
            int(params.get("wait_arrival_retries", 3))
        )
        self._on_auto_wait_changed(
            self._auto_wait_check.isChecked()
        )

    def apply(self, event: Event) -> bool:
        """
        将函数调用参数写回 Event.params。

        args / kwargs 以 JSON 字符串输入，解析失败时弹出警告并返回 False
        阻止对话框关闭。
        """
        # 模块 / 函数
        module_name = self._func_module_combo.currentData() or ""
        function_name = self._func_function_combo.currentData() or ""
        # 若 currentData 为空（占位项被选中），不使用 currentText（占位文本）
        # 保持 function_name 为空字符串，由用户选择具体函数

        # 解析 args JSON
        args_text = self._func_args_edit.text().strip()
        if args_text:
            try:
                args_value = json.loads(args_text)
                if not isinstance(args_value, list):
                    raise ValueError("位置参数必须是 JSON 数组")
            except (json.JSONDecodeError, ValueError) as e:
                QMessageBox.warning(
                    self.host, "参数错误",
                    f"位置参数 (JSON) 解析失败：\n{e}\n\n请输入合法的 JSON 数组，如 [1, 2, \"a\"]"
                )
                return False
        else:
            args_value = []

        # 解析 kwargs JSON
        kwargs_text = self._func_kwargs_edit.text().strip()
        if kwargs_text:
            try:
                kwargs_value = json.loads(kwargs_text)
                if not isinstance(kwargs_value, dict):
                    raise ValueError("关键字参数必须是 JSON 对象")
            except (json.JSONDecodeError, ValueError) as e:
                QMessageBox.warning(
                    self.host, "参数错误",
                    f"关键字参数 (JSON) 解析失败：\n{e}\n\n请输入合法的 JSON 对象，如 {{\"a\": 1}}"
                )
                return False
        else:
            kwargs_value = {}

        # 结果验证配置
        validate_enabled = self._func_validate_check.isChecked()
        result_validate = {}
        if validate_enabled:
            validate_field = self._func_validate_field_combo.currentData() or "target_location"
            whitelist_text = self._func_validate_whitelist_edit.text().strip()
            validate_whitelist = [v.strip() for v in whitelist_text.split(",") if v.strip()] if whitelist_text else None
            validate_retries = self._func_validate_retries_spin.value()
            validate_interval = self._func_validate_retry_interval_spin.value()

            if validate_whitelist:
                result_validate = {
                    "result_validate_field": validate_field,
                    "result_validate_whitelist": validate_whitelist,
                    "result_validate_retries": validate_retries,
                    "result_validate_retry_interval": validate_interval,
                }

        event.params = {
            "module": module_name,
            "function": function_name,
            "args": args_value,
            "kwargs": kwargs_value,
        }
        # 合并结果验证配置
        event.params.update(result_validate)

        # 自动等待到达配置
        event.params["auto_wait_arrival"] = self._auto_wait_check.isChecked()
        event.params["wait_arrival_timeout"] = self._auto_wait_timeout_spin.value()
        event.params["wait_arrival_tolerance"] = self._auto_wait_tolerance_spin.value()
        event.params["wait_arrival_stop_confirm_s"] = self._auto_wait_stable_spin.value()
        event.params["wait_arrival_sample_interval"] = self._auto_wait_interval_spin.value()
        event.params["wait_arrival_retries"] = self._auto_wait_retries_spin.value()

        return True


class ConditionParamPage(BaseParamPage):
    """条件分支参数页（增强版，已从 EventEditorDialog 抽出，PR #8 收口）。"""

    def build(self) -> QWidget:
        """
        条件分支参数页（增强版）。

        支持两种模式：
        - simple：简单比较（原模式）
        - switch：开关分支模式，按字段值匹配 case 并执行对应动作
        """
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(8, 8, 8, 8)

        # ---- 模式切换 ----
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("模式："))
        self._cond_mode_combo = QComboBox()
        self._cond_mode_combo.addItem("简单比较 (==/!=/>/<)", "simple")
        self._cond_mode_combo.addItem(
            "开关分支（按地图名匹配动作，推荐）", "switch"
        )
        self._cond_mode_combo.currentIndexChanged.connect(
            self._on_cond_mode_changed
        )
        mode_row.addWidget(self._cond_mode_combo, 1)
        page_layout.addLayout(mode_row)

        # ---- 模式 1: simple（堆叠页 0） ----
        self._cond_simple_page = QWidget()
        simple_form = QFormLayout(self._cond_simple_page)
        simple_form.setLabelAlignment(Qt.AlignRight)

        self._cond_variable_edit = QLineEdit()
        self._cond_variable_edit.setPlaceholderText(
            "如 last_result.target_location 或 函数调用3.target_location"
        )
        simple_form.addRow("变量名：", self._cond_variable_edit)

        self._cond_operator_combo = QComboBox()
        self._cond_operator_combo.addItem("==", "==")
        self._cond_operator_combo.addItem("!=", "!=")
        self._cond_operator_combo.addItem(">", ">")
        self._cond_operator_combo.addItem("<", "<")
        self._cond_operator_combo.addItem(">=", ">=")
        self._cond_operator_combo.addItem("<=", "<=")
        simple_form.addRow("运算符：", self._cond_operator_combo)

        self._cond_value_edit = QLineEdit()
        self._cond_value_edit.setPlaceholderText(
            '比较值（数字 / true/false / "字符串"）'
        )
        simple_form.addRow("比较值：", self._cond_value_edit)
        page_layout.addWidget(self._cond_simple_page)

        # ---- 模式 2: switch（堆叠页 1） ----
        self._cond_switch_page = QWidget()
        switch_layout = QVBoxLayout(self._cond_switch_page)
        switch_layout.setContentsMargins(0, 0, 0, 0)

        # 匹配字段选择
        field_row = QHBoxLayout()
        field_row.addWidget(QLabel("匹配字段："))
        self._cond_match_field_combo = QComboBox()
        self._cond_match_field_combo.setMinimumWidth(140)
        self._cond_match_field_combo.addItem("目标地点（target_location）", "target_location")
        self._cond_match_field_combo.addItem("任务名称（quest_name）", "quest_name")
        self._cond_match_field_combo.addItem("进度数值（progress_num）", "progress_num")
        self._cond_match_field_combo.addItem("地图名称（map_name）", "map_name")
        self._cond_match_field_combo.addItem("自定义字段...", "__custom__")
        self._cond_match_field_combo.currentIndexChanged.connect(
            self._on_cond_match_field_changed
        )
        field_row.addWidget(self._cond_match_field_combo, 1)
        switch_layout.addLayout(field_row)

        self._cond_match_custom_field_edit = QLineEdit()
        self._cond_match_custom_field_edit.setPlaceholderText(
            "自定义字段名，如 custom_field"
        )
        self._cond_match_custom_field_edit.setVisible(False)
        switch_layout.addWidget(self._cond_match_custom_field_edit)

        # 来源变量（指定从哪个函数结果取值，避免多函数事件歧义）
        src_row = QHBoxLayout()
        src_row.addWidget(QLabel("来源变量："))
        self._cond_source_var_edit = QLineEdit()
        self._cond_source_var_edit.setPlaceholderText("如 JHRW（留空=自动搜索）")
        src_row.addWidget(self._cond_source_var_edit, 1)
        switch_layout.addLayout(src_row)

        # Case 列表（表格）：匹配值 | 步数 | 操作序列
        case_group = QGroupBox("Case 列表（匹配值 -> 操作序列）")
        case_layout = QVBoxLayout(case_group)

        self._cond_cases_table = QTableWidget(0, 3)
        self._cond_cases_table.setHorizontalHeaderLabels([
            "匹配值", "步数", "操作序列"
        ])
        self._cond_cases_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch
        )
        self._cond_cases_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._cond_cases_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._cond_cases_table.verticalHeader().setVisible(False)
        case_layout.addWidget(self._cond_cases_table)

        # Case 操作按钮
        case_btn_row = QHBoxLayout()
        add_case_btn = QPushButton("+ 添加 Case")
        add_case_btn.clicked.connect(self._on_add_case)
        case_btn_row.addWidget(add_case_btn)

        del_case_btn = QPushButton("- 删除选中")
        del_case_btn.clicked.connect(self._on_del_case)
        case_btn_row.addWidget(del_case_btn)

        preset_btn = QPushButton("快速添加：从地图坐标.txt")
        preset_btn.clicked.connect(self._on_preset_cases_from_file)
        case_btn_row.addWidget(preset_btn, 1)
        case_layout.addLayout(case_btn_row)
        switch_layout.addWidget(case_group)

        # 默认动作
        default_group = QGroupBox("默认动作（无 Case 命中时执行）")
        default_form = QFormLayout(default_group)
        default_form.setLabelAlignment(Qt.AlignRight)

        self._cond_default_action_combo = QComboBox()
        self._cond_default_action_combo.addItem("不执行任何动作", "none")
        self._cond_default_action_combo.addItem("直接点击坐标", "click")
        self._cond_default_action_combo.addItem("从坐标文件查找并点击", "file_lookup")
        self._cond_default_action_combo.addItem("子流程（多步操作）", "subflow")
        self._cond_default_action_combo.currentIndexChanged.connect(
            self._on_cond_default_action_changed
        )
        default_form.addRow("动作类型：", self._cond_default_action_combo)

        # 默认动作 - click 参数
        self._cond_default_click_row = QWidget()
        dc_layout = QHBoxLayout(self._cond_default_click_row)
        dc_layout.setContentsMargins(0, 0, 0, 0)
        dc_layout.addWidget(QLabel("X:"))
        self._cond_default_x_edit = QLineEdit()
        self._cond_default_x_edit.setPlaceholderText("如 727")
        dc_layout.addWidget(self._cond_default_x_edit, 1)
        dc_layout.addWidget(QLabel("Y:"))
        self._cond_default_y_edit = QLineEdit()
        self._cond_default_y_edit.setPlaceholderText("如 438")
        dc_layout.addWidget(self._cond_default_y_edit, 1)
        dc_layout.addWidget(QLabel("按键:"))
        self._cond_default_button_combo = QComboBox()
        self._cond_default_button_combo.addItem("左键", "left")
        self._cond_default_button_combo.addItem("右键", "right")
        self._cond_default_button_combo.addItem("双击", "double")
        dc_layout.addWidget(self._cond_default_button_combo)
        self._cond_default_click_row.setVisible(False)
        default_form.addRow("", self._cond_default_click_row)

        # 默认动作 - file_lookup 参数
        self._cond_default_file_row = QWidget()
        df_layout = QVBoxLayout(self._cond_default_file_row)
        df_layout.setContentsMargins(0, 0, 0, 0)
        df_row1 = QHBoxLayout()
        df_row1.addWidget(QLabel("坐标文件:"))
        self._cond_default_file_edit = QLineEdit()
        self._cond_default_file_edit.setPlaceholderText(
            config.map_coord_file
        )
        df_row1.addWidget(self._cond_default_file_edit, 1)
        df_browse = QPushButton("浏览...")
        df_browse.clicked.connect(
            lambda: self.host._on_browse_file(
                self._cond_default_file_edit,
                "文本文件 (*.txt);;所有文件 (*.*)",
            )
        )
        df_row1.addWidget(df_browse)
        df_layout.addLayout(df_row1)
        df_row2 = QHBoxLayout()
        df_row2.addWidget(QLabel("按键:"))
        self._cond_default_file_button_combo = QComboBox()
        self._cond_default_file_button_combo.addItem("左键", "left")
        self._cond_default_file_button_combo.addItem("右键", "right")
        self._cond_default_file_button_combo.addItem("双击", "double")
        df_row2.addWidget(self._cond_default_file_button_combo)
        df_row2.addStretch(1)
        df_layout.addLayout(df_row2)
        self._cond_default_file_row.setVisible(False)
        default_form.addRow("", self._cond_default_file_row)

        # 默认动作 - 子流程（多步操作）
        self._cond_default_subflow_row = QWidget()
        ds_layout = QHBoxLayout(self._cond_default_subflow_row)
        ds_layout.setContentsMargins(0, 0, 0, 0)
        ds_layout.addWidget(QLabel("操作序列："))
        self._cond_default_subflow_btn = QPushButton("编辑默认子流程…")
        self._cond_default_subflow_btn.clicked.connect(self._on_edit_default_subflow)
        ds_layout.addWidget(self._cond_default_subflow_btn)
        ds_layout.addStretch(1)
        self._cond_default_subflow_row.setVisible(False)
        default_form.addRow("", self._cond_default_subflow_row)
        switch_layout.addWidget(default_group)

        # 模式堆叠（最后切换）
        self._cond_mode_stack = QStackedWidget()
        self._cond_mode_stack.addWidget(self._cond_simple_page)
        self._cond_mode_stack.addWidget(self._cond_switch_page)
        # 将原先的 simple 控件替换为堆叠，重新插入到 page 的正确位置
        # 先移除 simple_page（已经在 page_layout 中），再插入 stack
        page_layout.removeWidget(self._cond_simple_page)
        page_layout.addWidget(self._cond_mode_stack)

        # 初始化
        self._on_cond_mode_changed(0)

        return page

    # ------------------------------------------------------------------
    # 条件分支模式切换辅助
    # ------------------------------------------------------------------
    def _on_cond_mode_changed(self, index):
        mode = self._cond_mode_combo.itemData(index) or "simple"
        if mode == "switch":
            self._cond_mode_stack.setCurrentIndex(1)
        else:
            self._cond_mode_stack.setCurrentIndex(0)

    def _on_cond_match_field_changed(self, index):
        data = self._cond_match_field_combo.itemData(index) or "target_location"
        self._cond_match_custom_field_edit.setVisible(data == "__custom__")

    def _on_cond_default_action_changed(self, index):
        action = self._cond_default_action_combo.itemData(index) or "none"
        self._cond_default_click_row.setVisible(action == "click")
        self._cond_default_file_row.setVisible(action == "file_lookup")
        self._cond_default_subflow_row.setVisible(action == "subflow")

    # ------------------------------------------------------------------
    # switch case 子流程相关辅助
    # ------------------------------------------------------------------
    def _ensure_case_subflows(self):
        """保证 self._case_subflows 存在并与表格行数对齐。"""
        if not hasattr(self, "_case_subflows") or self._case_subflows is None:
            self._case_subflows = []
        while len(self._case_subflows) < self._cond_cases_table.rowCount():
            self._case_subflows.append([])

    def _case_button_row(self, button) -> int:
        """根据子流程按钮反查其所在表格行（避免删除行后行号错位）。"""
        for r in range(self._cond_cases_table.rowCount()):
            w = self._cond_cases_table.cellWidget(r, 2)
            if w is button:
                return r
        return -1

    def _refresh_case_steps(self):
        """刷新每行的'步数'列，反映对应子流程的事件数。"""
        self._ensure_case_subflows()
        for r in range(self._cond_cases_table.rowCount()):
            subflow = self._case_subflows[r] if r < len(self._case_subflows) else []
            item = self._cond_cases_table.item(r, 1)
            if item is not None:
                item.setText(f"{len(subflow)} 步")

    def _edit_subflow_dialog(self, subflow: List[Event]) -> bool:
        """打开子流程编辑器，返回用户是否确认。

        把父 EventEditorDialog 已知的"父任务前序事件"作为 context_events 传进去，
        这样子流程里编辑函数调用时，"承接参数"下拉能引用到父任务里更早的
        JHRW 等函数调用结果——而非只能看到子流程内前序。
        """
        dlg = SubFlowEditorDialog(subflow, self.host, self.host._previous_events)
        return dlg.exec_() == QDialog.Accepted

    def _on_add_case(self):
        """添加一个空的 case 行（含一个空子流程）。"""
        self._ensure_case_subflows()
        row = self._cond_cases_table.rowCount()
        self._cond_cases_table.insertRow(row)

        self._cond_cases_table.setItem(row, 0, QTableWidgetItem("江南野外"))
        self._cond_cases_table.setItem(row, 1, QTableWidgetItem("0 步"))

        btn = QPushButton("编辑子流程…")
        # ConditionParamPage 不是 QObject 子类，没有 self.sender()；
        # 用 functools.partial 把按钮引用作为参数传入
        btn.clicked.connect(
            functools.partial(self._on_edit_case_subflow, btn)
        )
        self._cond_cases_table.setCellWidget(row, 2, btn)

        self._case_subflows.append([])

    def _on_del_case(self):
        """删除选中的 case 行，并同步删除对应子流程。"""
        self._ensure_case_subflows()
        row = self._cond_cases_table.currentRow()
        if row >= 0:
            self._cond_cases_table.removeRow(row)
            if 0 <= row < len(self._case_subflows):
                del self._case_subflows[row]
            self._refresh_case_steps()

    def _on_edit_case_subflow(self, btn=None):
        """编辑当前 case 行的子流程（操作序列）。

        :param btn: 触发按钮（由 functools.partial 传入）。
            ConditionParamPage 不是 QObject 子类，没有 self.sender()，
            因此按钮引用必须由连接处显式传入，不能运行时查询。
        """
        self._ensure_case_subflows()
        row = self._case_button_row(btn) if btn is not None else self._cond_cases_table.currentRow()
        if row < 0 or row >= self._cond_cases_table.rowCount():
            return
        while len(self._case_subflows) <= row:
            self._case_subflows.append([])
        if self._edit_subflow_dialog(self._case_subflows[row]):
            self._refresh_case_steps()

    def _on_edit_default_subflow(self):
        """编辑 default 动作的子流程。"""
        if not hasattr(self, "_default_subflow") or self._default_subflow is None:
            self._default_subflow = []
        if self._edit_subflow_dialog(self._default_subflow):
            pass

    def _on_preset_cases_from_file(self):
        """
        从地图坐标.txt中读取条目，自动添加所有 case（每 case 一个空子流程，
        用户随后在'编辑子流程'里配置各自的操作序列）。
        """
        coord_file = config.map_coord_file
        if not os.path.isfile(coord_file):
            path, _ = QFileDialog.getOpenFileName(
                self.host, "选择地图坐标文件", "",
                "文本文件 (*.txt);;所有文件 (*.*)"
            )
            if not path:
                return
            coord_file = path

        entries = []
        try:
            with open(coord_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split()
                    if len(parts) < 2:
                        continue
                    map_name = parts[0].strip()
                    coord_str = parts[1].strip()
                    if "," in coord_str:
                        xstr, ystr = coord_str.split(",", 1)
                    elif len(parts) >= 3:
                        xstr, ystr = parts[1], parts[2]
                    else:
                        continue
                    try:
                        int(xstr.strip())
                        int(ystr.strip())
                        entries.append(map_name)
                    except (ValueError, TypeError):
                        continue
        except Exception as e:
            QMessageBox.warning(self.host, "读取失败", f"读取坐标文件失败:\n{e}")
            return

        if not entries:
            QMessageBox.information(self.host, "提示", "文件中未找到有效条目")
            return

        # 清空现有行与子流程
        self._cond_cases_table.setRowCount(0)
        self._case_subflows = []

        for map_name in entries:
            row = self._cond_cases_table.rowCount()
            self._cond_cases_table.insertRow(row)
            self._cond_cases_table.setItem(row, 0, QTableWidgetItem(map_name))
            self._cond_cases_table.setItem(row, 1, QTableWidgetItem("0 步"))
            btn = QPushButton("编辑子流程…")
            btn.clicked.connect(functools.partial(self._on_edit_case_subflow, btn))
            self._cond_cases_table.setCellWidget(row, 2, btn)
            self._case_subflows.append([])

        QMessageBox.information(
            self.host, "成功",
            f"已从地图坐标文件中导入 {len(entries)} 个 Case（均为空子流程，请逐一编辑操作序列）"
        )

    def load(self, params: dict) -> None:
        """加载条件分支参数到控件（支持 simple 和 switch 两种模式）。"""
        mode = str(params.get("mode", "simple") or "simple").lower()
        self.host._set_combo_by_data(self._cond_mode_combo, mode, "simple")
        # 触发模式切换
        self._on_cond_mode_changed(self._cond_mode_combo.currentIndex())

        if mode == "switch":
            # 匹配字段
            match_field = params.get("match_field", "target_location") or "target_location"
            self.host._set_combo_by_data(
                self._cond_match_field_combo, match_field, "target_location"
            )
            self._cond_match_custom_field_edit.setText(
                str(params.get("match_custom_field", "") or "")
            )
            self._on_cond_match_field_changed(
                self._cond_match_field_combo.currentIndex()
            )
            # 来源变量
            self._cond_source_var_edit.setText(
                str(params.get("source_var", "") or "")
            )

            # Case 列表（每 case = 匹配值 + 子流程操作序列）
            cases = params.get("cases", []) or []
            self._cond_cases_table.setRowCount(0)
            self._case_subflows = []
            for case in cases:
                row = self._cond_cases_table.rowCount()
                self._cond_cases_table.insertRow(row)

                # 匹配值
                self._cond_cases_table.setItem(
                    row, 0,
                    QTableWidgetItem(str(case.get("match_value", "") or ""))
                )

                # 子流程：优先用 actions 列表；旧格式单动作则升级为 1 步子流程
                actions = case.get("actions")
                if isinstance(actions, list):
                    subflow = [
                        (Event.from_dict(a) if isinstance(a, dict) else a)
                        for a in actions
                    ]
                elif case.get("action"):
                    subflow = [_legacy_case_to_event(case)]
                else:
                    subflow = []
                self._case_subflows.append(subflow)

                # 步数 + 编辑按钮
                self._cond_cases_table.setItem(
                    row, 1, QTableWidgetItem(f"{len(subflow)} 步")
                )
                btn = QPushButton("编辑子流程…")
                btn.clicked.connect(functools.partial(self._on_edit_case_subflow, btn))
                self._cond_cases_table.setCellWidget(row, 2, btn)

            # 默认动作
            default_action = params.get("default_action") or {}
            default_act = str(default_action.get("action", "none") or "none")
            self.host._set_combo_by_data(
                self._cond_default_action_combo, default_act, "none"
            )
            self._on_cond_default_action_changed(
                self._cond_default_action_combo.currentIndex()
            )

            self._cond_default_x_edit.setText(
                str(default_action.get("x", "") or "")
            )
            self._cond_default_y_edit.setText(
                str(default_action.get("y", "") or "")
            )
            self.host._set_combo_by_data(
                self._cond_default_button_combo,
                str(default_action.get("button", "left") or "left"),
                "left",
            )
            self._cond_default_file_edit.setText(
                str(default_action.get("coord_file", "") or "")
            )
            self.host._set_combo_by_data(
                self._cond_default_file_button_combo,
                str(default_action.get("button", "left") or "left"),
                "left",
            )
            # 默认子流程（仅当 action=subflow 且带 actions 时加载）
            self._default_subflow = []
            if default_act == "subflow":
                dacts = default_action.get("actions")
                if isinstance(dacts, list):
                    self._default_subflow = [
                        (Event.from_dict(a) if isinstance(a, dict) else a)
                        for a in dacts
                    ]
        else:
            # simple 模式
            self._cond_variable_edit.setText(
                str(params.get("variable", "") or "")
            )
            self.host._set_combo_by_data(
                self._cond_operator_combo, params.get("operator", "=="), "=="
            )
            value = params.get("value", "")
            if isinstance(value, str):
                text = value
            else:
                try:
                    text = json.dumps(value, ensure_ascii=False)
                except (TypeError, ValueError):
                    text = str(value)
            self._cond_value_edit.setText(text)

    def apply(self, event: Event) -> bool:
        """
        将条件分支参数写回 Event.params。

        支持 simple 和 switch 两种模式：
        - simple：variable/operator/value（原格式，向后兼容）
        - switch：match_field/cases/default_action
        """
        mode = self._cond_mode_combo.currentData() or "simple"
        old_params = event.params or {}
        true_branch = old_params.get("true_branch", [])
        false_branch = old_params.get("false_branch", [])

        if mode == "switch":
            # switch 模式
            match_field = (
                self._cond_match_field_combo.currentData() or "target_location"
            )
            match_custom_field = (
                self._cond_match_custom_field_edit.text().strip()
                if match_field == "__custom__"
                else ""
            )
            source_var = self._cond_source_var_edit.text().strip()

            # 收集 cases（每 case 一个完整子流程操作序列）
            self._ensure_case_subflows()
            cases = []
            for row in range(self._cond_cases_table.rowCount()):
                match_value_item = self._cond_cases_table.item(row, 0)
                match_value = (
                    match_value_item.text().strip() if match_value_item else ""
                )
                if not match_value:
                    continue
                subflow = (
                    self._case_subflows[row]
                    if row < len(self._case_subflows) else []
                )
                case = {
                    "match_value": match_value,
                    "actions": [e.to_dict() for e in subflow],
                }
                cases.append(case)

            # 默认动作
            default_act = (
                self._cond_default_action_combo.currentData() or "none"
            )
            if default_act == "subflow":
                subflow = getattr(self, "_default_subflow", None) or []
                default_action = {
                    "action": "subflow",
                    "actions": [e.to_dict() for e in subflow],
                }
            else:
                default_action = {"action": default_act}
                if default_act == "click":
                    try:
                        default_action["x"] = int(self._cond_default_x_edit.text())
                    except (ValueError, TypeError):
                        default_action["x"] = 0
                    try:
                        default_action["y"] = int(self._cond_default_y_edit.text())
                    except (ValueError, TypeError):
                        default_action["y"] = 0
                    default_action["button"] = (
                        self._cond_default_button_combo.currentData() or "left"
                    )
                elif default_act == "file_lookup":
                    _coord_file = self._cond_default_file_edit.text().strip()
                    # 默认值不写入 JSON（运行时回退 config.map_coord_file）
                    if _coord_file == config.map_coord_file:
                        _coord_file = ""
                    default_action["coord_file"] = _coord_file
                    default_action["button"] = (
                        self._cond_default_file_button_combo.currentData()
                        or "left"
                    )

            event.params = {
                "mode": "switch",
                "match_field": match_field,
                "match_custom_field": match_custom_field,
                "source_var": source_var,
                "cases": cases,
                "default_action": default_action,
                "true_branch": true_branch,
                "false_branch": false_branch,
            }
            return True

        # simple 模式（向后兼容）
        value_text = self._cond_value_edit.text()
        parsed_value = self.host._try_parse_value(value_text)
        event.params = {
            "mode": "simple",
            "variable": self._cond_variable_edit.text(),
            "operator": self._cond_operator_combo.currentData() or "==",
            "value": parsed_value,
            "true_branch": true_branch,
            "false_branch": false_branch,
        }
        return True
