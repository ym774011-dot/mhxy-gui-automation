# -*- coding: utf-8 -*-
"""
子流程编辑器对话框（从 event_editor 上帝类拆出，PR #8 收口）。

``SubFlowEditorDialog`` 用于编辑某个 switch case（或 default 动作）下的一组
事件序列（操作子流程）。它复用 ``EventTypeDialog`` 选择类型、``EventEditorDialog``
编辑单事件，列表的增删 / 排序逻辑与 ``TaskEditor`` 的事件列表一致。

为避免与 ``event_editor`` 形成循环导入，``EventEditorDialog`` 仅在使用处
（``_on_edit``）做惰性导入；``task_editor`` 的构件同样惰性导入。

子流程间复制/粘贴（2026-08-04）：
    跨多个条件分支的子流程复用同一组事件是常见需求（例如「3 个地图各自
    走同样 13 步操作」），手动重建太繁琐。本文件提供模块级剪贴板
    ``_SUBFLOW_CLIPBOARD``：
      - "复制选中事件"：把当前选中的一个或连续多个事件序列化为 dict，
        深拷贝存到剪贴板（与其他对话框共享）；
      - "粘贴事件"：从剪贴板反序列化为新 Event 列表，插入到当前子流程
        选中位置（未选中则追加到末尾）。
    不依赖系统剪贴板（避免跨进程 / EventType 序列化兼容问题）。
"""
import copy
from typing import Any, Dict, List, Optional

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QMessageBox,
)

from models.event import Event, EventType
from utils.logger import logger


# ------------------------------------------------------------------
# 子流程事件剪贴板（模块级，跨 SubFlowEditorDialog 共享）
# ------------------------------------------------------------------
# 用模块级 dict 列表（而非 Event 实例）以避免粘贴后修改原对象意外影响剪贴板。
# 任何 SubFlowEditorDialog 实例都可以写入 / 读取，用户切换条件分支时
# 仍可继续粘贴最近一次复制的事件序列。
_SUBFLOW_CLIPBOARD: List[Dict[str, Any]] = []
_SUBFLOW_CLIPBOARD_SRC: str = ""  # 来源子流程的简短描述（仅用于状态提示）


def _copy_subflow_events(
    events: List[Event], src_desc: str = ""
) -> int:
    """把一组事件深拷贝到模块级剪贴板。返回复制条数。"""
    _SUBFLOW_CLIPBOARD.clear()
    for ev in events:
        _SUBFLOW_CLIPBOARD.append(copy.deepcopy(ev.to_dict()))
    global _SUBFLOW_CLIPBOARD_SRC
    _SUBFLOW_CLIPBOARD_SRC = src_desc
    return len(_SUBFLOW_CLIPBOARD)


def _has_subflow_clipboard() -> bool:
    return len(_SUBFLOW_CLIPBOARD) > 0


def _paste_subflow_events() -> List[Event]:
    """从模块级剪贴板反序列化为 Event 列表（深拷贝）。"""
    return [Event.from_dict(copy.deepcopy(d)) for d in _SUBFLOW_CLIPBOARD]


def _subflow_clipboard_desc() -> str:
    return _SUBFLOW_CLIPBOARD_SRC


class SubFlowEditorDialog(QDialog):
    """
    子流程编辑器对话框。

    用于编辑某个 switch case（或 default 动作）下的一组事件序列（操作子流程）。
    复用 ``EventTypeDialog`` 选择类型、``EventEditorDialog`` 编辑单事件，
    列表的增删 / 排序逻辑与 ``TaskEditor`` 的事件列表一致。

    :param events: 要编辑的事件列表（原地修改）
    :param parent: 父窗口
    :param context_events: 父任务里在**该 condition 事件之前**的事件列表。
                          用于让子流程内的函数调用能"承接"父任务上游函数调用
                          （如 JHRW）的结果，而不仅限于子流程内前序。
    """

    def __init__(self, events: Optional[List[Event]], parent=None,
                 context_events: Optional[List[Event]] = None):
        super().__init__(parent)
        # 持有原引用，accept 时把编辑结果写回——实现"原地编辑 / 自动保存"语义。
        # 若原引用为 None（极少见）则创建独立空列表，仅保存在本对话框内。
        self._events_ref: List[Event] = events if events is not None else []
        self._events: List[Event] = list(self._events_ref)
        self._context_events: List[Event] = list(context_events) if context_events else []
        self.setWindowTitle("编辑子流程（操作序列）")
        self.setMinimumSize(460, 480)
        # 记录事件被点击/选中的顺序（用于多选复制时保持用户点击顺序）
        # 元素为 Event.id；点击时追加/移动到末尾
        self._click_order: List[str] = []
        self._init_ui()
        self._refresh_list()

    def accept(self):
        """用户点击 OK：把编辑后的事件列表写回原引用（自动保存）。"""
        self._events_ref.clear()
        self._events_ref.extend(self._events)
        super().accept()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        tip = QLabel(
            "该分支命中后要依次执行的操作。坐标可填 "
            "${target_coord.0} / ${target_location} 等动态字段（取自上游函数结果）。\n"
            "按住 Ctrl/Shift 可多选事件；复制时按点击顺序保存。"
        )
        tip.setWordWrap(True)
        tip.setStyleSheet("color: #888;")
        layout.addWidget(tip)

        self._list = QListWidget()
        # 多选：支持按住 Ctrl / Shift 连续选择多个事件
        # （复制选中事件时按"点击顺序"收集，见 _on_copy）
        self._list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._list.itemDoubleClicked.connect(self._on_edit)
        self._list.itemClicked.connect(self._record_click_order)
        layout.addWidget(self._list, 1)

        btn_row = QHBoxLayout()
        add_btn = QPushButton("添加事件")
        edit_btn = QPushButton("编辑事件")
        del_btn = QPushButton("删除事件")
        up_btn = QPushButton("上移")
        down_btn = QPushButton("下移")
        copy_btn = QPushButton("复制选中事件")
        paste_btn = QPushButton("粘贴事件")
        add_btn.clicked.connect(self._on_add)
        edit_btn.clicked.connect(self._on_edit)
        del_btn.clicked.connect(self._on_delete)
        up_btn.clicked.connect(self._on_up)
        down_btn.clicked.connect(self._on_down)
        copy_btn.clicked.connect(self._on_copy)
        paste_btn.clicked.connect(self._on_paste)
        for b in (add_btn, edit_btn, del_btn, up_btn, down_btn,
                  copy_btn, paste_btn):
            btn_row.addWidget(b)
        layout.addLayout(btn_row)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    # ---- 列表刷新 ----
    def _refresh_list(self):
        from gui.task_editor import _event_type_name
        # 保留仍存在的点击顺序 id（删除/重排后已移除的 id 自动丢弃）
        alive = {ev.id for ev in self._events}
        self._click_order = [eid for eid in self._click_order if eid in alive]
        self._list.blockSignals(True)
        try:
            self._list.clear()
            for idx, ev in enumerate(self._events):
                # 2026-08-05 修复：列表不显示 enabled 状态（之前 disabled 项和
                # enabled 项视觉一样），用户无法判断"哪个没启用"。现在
                # disabled 项加 [已禁用] 前缀 + 灰色文字。
                name = ev.name or "(未命名)"
                if not getattr(ev, "enabled", True):
                    label = f"{idx + 1}. {name}  [{_event_type_name(ev.event_type)}]  [已禁用]"
                else:
                    label = f"{idx + 1}. {name}  [{_event_type_name(ev.event_type)}]"
                item = QListWidgetItem(label)
                if not getattr(ev, "enabled", True):
                    item.setForeground(Qt.gray)
                item.setData(Qt.UserRole, ev.id)
                self._list.addItem(item)
        finally:
            self._list.blockSignals(False)

    def _selected_event(self) -> Optional[Event]:
        item = self._list.currentItem()
        if item is None:
            return None
        eid = item.data(Qt.UserRole)
        for ev in self._events:
            if ev.id == eid:
                return ev
        return None

    def _select_by_id(self, eid: str):
        for i in range(self._list.count()):
            if self._list.item(i).data(Qt.UserRole) == eid:
                self._list.setCurrentRow(i)
                break

    # ---- 增删改排序（懒加载 task_editor 构件，避免循环导入）----
    def _on_add(self):
        from gui.task_editor import (
            EventTypeDialog,
            _default_params,
            _event_type_name,
        )
        dlg = EventTypeDialog(self)
        if dlg.exec_() != QDialog.Accepted:
            return
        et = dlg.selected_type()
        if et is None:
            return
        ev = Event(
            name=f"{_event_type_name(et)} {len(self._events) + 1}",
            event_type=et,
            params=_default_params(et),
        )
        self._events.append(ev)
        self._refresh_list()
        self._select_by_id(ev.id)

    def _on_edit(self):
        ev = self._selected_event()
        if ev is None:
            QMessageBox.information(self, "提示", "请先选择一个事件。")
            return
        # 承接参数 = 父任务里在该 condition 事件之前的事件（context_events）
        #           + 子流程内该事件之前的兄弟事件。
        # 顺序很重要：父任务先跑（拿到 JHRW 结果），再进入子流程跑子流程事件。
        prev: List[Event] = list(self._context_events or [])
        for e in self._events:
            if e.id == ev.id:
                break
            prev.append(e)
        from gui.event_editor import EventEditorDialog
        dlg = EventEditorDialog(ev, self, prev)
        if dlg.exec_() == QDialog.Accepted:
            self._refresh_list()
            self._select_by_id(ev.id)

    def _on_delete(self):
        ev = self._selected_event()
        if ev is None:
            QMessageBox.information(self, "提示", "请先选择一个事件。")
            return
        if QMessageBox.question(
            self, "确认删除", f'确定删除事件 "{ev.name}" 吗？',
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        ) != QMessageBox.Yes:
            return
        self._events = [e for e in self._events if e.id != ev.id]
        self._refresh_list()

    def _on_up(self):
        ev = self._selected_event()
        if ev is None:
            return
        i = self._events.index(ev)
        if i > 0:
            self._events[i - 1], self._events[i] = self._events[i], self._events[i - 1]
            self._refresh_list()
            self._select_by_id(ev.id)

    def _on_down(self):
        ev = self._selected_event()
        if ev is None:
            return
        i = self._events.index(ev)
        if i < len(self._events) - 1:
            self._events[i + 1], self._events[i] = self._events[i], self._events[i + 1]
            self._refresh_list()
            self._select_by_id(ev.id)

    # ---- 跨子流程复制/粘贴 ----
    def _record_click_order(self, item: "QListWidgetItem"):
        """记录点击/选中顺序（用于多选复制保持用户点击顺序）。

        用户可能按 Ctrl 点选第 3、1、2 项（顺序随意），复制时应按
        『点击的先后顺序』而不是列表顺序还原。每次点击把对应 id
        移到 _click_order 末尾；已被选中的再点会取消选中，但 id 保留
        在顺序里（复制时只取仍处于选中状态的）。
        """
        eid = item.data(Qt.UserRole) if item else None
        if not eid:
            return
        if eid in self._click_order:
            self._click_order.remove(eid)
        self._click_order.append(eid)

    def _selected_events_in_click_order(self) -> Optional[List[Event]]:
        """按点击顺序返回当前选中的事件。

        实现：
          1. 收集当前所有选中项对应的 Event（isSelected 过滤出仍选中的）
          2. 按 _click_order 排序（未出现在点击记录里的选中项按列表顺序补在后面）
        若完全没选中，返回 None。
        """
        # 选中项 id → event 映射
        selected_ids = []
        for i in range(self._list.count()):
            it = self._list.item(i)
            if it.isSelected():
                selected_ids.append(it.data(Qt.UserRole))
        if not selected_ids:
            return None

        by_id = {ev.id: ev for ev in self._events}
        # 点击顺序优先
        ordered: List[Event] = []
        seen = set()
        for eid in self._click_order:
            if eid in selected_ids and eid not in seen:
                seen.add(eid)
                if eid in by_id:
                    ordered.append(by_id[eid])
        # 点击顺序里没有的选中项（如全选后未逐个点击），按列表顺序补上
        for eid in selected_ids:
            if eid not in seen and eid in by_id:
                seen.add(eid)
                ordered.append(by_id[eid])
        return ordered

    def _on_copy(self):
        """把当前选中的事件（可按住 Ctrl/Shift 多选）深拷贝到模块级剪贴板。

        复制顺序 = 点击顺序（支持 Ctrl 乱序点选后仍按点击先后粘贴）。
        """
        evs = self._selected_events_in_click_order()
        if not evs:
            QMessageBox.information(
                self, "提示",
                "请先选中要复制的事件（可按住 Ctrl/Shift 多选）。",
            )
            return
        n = _copy_subflow_events(
            evs,
            src_desc=self.windowTitle() or "子流程",
        )
        logger.info(f"复制 {n} 个事件到子流程剪贴板（点击顺序）")
        QMessageBox.information(
            self, "已复制",
            f"已复制 {n} 个事件到剪贴板（按点击顺序）。\n"
            f"切到别的条件分支后点「粘贴事件」即可插入。",
        )

    def _on_paste(self):
        """从模块级剪贴板反序列化，在当前选中位置之后插入。"""
        if not _has_subflow_clipboard():
            QMessageBox.information(
                self, "提示",
                "剪贴板为空。请先在别的子流程里点「复制选中事件」。",
            )
            return
        pasted = _paste_subflow_events()
        if not pasted:
            return

        # 插入位置：最后一次点击的选中事件之后（多选场景下 currentItem
        # 可能是选中区间首项，用 _click_order 最后一个仍选中的 id 更贴合
        # 「在最后点选的事件后面插入」的直觉）；未选中则追加到末尾。
        anchor = self._anchor_event_id()
        insert_at = None
        if anchor is not None:
            for i, e in enumerate(self._events):
                if e.id == anchor:
                    insert_at = i + 1
                    break
        if insert_at is not None:
            for i, ev in enumerate(pasted):
                self._events.insert(insert_at + i, ev)
        else:
            self._events.extend(pasted)

        self._refresh_list()
        # 选中刚粘贴的第一个事件
        if pasted:
            self._select_by_id(pasted[0].id)
            last_id = pasted[-1].id
            for i in range(self._list.count()):
                if self._list.item(i).data(Qt.UserRole) == last_id:
                    self._list.setCurrentRow(i)
                    break
        logger.info(
            f"粘贴 {len(pasted)} 个事件（来源: {_subflow_clipboard_desc()}）"
        )

    def _anchor_event_id(self) -> Optional[str]:
        """返回粘贴插入位置的锚点事件 id（最后一次点击的选中项）。

        点击顺序里仍处于选中状态、且在 _events 中存在的最后一个 id；
        没有则回退到 currentItem。
        """
        alive = {ev.id for ev in self._events}
        selected_ids = set()
        for i in range(self._list.count()):
            it = self._list.item(i)
            if it.isSelected():
                selected_ids.add(it.data(Qt.UserRole))
        for eid in reversed(self._click_order):
            if eid in selected_ids and eid in alive:
                return eid
        cur = self._selected_event()
        return cur.id if cur is not None else None
