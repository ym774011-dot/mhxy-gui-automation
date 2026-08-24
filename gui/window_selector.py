# -*- coding: utf-8 -*-
"""
选择游戏窗口对话框（列表式绑定）。

与 yolo_auto_train/gui.py 的 select_game_window 行为对齐：
    - 列出所有游戏窗口（按 Galaxy2DEngine 类名 / 标题关键字过滤，
      支持多开器子窗口，含隐藏窗口并标记 visible）
    - 五列：PID / 角色名 / 状态 / 窗口标题 / 句柄
    - 锁定选中窗口（委托 window_manager.bind(pid=...)）
    - 解除绑定（委托 window_manager.unbind()）
    - 绑定持久化到 config（window.pid），下次启动自动恢复

用法::

    from gui.window_selector import WindowSelectorDialog
    dlg = WindowSelectorDialog(parent=self)
    dlg.exec_()
    # 绑定完成后调用外部 _update_window_status() 刷新状态标签
"""
from __future__ import annotations

import re
from typing import List, Tuple

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from core.window_manager import window_manager
from utils.logger import logger


def extract_role_name(title: str) -> str:
    """
    从游戏窗口标题提取角色名。

    标题格式: 鲜衣怒马 - 怀旧江南版 - (鲜衣怒马 - 然学[701529]) - 2026年...
    提取括号内的角色名部分；无括号则取标题前 20 字符。

    :param title: 窗口标题
    :return: 角色名（未知时返回 "(未知)"）
    """
    if not title:
        return "(未知)"
    m = re.search(r"\(([^)]+)\)", title)
    if m:
        inner = m.group(1)
        # "鲜衣怒马 - 然学[701529]" → "然学"
        parts = inner.split(" - ")
        if len(parts) >= 2:
            last = parts[-1]
            # 去掉 [701529] 这种 ID
            return re.sub(r"\[\d+\]", "", last).strip()
    return title[:20]


class WindowSelectorDialog(QDialog):
    """游戏窗口列表选择对话框。"""

    # 列顺序
    COLUMNS = ["PID", "角色名", "状态", "窗口标题", "句柄"]
    COL_WIDTHS = [70, 110, 60, 340, 90]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("选择游戏窗口")
        self.setMinimumSize(760, 440)
        self._build_ui()

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------
    def _build_ui(self):
        layout = QVBoxLayout(self)

        # 提示文案
        self.tip_label = QLabel()
        self.tip_label.setWordWrap(True)
        layout.addWidget(self.tip_label)

        # 表格
        self.table = QTableWidget(0, len(self.COLUMNS), self)
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(True)
        for i, w in enumerate(self.COL_WIDTHS):
            self.table.setColumnWidth(i, w)
        layout.addWidget(self.table, stretch=1)

        # 当前绑定状态
        self.status_label = QLabel()
        self.status_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(self.status_label)

        # 按钮行
        btn_row = QHBoxLayout()
        self.lock_btn = QPushButton("锁定选中窗口")
        self.lock_btn.setStyleSheet(
            "background: #2d9d4e; color: white; padding: 6px 18px; "
            "border-radius: 4px; font-weight: bold;"
        )
        self.lock_btn.clicked.connect(self._on_lock)

        self.unlock_btn = QPushButton("解除绑定")
        self.unlock_btn.setStyleSheet(
            "background: #e74c3c; color: white; padding: 6px 14px; "
            "border-radius: 4px;"
        )
        self.unlock_btn.clicked.connect(self._on_unlock)

        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.close)

        btn_row.addWidget(self.lock_btn)
        btn_row.addWidget(self.unlock_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        self._load_windows()
        self._update_status_label()

    # ------------------------------------------------------------------
    # 数据
    # ------------------------------------------------------------------
    def _load_windows(self):
        """枚举游戏窗口并填充表格。

        ★2026-08-25 多组：按当前组配置的 window.roles 过滤窗口——
        组1 GUI 只显示组1 角色（然学等），组2 GUI 只显示组2 角色（支纵等），
        防止多开时两组号绑定串组。组配置未设 roles 时显示全部（兼容旧行为）。
        """
        # 组角色过滤（MHXY_GROUP 环境变量 → config/group<N>/settings.json）
        import os as _os, json
        self._group_roles = []
        self._group_id = 1
        try:
            self._group_id = int(_os.environ.get("MHXY_GROUP", "1") or "1")
        except ValueError:
            self._group_id = 1
        try:
            _cfg_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "config", f"group{self._group_id}", "settings.json")
            if os.path.exists(_cfg_path):
                with open(_cfg_path, encoding="utf-8") as f:
                    _cfg = json.load(f)
                self._group_roles = list((_cfg.get("window") or {}).get("roles") or [])
        except Exception:
            pass

        windows: List[Tuple[int, str, int, bool]] = []
        try:
            windows = window_manager.list_game_windows()
        except Exception as e:
            logger.error(f"list_game_windows 失败: {e}")

        # 按组角色过滤
        if self._group_roles:
            _before = len(windows)
            windows = [w for w in windows
                       if extract_role_name(w[1]) in self._group_roles]
            _filtered = _before - len(windows)
        else:
            _filtered = 0

        self._windows = windows
        self.table.setRowCount(len(windows))
        current_pid = window_manager.pid

        for row, (hwnd, title, pid, visible) in enumerate(windows):
            role = extract_role_name(title)
            status = "可见" if visible else "隐藏"
            values = [str(pid), role, status, title, f"0x{hwnd:X}"]
            for col, v in enumerate(values):
                item = QTableWidgetItem(v)
                if col == 0:  # PID 居中
                    item.setTextAlignment(Qt.AlignCenter)
                if pid == current_pid and current_pid:
                    # 高亮当前已绑定行
                    item.setBackground(Qt.yellow)
                self.table.setItem(row, col, item)

        # 提示文案（★多组：显示组号 + 角色过滤信息）
        _tip = f"组{self._group_id}：找到 {len(windows)} 个游戏窗口"
        if self._group_roles:
            _tip += f"（已按本组角色 {'/'.join(self._group_roles)} 过滤，排除 {_filtered} 个其他组窗口）"
        else:
            _tip += "（未配置组角色，显示全部）"
        _tip += "，选择要锁定的窗口（多开时用 PID 区分）："
        self.tip_label.setText(_tip)

        if not windows:
            logger.warning(f"window_selector: 组{self._group_id} 未找到匹配角色窗口")

    def _update_status_label(self):
        """刷新底部绑定状态标签。"""
        if window_manager.bound:
            self.status_label.setText(
                f"当前绑定: PID={window_manager.pid} | {window_manager.window_title}"
            )
            self.status_label.setStyleSheet(
                "color: #2d9d4e; font-weight: bold;"
            )
        else:
            self.status_label.setText("当前未绑定（自动匹配第一个窗口）")
            self.status_label.setStyleSheet(
                "color: #888; font-weight: bold;"
            )

    # ------------------------------------------------------------------
    # 按钮回调
    # ------------------------------------------------------------------
    def _on_lock(self):
        """锁定选中的窗口。

        点击后不弹"绑定成功"提示框（避免挡住用户、强制多一次点击），
        直接刷新状态条 + 自动关闭对话框。底部状态条已显示绑定信息，
        且 window_manager.bind() 已持久化到 config，下次启动自动恢复。
        """
        row = self.table.currentRow()
        if row < 0 or row >= len(self._windows):
            QMessageBox.warning(self, "提示", "请先选择一个窗口")
            return

        hwnd, title, pid, visible = self._windows[row]
        ok = window_manager.bind(title=None, pid=pid)
        if not ok:
            QMessageBox.critical(
                self, "绑定失败",
                f"PID={pid} 进程不存在或已退出，请重新选择。",
            )
            return

        logger.info(
            f"window_selector 锁定成功: PID={pid}, title={title!r}"
        )
        self._update_status_label()
        self._rehighlight(current_pid=pid)
        # 自动关闭选择对话框（绑定已持久化，无需用户手动确认）
        self.accept()

    def _on_unlock(self):
        """解除绑定。"""
        window_manager.unbind()
        logger.info("window_selector 已解除绑定")
        # 同样不弹提示框，直接刷新状态条
        self._update_status_label()
        self._rehighlight(current_pid=0)

    def _rehighlight(self, current_pid: int):
        """绑定状态变化后重新高亮当前行。"""
        for row, (hwnd, title, pid, visible) in enumerate(self._windows):
            for col in range(len(self.COLUMNS)):
                item = self.table.item(row, col)
                if item is None:
                    continue
                if current_pid and pid == current_pid:
                    item.setBackground(Qt.yellow)
                else:
                    item.setBackground(Qt.white)
