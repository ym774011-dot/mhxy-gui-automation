# -*- coding: utf-8 -*-
"""
MHXY GUI 自动化脚本平台 - 任务编辑器面板（Task 11）。

实现 ``TaskEditor(QWidget)``，作为"任务编辑"标签页的内容面板，提供
任务序列的可视化编辑能力：

    - 左侧（任务/事件列表区）：
        * 任务列表 QGroupBox：QComboBox 选择当前任务 + 新建/删除按钮
          + 任务属性编辑（名称、描述、循环次数、循环间隔）
        * 事件列表 QGroupBox：QListWidget 显示当前任务的事件
          + 添加/编辑/删除/上移/下移 按钮行
    - 右侧（事件详情区）：
        * 显示选中事件的基本信息（类型、名称、参数 JSON 预览）
        * 完整的事件参数编辑器将在 Task 12 中实现

核心模型对象引用关系：
    - ``self._task_sequence``：当前编辑的 TaskSequence（与 MainWindow 共享同一引用）
    - ``self._current_task``：当前选中的 Task
    - 所有增删改操作直接作用于上述模型对象，``get_task_sequence()``
      返回的即是被编辑的同一实例。
"""
import json

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from models.event import Event, EventType
from models.task import Task
from models.task_sequence import TaskSequence
from utils.logger import logger


# ----------------------------------------------------------------------
# 事件类型元信息：图标 / 中文名 / 默认参数模板
# 集中管理，便于事件类型选择对话框与新建事件时复用。
# ----------------------------------------------------------------------

_EVENT_TYPE_INFO = {
    EventType.CLICK: (
        "🖱", "鼠标点击",
        {
            "x": 0, "y": 0, "button": "left", "background": False,
            "press_delay": 0.05,  # 按下→弹起保持时间（秒），可 GUI 配置
        },
    ),
    EventType.KEY: (
        "⌨", "键盘输入",
        {
            "keys": "", "text": "", "duration": 0.0,
        },
    ),
    EventType.WAIT: (
        "⏱", "等待延迟",
        {
            "duration": 1.0, "wait_for_image": False,
            "image_path": "", "timeout": 10.0,
        },
    ),
    EventType.IMAGE: (
            "🖼", "图像识别",
            {
                "source_mode": "direct",
                "template_path": "", "threshold": 0.8,
                "action": "click", "button": "left",
                "click_delay": 300,
                "region": [0, 0, 0, 0],
                # 动态构建
                "prefix": "", "dir_path": "", "suffix": ".bmp",
                "dyn_field": "target_location", "dyn_custom_field": "",
                # 批量识别
                "batch_dir": "", "batch_ext": ".bmp",
                "batch_use_var": False,
                "batch_var_field": "target_location",
                "batch_sort": "name", "batch_click_mode": "all",
                # 附加点击（图像识别点击后执行）
                "additional_click_enabled": False,
                "additional_mode": "direct",
                "additional_x": "",
                "additional_y": "",
                "coord_file": "E:/DS/梦幻西游脚本函数包/地图数据/地图坐标.txt",
                "match_field": "target_location",
                "match_custom_field": "",
                "additional_button": "left",
                "additional_delay": 200,
                # 操作结果验证
            },
        ),
    EventType.YOLO: (
        "👁", "YOLO 检测",
        {
            "template_path": "", "threshold": 0.8,
            "action": "click", "region": [0, 0, 0, 0],
        },
    ),
    EventType.FUNCTION: (
        "⚙", "函数调用",
        {
            "module": "", "function": "", "args": [], "kwargs": {},
        },
    ),
    EventType.CONDITION: (
        "❓", "条件分支",
        {
            "mode": "switch",           # simple / switch
            # simple 模式字段
            "variable": "", "operator": "==", "value": "",
            # switch 模式字段
            "match_field": "target_location",
            "match_custom_field": "",
            "cases": [],
            "default_action": {"action": "none"},
            # 保持向后兼容
            "true_branch": [], "false_branch": [],
        },
    ),
}


def _event_type_icon(event_type):
    """返回事件类型对应的图标字符串，未知类型回退到空串。"""
    info = _EVENT_TYPE_INFO.get(event_type)
    return info[0] if info else ""


def _event_type_name(event_type):
    """返回事件类型对应的中文名，未知类型回退到类型字符串本身。"""
    info = _EVENT_TYPE_INFO.get(event_type)
    return info[1] if info else str(event_type)


def _default_params(event_type):
    """返回事件类型的默认参数（深拷贝，避免共享引用）。"""
    info = _EVENT_TYPE_INFO.get(event_type)
    if info:
        # json 往返实现深拷贝，保证每次新建事件参数相互独立
        return json.loads(json.dumps(info[2]))
    return {}


# ----------------------------------------------------------------------
# 事件类型选择对话框
# ----------------------------------------------------------------------
class EventTypeDialog(QDialog):
    """
    事件类型选择对话框。

    列出所有事件类型供用户选择，确认后通过 ``selected_type()`` 获取
    选中的事件类型字符串；取消则返回 None。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("选择事件类型")
        self.setMinimumWidth(340)
        self._selected_type = None
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        tip = QLabel("请选择要添加的事件类型：")
        layout.addWidget(tip)

        self._list = QListWidget()
        # 遍历所有事件类型，按 EventType.all() 顺序展示
        for et in EventType.all():
            icon = _event_type_icon(et)
            name = _event_type_name(et)
            item = QListWidgetItem(f"{icon}  {name}    ({et})")
            item.setData(Qt.UserRole, et)
            self._list.addItem(item)
        # 默认选中第一项
        if self._list.count() > 0:
            self._list.setCurrentRow(0)
        # 双击即确认
        self._list.itemDoubleClicked.connect(self._on_accept)
        layout.addWidget(self._list)

        # 确定 / 取消按钮
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self._on_accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _on_accept(self, *_args):
        """确认选择：记录选中类型后关闭对话框。"""
        item = self._list.currentItem()
        if item is not None:
            self._selected_type = item.data(Qt.UserRole)
            self.accept()
        else:
            # 未选中任何项时不允许确认
            QMessageBox.warning(self, "提示", "请先选择一个事件类型。")

    def selected_type(self):
        """返回用户选中的事件类型字符串，未确认时返回 None。"""
        return self._selected_type


# ----------------------------------------------------------------------
# 任务编辑器主面板
# ----------------------------------------------------------------------
class TaskEditor(QWidget):
    """
    任务编辑器面板。

    通过 ``set_task_sequence()`` 绑定一个 ``TaskSequence`` 实例后即可
    在界面上编辑其任务与事件；所有修改直接作用于绑定的对象，
    ``get_task_sequence()`` 返回的即是同一引用。
    """

    # 任务序列发生结构性变化（增删任务/事件、移动）时发射，
    # 供 MainWindow 同步"是否需要保存"等状态
    task_sequence_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)

        # 当前编辑的任务序列（与 MainWindow 共享同一引用）
        self._task_sequence: TaskSequence = None
        # 当前选中的任务
        self._current_task: Task = None

        # 同步标志：在程序化刷新 UI 时置 True，避免回写信号触发循环
        self._syncing = False

        self._init_ui()

    # ==================================================================
    # UI 构建
    # ==================================================================
    def _init_ui(self):
        """初始化整体布局：水平分割（左列表区 | 右详情区）。"""
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(6, 6, 6, 6)

        splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(splitter)

        # 左侧：任务列表 + 事件列表
        left_panel = self._build_left_panel()
        splitter.addWidget(left_panel)

        # 右侧：事件详情
        right_panel = self._build_right_panel()
        splitter.addWidget(right_panel)

        # 比例：左 3 : 右 2
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

    # ------------------------------------------------------------------
    # 左侧面板
    # ------------------------------------------------------------------
    def _build_left_panel(self) -> QWidget:
        """构建左侧面板：任务列表区 + 事件列表区。"""
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)

        # 任务列表区
        layout.addWidget(self._build_task_group())
        # 事件列表区（占据剩余空间）
        layout.addWidget(self._build_event_group(), 1)

        return container

    def _build_task_group(self) -> QGroupBox:
        """构建"任务列表"分组：下拉选择 + 新建/删除 + 任务属性编辑。"""
        group = QGroupBox("任务列表")
        layout = QVBoxLayout(group)

        # 任务选择下拉框
        self._task_combo = QComboBox()
        self._task_combo.currentIndexChanged.connect(self._on_task_changed)
        layout.addWidget(self._task_combo)

        # 新建 / 删除任务按钮行
        btn_row = QHBoxLayout()
        new_task_btn = QPushButton("新建任务")
        del_task_btn = QPushButton("删除任务")
        new_task_btn.clicked.connect(self._on_new_task)
        del_task_btn.clicked.connect(self._on_delete_task)
        btn_row.addWidget(new_task_btn)
        btn_row.addWidget(del_task_btn)
        layout.addLayout(btn_row)

        # 任务属性编辑表单
        form = QFormLayout()
        self._task_name_edit = QLineEdit()
        self._task_name_edit.setPlaceholderText("任务名称")
        self._task_name_edit.editingFinished.connect(self._on_task_property_changed)

        self._task_desc_edit = QLineEdit()
        self._task_desc_edit.setPlaceholderText("任务描述")
        self._task_desc_edit.editingFinished.connect(self._on_task_property_changed)

        # 循环次数：0 表示无限循环
        self._loop_count_spin = QSpinBox()
        self._loop_count_spin.setRange(0, 999999)
        self._loop_count_spin.setSpecialValueText("无限")
        self._loop_count_spin.valueChanged.connect(self._on_task_property_changed)

        # 循环间隔（秒）
        self._loop_delay_spin = QDoubleSpinBox()
        self._loop_delay_spin.setRange(0.0, 86400.0)
        self._loop_delay_spin.setSingleStep(0.1)
        self._loop_delay_spin.setDecimals(2)
        self._loop_delay_spin.setSuffix(" 秒")
        self._loop_delay_spin.valueChanged.connect(self._on_task_property_changed)

        form.addRow("名称：", self._task_name_edit)
        form.addRow("描述：", self._task_desc_edit)
        form.addRow("循环次数：", self._loop_count_spin)
        form.addRow("循环间隔：", self._loop_delay_spin)
        layout.addLayout(form)

        # ---- 序列循环配置（整个任务序列执行完后自动重新开始）----
        seq_group = QGroupBox("序列循环（整体重复执行）")
        seq_layout = QVBoxLayout(seq_group)

        seq_form = QFormLayout()
        # 序列循环次数：0 表示无限循环
        self._seq_loop_count_spin = QSpinBox()
        self._seq_loop_count_spin.setRange(0, 999999)
        self._seq_loop_count_spin.setValue(1)
        self._seq_loop_count_spin.setSpecialValueText("无限循环")
        self._seq_loop_count_spin.setToolTip(
            "整个任务序列执行完一遍后自动重新开始。\n"
            "0 = 无限循环（直到手动停止）\n"
            "1 = 只执行一遍（默认，不循环）\n"
            "N = 执行 N 遍"
        )
        self._seq_loop_count_spin.valueChanged.connect(
            self._on_seq_loop_changed
        )

        # 序列循环间隔（秒）
        self._seq_loop_delay_spin = QDoubleSpinBox()
        self._seq_loop_delay_spin.setRange(0.0, 86400.0)
        self._seq_loop_delay_spin.setSingleStep(0.1)
        self._seq_loop_delay_spin.setDecimals(2)
        self._seq_loop_delay_spin.setSuffix(" 秒")
        self._seq_loop_delay_spin.setValue(1.0)
        self._seq_loop_delay_spin.setToolTip("每轮序列循环之间的等待时间（秒）")
        self._seq_loop_delay_spin.valueChanged.connect(
            self._on_seq_loop_changed
        )

        seq_form.addRow("循环次数：", self._seq_loop_count_spin)
        seq_form.addRow("循环间隔：", self._seq_loop_delay_spin)
        seq_layout.addLayout(seq_form)

        layout.addWidget(seq_group)

        return group

    def _build_event_group(self) -> QGroupBox:
        """构建"事件列表"分组：事件列表 + 操作按钮行。"""
        group = QGroupBox("事件列表")
        layout = QVBoxLayout(group)

        # 事件列表
        self._event_list = QListWidget()
        self._event_list.currentItemChanged.connect(self._on_event_selected)
        layout.addWidget(self._event_list, 1)

        # 操作按钮行
        btn_row = QHBoxLayout()
        add_btn = QPushButton("添加事件")
        edit_btn = QPushButton("编辑事件")
        del_btn = QPushButton("删除事件")
        up_btn = QPushButton("上移")
        down_btn = QPushButton("下移")
        copy_btn = QPushButton("复制选中事件")
        paste_btn = QPushButton("粘贴事件")
        add_btn.clicked.connect(self._on_add_event)
        edit_btn.clicked.connect(self._on_edit_event)
        del_btn.clicked.connect(self._on_delete_event)
        up_btn.clicked.connect(self._on_move_up)
        down_btn.clicked.connect(self._on_move_down)
        copy_btn.clicked.connect(self._on_copy_event)
        paste_btn.clicked.connect(self._on_paste_event)
        for b in (add_btn, edit_btn, del_btn, up_btn, down_btn,
                  copy_btn, paste_btn):
            btn_row.addWidget(b)
        layout.addLayout(btn_row)

        return group

    # ------------------------------------------------------------------
    # 右侧面板
    # ------------------------------------------------------------------
    def _build_right_panel(self) -> QGroupBox:
        """构建"事件详情"分组：当前为只读预览，详细编辑在 Task 12 实现。"""
        group = QGroupBox("事件详情")
        layout = QVBoxLayout(group)

        # 占位提示
        tip = QLabel("事件编辑器将在 Task 12 中实现\n当前为只读预览")
        tip.setAlignment(Qt.AlignCenter)
        tip.setStyleSheet("color: #888; font-weight: bold;")
        layout.addWidget(tip)

        # 事件基本信息表单（只读）
        form = QFormLayout()
        self._info_type_label = QLabel("-")
        self._info_name_label = QLabel("-")
        self._info_enabled_label = QLabel("-")
        self._info_pre_delay_label = QLabel("-")
        self._info_post_delay_label = QLabel("-")
        self._info_on_error_label = QLabel("-")
        form.addRow("事件类型：", self._info_type_label)
        form.addRow("事件名称：", self._info_name_label)
        form.addRow("是否启用：", self._info_enabled_label)
        form.addRow("执行前延迟：", self._info_pre_delay_label)
        form.addRow("执行后延迟：", self._info_post_delay_label)
        form.addRow("错误处理：", self._info_on_error_label)
        layout.addLayout(form)

        # 参数 JSON 预览（只读）
        layout.addWidget(QLabel("参数 JSON 预览："))
        self._params_preview = QTextEdit()
        self._params_preview.setReadOnly(True)
        self._params_preview.setMinimumHeight(120)
        layout.addWidget(self._params_preview, 1)

        return group

    # ==================================================================
    # 对外公开方法
    # ==================================================================
    def set_task_sequence(self, task_sequence: TaskSequence):
        """
        设置要编辑的任务序列。

        :param task_sequence: TaskSequence 实例，可为 None（表示清空编辑器）
        """
        self._task_sequence = task_sequence
        self._current_task = None
        self._refresh_task_combo()
        # _refresh_task_combo 会触发 _on_task_changed 进而刷新事件列表与详情
        # 这里再显式刷新一次详情，保证无任务时右侧为空
        self._refresh_event_list()
        self._refresh_event_detail(None)
        # 同步序列级循环配置到 UI（从已加载的 TaskSequence 回填）
        self._sync_seq_loop_form(task_sequence)
        if task_sequence is not None:
            logger.debug(
                f"TaskEditor 已绑定任务序列: name={task_sequence.name!r}, "
                f"tasks={len(task_sequence.tasks)}"
            )

    def get_task_sequence(self) -> TaskSequence:
        """
        获取当前编辑的任务序列。

        :return: 当前绑定的 TaskSequence 实例（未绑定时返回 None）
        """
        return self._task_sequence

    # ==================================================================
    # 任务相关槽函数
    # ==================================================================
    def _on_task_changed(self, index: int):
        """
        任务下拉框切换：更新当前任务，刷新事件列表与任务属性表单。

        :param index: 下拉框新选中的下标
        """
        if self._syncing:
            return
        if self._task_sequence is None or index < 0:
            self._current_task = None
            self._refresh_event_list()
            self._refresh_event_detail(None)
            self._sync_task_form(None)
            return

        # 通过下标取任务（与下拉框数据顺序一致）
        if index < len(self._task_sequence.tasks):
            self._current_task = self._task_sequence.tasks[index]
        else:
            self._current_task = None

        self._sync_task_form(self._current_task)
        self._refresh_event_list()
        self._refresh_event_detail(None)

    def _on_new_task(self):
        """新建任务：创建空 Task 加入序列并选中。"""
        if self._task_sequence is None:
            QMessageBox.warning(self, "提示", "请先新建或打开一个任务序列。")
            return

        task = Task(name=f"任务 {len(self._task_sequence.tasks) + 1}")
        self._task_sequence.add_task(task)
        logger.info(f"已新建任务: name={task.name!r}, id={task.id[:8]}")
        self.task_sequence_changed.emit()

        # 刷新下拉框并选中新任务
        self._refresh_task_combo()
        # 新任务在末尾
        new_index = len(self._task_sequence.tasks) - 1
        if new_index >= 0:
            self._task_combo.setCurrentIndex(new_index)

    def _on_delete_task(self):
        """删除当前选中的任务。"""
        if self._task_sequence is None or self._current_task is None:
            QMessageBox.information(self, "提示", "没有可删除的任务。")
            return

        # 二次确认
        reply = QMessageBox.question(
            self, "确认删除",
            f'确定要删除任务 "{self._current_task.name}" 吗？\n'
            f"该任务包含 {len(self._current_task.events)} 个事件。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        task_id = self._current_task.id
        self._task_sequence.remove_task(task_id)
        logger.info(f"已删除任务: id={task_id[:8]}")
        self.task_sequence_changed.emit()

        self._refresh_task_combo()
        # 删除后下拉框会自动切换到相邻项，_on_task_changed 会处理后续刷新

    def _on_task_property_changed(self):
        """
        任务属性表单发生变化时回写到当前 Task 对象。
        通过 _syncing 标志避免程序化刷新触发的回环。
        """
        if self._syncing or self._current_task is None:
            return
        self._current_task.name = self._task_name_edit.text().strip()
        self._current_task.description = self._task_desc_edit.text()
        self._current_task.loop_count = self._loop_count_spin.value()
        self._current_task.loop_delay = self._loop_delay_spin.value()
        # 任务名称变化需同步到下拉框显示
        self._update_current_task_combo_text()
        self.task_sequence_changed.emit()

    def _on_seq_loop_changed(self):
        """
        序列循环配置发生变化时回写到当前 TaskSequence 对象。

        通过 _syncing 标志避免程序化刷新触发的回环。
        """
        if self._syncing or self._task_sequence is None:
            return
        self._task_sequence.loop_count = self._seq_loop_count_spin.value()
        self._task_sequence.loop_delay = self._seq_loop_delay_spin.value()
        logger.debug(
            f"序列循环配置已更新: loop_count="
            f"{self._task_sequence.loop_count}, "
            f"loop_delay={self._task_sequence.loop_delay}"
        )
        self.task_sequence_changed.emit()

    # ==================================================================
    # 事件相关槽函数
    # ==================================================================
    def _on_add_event(self):
        """添加事件：弹出事件类型选择对话框，创建 Event 加入当前任务。"""
        if self._task_sequence is None or self._current_task is None:
            QMessageBox.warning(self, "提示", "请先选择一个任务。")
            return

        dialog = EventTypeDialog(self)
        if dialog.exec_() != QDialog.Accepted:
            return

        event_type = dialog.selected_type()
        if event_type is None:
            return

        # 创建事件：默认名称取事件类型中文名 + 序号
        name = f"{_event_type_name(event_type)} {len(self._current_task.events) + 1}"
        event = Event(
            name=name,
            event_type=event_type,
            params=_default_params(event_type),
        )
        self._current_task.add_event(event)
        logger.info(
            f"已添加事件: name={event.name!r}, type={event.event_type}, "
            f"task={self._current_task.name!r}"
        )
        self.task_sequence_changed.emit()

        self._refresh_event_list()
        # 选中新添加的事件
        self._select_event_by_id(event.id)

    def _on_edit_event(self):
        """
        编辑选中事件：弹出 ``EventEditorDialog`` 进行可视化编辑。

        EventEditorDialog 在确认时已将修改写回 Event 对象，此处只需刷新
        列表与详情区。
        """
        event = self._get_selected_event()
        if event is None:
            QMessageBox.information(self, "提示", "请先选择要编辑的事件。")
            return

        # 获取当前事件之前的所有事件（用于承接参数选择）
        previous_events = []
        if self._current_task:
            for evt in self._current_task.events:
                if evt.id == event.id:
                    break
                previous_events.append(evt)

        from gui.event_editor import EventEditorDialog
        dialog = EventEditorDialog(event, self, previous_events)
        if dialog.exec_() == QDialog.Accepted:
            # EventEditorDialog.accept 已将修改写回 event 对象
            self.task_sequence_changed.emit()
            self._refresh_event_list()
            self._select_event_by_id(event.id)
            self._refresh_event_detail(event)

    def _on_delete_event(self):
        """删除选中事件。"""
        event = self._get_selected_event()
        if event is None:
            QMessageBox.information(self, "提示", "请先选择要删除的事件。")
            return

        reply = QMessageBox.question(
            self, "确认删除",
            f'确定要删除事件 "{event.name}" 吗？',
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        self._current_task.remove_event(event.id)
        logger.info(f"已删除事件: name={event.name!r}, id={event.id[:8]}")
        self.task_sequence_changed.emit()

        self._refresh_event_list()
        self._refresh_event_detail(None)

    def _on_move_up(self):
        """上移选中事件。"""
        event = self._get_selected_event()
        if event is None:
            QMessageBox.information(self, "提示", "请先选择要移动的事件。")
            return

        ok = self._current_task.move_event(event.id, "up")
        if ok:
            self.task_sequence_changed.emit()
            self._refresh_event_list()
            self._select_event_by_id(event.id)

    def _on_move_down(self):
        """下移选中事件。"""
        event = self._get_selected_event()
        if event is None:
            QMessageBox.information(self, "提示", "请先选择要移动的事件。")
            return

        ok = self._current_task.move_event(event.id, "down")
        if ok:
            self.task_sequence_changed.emit()
            self._refresh_event_list()
            self._select_event_by_id(event.id)

    def _on_copy_event(self):
        """复制选中事件到模块级剪贴板（可与子流程编辑器互通）。

        复用 gui/subflow_editor 的剪贴板（_copy_subflow_events），
        因此主任务编辑器复制的事件可以粘贴到条件分支的子流程里，
        反之亦然。
        """
        event = self._get_selected_event()
        if event is None:
            QMessageBox.information(self, "提示", "请先选择要复制的事件。")
            return
        from gui.subflow_editor import _copy_subflow_events
        n = _copy_subflow_events([event], src_desc=self.windowTitle() or "任务")
        logger.info(f"复制 {n} 个事件到剪贴板（主任务编辑器）")
        QMessageBox.information(
            self, "已复制",
            f"已复制 {n} 个事件到剪贴板。\n"
            f"可粘贴到本任务、别的任务或条件分支的子流程里。",
        )

    def _on_paste_event(self):
        """从模块级剪贴板粘贴事件到当前任务的事件列表。"""
        if self._current_task is None:
            QMessageBox.information(self, "提示", "请先选择目标任务。")
            return
        from gui.subflow_editor import (
            _has_subflow_clipboard,
            _paste_subflow_events,
        )
        if not _has_subflow_clipboard():
            QMessageBox.information(
                self, "提示",
                "剪贴板为空。请先点「复制选中事件」。",
            )
            return
        pasted = _paste_subflow_events()
        if not pasted:
            return

        # 插入位置：当前选中事件之后；未选中则追加到末尾
        current = self._get_selected_event()
        if current is not None and self._current_task is not None:
            insert_at = self._current_task.events.index(current) + 1
            for i, ev in enumerate(pasted):
                self._current_task.events.insert(insert_at + i, ev)
        else:
            for ev in pasted:
                self._current_task.add_event(ev)

        self.task_sequence_changed.emit()
        self._refresh_event_list()
        if pasted:
            self._select_event_by_id(pasted[0].id)
        logger.info(f"粘贴 {len(pasted)} 个事件到任务 {self._current_task.name!r}")

    def _on_event_selected(self, current: QListWidgetItem,
                           _previous: QListWidgetItem):
        """
        事件列表选中项变化：更新右侧详情区。

        :param current: 新选中的 QListWidgetItem
        :param _previous: 上一个选中的项（未使用）
        """
        if current is None:
            self._refresh_event_detail(None)
            return
        event_id = current.data(Qt.UserRole)
        event = self._current_task.get_event_by_id(event_id) \
            if self._current_task else None
        self._refresh_event_detail(event)

    # ==================================================================
    # 刷新方法
    # ==================================================================
    def _refresh_task_combo(self):
        """刷新任务下拉框，保持当前任务选中状态。"""
        self._syncing = True
        try:
            self._task_combo.blockSignals(True)
            self._task_combo.clear()

            if self._task_sequence is None:
                self._current_task = None
                self._sync_task_form(None)
                return

            # 记录当前任务 id，用于刷新后恢复选中
            prev_id = (self._current_task.id
                       if self._current_task is not None else None)

            for idx, task in enumerate(self._task_sequence.tasks):
                # 显示文本：序号 + 名称（事件数）
                label = f"{idx + 1}. {task.name} ({len(task.events)} 事件)"
                self._task_combo.addItem(label)

            # 恢复选中
            select_index = 0
            if prev_id is not None:
                for i, task in enumerate(self._task_sequence.tasks):
                    if task.id == prev_id:
                        select_index = i
                        break
            elif self._task_sequence.tasks:
                # 默认选第一个任务
                select_index = 0
                # 同步 current_task 指针
                self._current_task = self._task_sequence.tasks[0]

            if self._task_sequence.tasks:
                self._task_combo.setCurrentIndex(select_index)
                # 确保 _current_task 与选中下标一致
                self._current_task = self._task_sequence.tasks[select_index]
            else:
                self._current_task = None

            self._sync_task_form(self._current_task)
        finally:
            self._task_combo.blockSignals(False)
            self._syncing = False

        # 手动触发一次事件列表刷新（因为 blockSignals 跳过了 _on_task_changed）
        self._refresh_event_list()

    def _refresh_event_list(self):
        """刷新事件列表显示。"""
        self._event_list.blockSignals(True)
        try:
            self._event_list.clear()

            if self._current_task is None:
                return

            for ev in self._current_task.events:
                icon = _event_type_icon(ev.event_type)
                # 显示格式：[图标] 事件名称
                # 禁用事件加标记
                prefix = "" if ev.enabled else "[已禁用] "
                text = f"{icon}  {prefix}{ev.name}"
                item = QListWidgetItem(text)
                item.setData(Qt.UserRole, ev.id)
                # 禁用事件灰显
                if not ev.enabled:
                    item.setForeground(Qt.gray)
                self._event_list.addItem(item)

            # 默认选中第一个事件（若有）
            if self._event_list.count() > 0:
                self._event_list.setCurrentRow(0)
        finally:
            self._event_list.blockSignals(False)

        # 手动触发详情刷新
        current_item = self._event_list.currentItem()
        if current_item is not None:
            event_id = current_item.data(Qt.UserRole)
            event = self._current_task.get_event_by_id(event_id) \
                if self._current_task else None
            self._refresh_event_detail(event)
        else:
            self._refresh_event_detail(None)

    def _refresh_event_detail(self, event):
        """
        刷新右侧事件详情区。

        :param event: 当前选中的 Event 实例，None 表示清空详情
        """
        if event is None:
            self._info_type_label.setText("-")
            self._info_name_label.setText("-")
            self._info_enabled_label.setText("-")
            self._info_pre_delay_label.setText("-")
            self._info_post_delay_label.setText("-")
            self._info_on_error_label.setText("-")
            self._params_preview.clear()
            return

        self._info_type_label.setText(
            f"{_event_type_icon(event.event_type)}  "
            f"{_event_type_name(event.event_type)} ({event.event_type})"
        )
        self._info_name_label.setText(event.name or "(未命名)")
        self._info_enabled_label.setText("是" if event.enabled else "否")
        self._info_pre_delay_label.setText(f"{event.pre_delay:.3f} 秒")
        self._info_post_delay_label.setText(f"{event.post_delay:.3f} 秒")
        self._info_on_error_label.setText(event.on_error)

        # 参数 JSON 预览（格式化输出）
        try:
            pretty = json.dumps(event.params, ensure_ascii=False, indent=2)
        except (TypeError, ValueError) as e:
            pretty = f"<参数序列化失败: {e}>"
        self._params_preview.setPlainText(pretty)

    # ==================================================================
    # 辅助方法
    # ==================================================================
    def _sync_task_form(self, task):
        """
        将任务对象的属性同步到任务属性表单控件。

        :param task: Task 实例，None 表示清空表单
        """
        self._syncing = True
        try:
            if task is None:
                self._task_name_edit.clear()
                self._task_desc_edit.clear()
                self._loop_count_spin.setValue(1)
                self._loop_delay_spin.setValue(1.0)
                return
            self._task_name_edit.setText(task.name)
            self._task_desc_edit.setText(task.description)
            self._loop_count_spin.setValue(task.loop_count)
            self._loop_delay_spin.setValue(task.loop_delay)
        finally:
            self._syncing = False

    def _sync_seq_loop_form(self, task_sequence: TaskSequence):
        """
        将 TaskSequence 的序列循环配置同步到序列循环 UI 控件。

        :param task_sequence: TaskSequence 实例，None 表示恢复默认值
        """
        self._syncing = True
        try:
            if task_sequence is None:
                self._seq_loop_count_spin.setValue(1)
                self._seq_loop_delay_spin.setValue(1.0)
                return
            self._seq_loop_count_spin.setValue(task_sequence.loop_count)
            self._seq_loop_delay_spin.setValue(task_sequence.loop_delay)
        finally:
            self._syncing = False

    def _update_current_task_combo_text(self):
        """更新当前任务在下拉框中的显示文本（名称被编辑后调用）。"""
        if self._task_sequence is None or self._current_task is None:
            return
        idx = self._task_combo.currentIndex()
        if idx < 0:
            return
        label = f"{idx + 1}. {self._current_task.name} " \
                f"({len(self._current_task.events)} 事件)"
        # blockSignals 防止 setCurrentIndex 触发 _on_task_changed
        self._task_combo.blockSignals(True)
        self._task_combo.setItemText(idx, label)
        self._task_combo.blockSignals(False)

    def _get_selected_event(self) -> Event:
        """
        获取当前事件列表中选中的 Event 实例。

        :return: Event 实例，未选中或无当前任务时返回 None
        """
        if self._current_task is None:
            return None
        item = self._event_list.currentItem()
        if item is None:
            return None
        event_id = item.data(Qt.UserRole)
        return self._current_task.get_event_by_id(event_id)

    def _select_event_by_id(self, event_id):
        """
        按 ID 选中事件列表中的对应项。

        :param event_id: 事件 ID
        """
        if not event_id:
            return
        for i in range(self._event_list.count()):
            item = self._event_list.item(i)
            if item.data(Qt.UserRole) == event_id:
                self._event_list.setCurrentRow(i)
                return
