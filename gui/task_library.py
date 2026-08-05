# -*- coding: utf-8 -*-
"""
任务库管理面板（Task 13）。

实现 ``TaskLibraryPanel(QWidget)``，作为主窗口"任务库"标签页的内容面板。
提供模块的导入、启用 / 禁用、重载、移除以及函数查看等功能。

布局（水平分割）::
    +-----------------------------+---------------------------+
    |  [导入脚本] [刷新] [保存配置]  |  函数列表 (QGroupBox)       |
    |                             |                           |
    |  +------------------------+ |  +-----------------------+ |
    |  | 模块列表 (QListWidget)  | |  | 函数 QListWidget      | |
    |  | [内置] xxx (已启用)     | |  | func_name(args)       | |
    |  | [自定义] xxx (已禁用)    | |  | ...                   | |
    |  | [地图函数] xxx (已启用)  | |  +-----------------------+ |
    |  +------------------------+ |  | 函数详情 (QTextEdit)   | |
    |  [启用] [禁用] [重新加载] [移除]|  | docstring / 签名      | |
    |                             |  +-----------------------+ |
    +-----------------------------+---------------------------+

核心数据来源：``core.task_library_manager.task_library`` 单例。
"""
import os
import inspect

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QBrush, QColor
from PyQt5.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.task_library_manager import task_library
from utils.logger import logger


# 分类显示名与颜色映射：
#   内置 = 蓝色、自定义 = 绿色、地图函数 = 橙色、其他 = 灰色
_CATEGORY_DISPLAY = {
    "built_in": ("内置", "#2980b9"),
    "custom": ("自定义", "#27ae60"),
    "map": ("地图函数", "#e67e22"),
}


class TaskLibraryPanel(QWidget):
    """
    任务库管理面板。

    通过 ``task_library`` 单例管理模块：导入 / 启用 / 禁用 / 重载 / 移除，
    并在右侧展示选中模块的可调用函数列表与详情。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        # 加载标志：在程序化填充列表时抑制 itemChanged 信号，避免回调递归
        self._loading = False
        # 当前选中模块名（用于避免重复刷新函数列表）
        self._current_module_name = None
        # 当前模块的函数信息缓存：[(函数名, 函数对象, 签名字符串), ...]
        self._current_functions = []

        self._init_ui()
        self._refresh_module_list()

    # ==================================================================
    # UI 初始化
    # ==================================================================
    def _init_ui(self):
        """构建面板 UI。"""
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(4, 4, 4, 4)

        # 水平分割器：左侧模块区 | 右侧函数区
        splitter = QSplitter(Qt.Horizontal, self)

        # ---------------- 左侧：模块区 ----------------
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)

        # 顶部按钮行：导入脚本 / 刷新 / 保存配置
        top_btn_layout = QHBoxLayout()
        self.import_btn = QPushButton("导入脚本")
        self.refresh_btn = QPushButton("刷新")
        self.save_btn = QPushButton("保存配置")
        self.import_btn.setStatusTip("从文件系统选择 .py 脚本导入到任务库")
        self.refresh_btn.setStatusTip("重新加载所有模块")
        self.save_btn.setStatusTip("将当前模块列表保存到 settings.json")
        top_btn_layout.addWidget(self.import_btn)
        top_btn_layout.addWidget(self.refresh_btn)
        top_btn_layout.addWidget(self.save_btn)
        top_btn_layout.addStretch()
        left_layout.addLayout(top_btn_layout)

        # 模块列表
        self.module_list = QListWidget()
        self.module_list.setStatusTip("任务库模块列表，复选框控制启用 / 禁用")
        left_layout.addWidget(self.module_list, 1)

        # 底部操作按钮行：启用 / 禁用 / 重新加载 / 移除
        bottom_btn_layout = QHBoxLayout()
        self.enable_btn = QPushButton("启用")
        self.disable_btn = QPushButton("禁用")
        self.reload_btn = QPushButton("重新加载")
        self.remove_btn = QPushButton("移除")
        self.enable_btn.setStatusTip("启用当前选中的模块")
        self.disable_btn.setStatusTip("禁用当前选中的模块")
        self.reload_btn.setStatusTip("重新加载当前选中的模块")
        self.remove_btn.setStatusTip("从任务库移除当前选中的模块（不删除原文件）")
        bottom_btn_layout.addWidget(self.enable_btn)
        bottom_btn_layout.addWidget(self.disable_btn)
        bottom_btn_layout.addWidget(self.reload_btn)
        bottom_btn_layout.addWidget(self.remove_btn)
        left_layout.addLayout(bottom_btn_layout)

        # ---------------- 右侧：函数区 ----------------
        right_group = QGroupBox("函数列表")
        right_layout = QVBoxLayout(right_group)

        # 函数列表
        self.function_list = QListWidget()
        self.function_list.setStatusTip("选中模块的可调用函数")
        right_layout.addWidget(self.function_list, 1)

        # 函数详情标题
        detail_title = QLabel("函数详情：")
        right_layout.addWidget(detail_title)

        # 函数详细信息（docstring / 签名）
        self.function_detail = QTextEdit()
        self.function_detail.setReadOnly(True)
        self.function_detail.setPlaceholderText("选择一个函数查看详情")
        right_layout.addWidget(self.function_detail, 1)

        # ---------------- 组装 ----------------
        splitter.addWidget(left_widget)
        splitter.addWidget(right_group)
        # 左右初始比例 3:2
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        main_layout.addWidget(splitter)

        # ---------------- 信号连接 ----------------
        self.import_btn.clicked.connect(self._on_import_script)
        self.refresh_btn.clicked.connect(self._on_refresh)
        self.save_btn.clicked.connect(self._on_save_config)

        self.enable_btn.clicked.connect(self._on_enable)
        self.disable_btn.clicked.connect(self._on_disable)
        self.reload_btn.clicked.connect(self._on_reload)
        self.remove_btn.clicked.connect(self._on_remove)

        self.module_list.itemSelectionChanged.connect(self._on_module_changed)
        self.module_list.itemChanged.connect(self._on_module_check_changed)
        self.function_list.itemSelectionChanged.connect(self._on_function_changed)

    # ==================================================================
    # 模块列表
    # ==================================================================
    def _refresh_module_list(self):
        """刷新模块列表，保留当前选中项。"""
        # 记录当前选中模块，刷新后尝试恢复
        previous_name = self._get_selected_module_name()

        self._loading = True
        self.module_list.blockSignals(True)
        try:
            self.module_list.clear()
            all_modules = task_library.get_all_modules()
            for name, info in all_modules.items():
                item = self._create_module_item(name, info)
                self.module_list.addItem(item)

            # 恢复选中：优先原模块名，否则选第一项
            target_item = None
            if previous_name:
                target_item = self._find_item_by_name(previous_name)
            if target_item is None and self.module_list.count() > 0:
                target_item = self.module_list.item(0)
            if target_item is not None:
                self.module_list.setCurrentItem(target_item)
        finally:
            self.module_list.blockSignals(False)
            self._loading = False

        # 手动触发函数列表刷新（因为信号被屏蔽了）
        selected_name = self._get_selected_module_name()
        if selected_name:
            self._refresh_function_list(selected_name)
        else:
            self._current_module_name = None
            self._current_functions = []
            self.function_list.clear()
            self.function_detail.clear()

    def _create_module_item(self, name, info):
        """
        创建模块列表项。

        :param name: 模块名
        :param info: 模块信息字典（含 path / enabled / category / functions）
        :return: QListWidgetItem
        """
        category = info.get("category", "custom")
        enabled = bool(info.get("enabled", True))
        cat_display, cat_color = _CATEGORY_DISPLAY.get(
            category, (category, "#7f8c8d")
        )
        status = "已启用" if enabled else "已禁用"

        item = QListWidgetItem()
        # 显示文本格式：[分类] 模块名 (已启用/已禁用)
        item.setText(f"[{cat_display}] {name} ({status})")
        # 模块名存入 UserRole，便于查找
        item.setData(Qt.UserRole, name)
        # 复选框控制启用 / 禁用
        item.setCheckState(Qt.Checked if enabled else Qt.Unchecked)
        # 按分类着色（分类标签着色要求）
        item.setForeground(QBrush(QColor(cat_color)))
        # 工具提示显示完整路径与函数数量
        path = info.get("path", "")
        func_count = len(info.get("functions", []))
        item.setToolTip(
            f"模块名：{name}\n"
            f"分类：{cat_display}\n"
            f"状态：{status}\n"
            f"路径：{path}\n"
            f"函数数：{func_count}"
        )
        return item

    def _find_item_by_name(self, name):
        """根据模块名查找列表项，找不到返回 None。"""
        for i in range(self.module_list.count()):
            item = self.module_list.item(i)
            if item.data(Qt.UserRole) == name:
                return item
        return None

    def _get_selected_module_name(self):
        """返回当前选中的模块名，无选中返回 None。"""
        items = self.module_list.selectedItems()
        if not items:
            return None
        return items[0].data(Qt.UserRole)

    # ==================================================================
    # 模块选择 / 复选框回调
    # ==================================================================
    def _on_module_changed(self):
        """模块选择改变：更新右侧函数列表。"""
        if self._loading:
            return
        name = self._get_selected_module_name()
        if name is None:
            self._current_module_name = None
            self._current_functions = []
            self.function_list.clear()
            self.function_detail.clear()
            return
        # 仅在选中模块变化时刷新，避免重复
        if name != self._current_module_name:
            self._refresh_function_list(name)

    def _on_module_check_changed(self, item):
        """复选框状态改变：启用 / 禁用对应模块。"""
        if self._loading:
            return
        name = item.data(Qt.UserRole)
        if not name:
            return
        checked = item.checkState() == Qt.Checked
        if checked:
            task_library.enable_module(name)
        else:
            task_library.disable_module(name)
        # 同步该项显示文本中的状态
        self._update_item_status(item, name, checked)
        logger.info(f"模块 '{name}' 已{'启用' if checked else '禁用'}")

    def _update_item_status(self, item, name, enabled):
        """更新列表项文本中的启用 / 禁用状态（屏蔽信号避免回调）。"""
        info = task_library.get_module(name)
        if info is None:
            return
        category = info.get("category", "custom")
        cat_display, cat_color = _CATEGORY_DISPLAY.get(
            category, (category, "#7f8c8d")
        )
        status = "已启用" if enabled else "已禁用"
        self.module_list.blockSignals(True)
        try:
            item.setText(f"[{cat_display}] {name} ({status})")
            item.setForeground(QBrush(QColor(cat_color)))
        finally:
            self.module_list.blockSignals(False)

    # ==================================================================
    # 函数列表
    # ==================================================================
    def _refresh_function_list(self, module_name):
        """刷新右侧函数列表。"""
        self._current_module_name = module_name
        self._current_functions = []
        self.function_list.clear()
        self.function_detail.clear()

        functions = task_library.get_functions(module_name)
        self._current_functions = functions

        for fname, fobj, sig_str in functions:
            # 显示格式：函数名(参数签名)
            text = f"{fname}({sig_str})" if sig_str else fname
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, fname)
            self.function_list.addItem(item)

        if self.function_list.count() > 0:
            # 默认选中第一个函数，显示其详情
            self.function_list.setCurrentRow(0)
        else:
            self.function_detail.setPlainText("该模块没有可调用函数。")

    def _on_function_changed(self):
        """函数选择改变：显示详情。"""
        items = self.function_list.selectedItems()
        if not items:
            return
        fname = items[0].data(Qt.UserRole)
        # 从缓存中查找函数对象
        fobj = None
        for fn, fo, _ in self._current_functions:
            if fn == fname:
                fobj = fo
                break
        if fobj is None:
            return
        self._show_function_detail(fname, fobj)

    def _show_function_detail(self, fname, fobj):
        """显示函数详细信息（签名 + docstring）。"""
        lines = [f"函数名：{fname}"]
        try:
            sig = inspect.signature(fobj)
            lines.append(f"签名：{fname}{sig}")
        except (ValueError, TypeError):
            lines.append("签名：（无法获取）")
        lines.append("")

        doc = inspect.getdoc(fobj)
        if doc:
            lines.append("文档：")
            lines.append(doc)
        else:
            lines.append("文档：（无）")

        self.function_detail.setPlainText("\n".join(lines))

    # ==================================================================
    # 按钮回调
    # ==================================================================
    def _on_import_script(self):
        """导入外部 .py 脚本到任务库。"""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择要导入的脚本",
            "",
            "Python 脚本 (*.py);;所有文件 (*.*)",
        )
        if not path:
            return

        # 用文件名（不含扩展名）作为模块名
        name = os.path.splitext(os.path.basename(path))[0]

        # 同名模块已存在时提示覆盖
        if task_library.get_module(name) is not None:
            reply = QMessageBox.question(
                self, "确认覆盖",
                f"模块 '{name}' 已存在，是否重新导入（覆盖）？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return

        ok = task_library.import_module(name, path, category="custom")
        if ok:
            logger.info(f"已导入脚本：{name} ({path})")
            QMessageBox.information(self, "导入成功", f"模块 '{name}' 导入成功。")
            self._refresh_module_list()
            # 选中新导入的模块
            self._select_module(name)
        else:
            logger.error(f"导入脚本失败：{path}")
            QMessageBox.critical(
                self, "导入失败",
                f"模块 '{name}' 导入失败，请查看日志。\n"
                f"常见原因：脚本存在语法错误或缺少依赖。",
            )

    def _on_enable(self):
        """启用当前选中模块。"""
        name = self._get_selected_module_name()
        if not name:
            QMessageBox.information(self, "提示", "请先选择一个模块。")
            return
        if task_library.enable_module(name):
            item = self.module_list.currentItem()
            if item:
                # 屏蔽信号，避免 itemChanged 回调
                self.module_list.blockSignals(True)
                try:
                    item.setCheckState(Qt.Checked)
                finally:
                    self.module_list.blockSignals(False)
                self._update_item_status(item, name, True)
            logger.info(f"已启用模块：{name}")
        else:
            QMessageBox.warning(self, "启用失败", f"模块 '{name}' 不存在。")

    def _on_disable(self):
        """禁用当前选中模块。"""
        name = self._get_selected_module_name()
        if not name:
            QMessageBox.information(self, "提示", "请先选择一个模块。")
            return
        if task_library.disable_module(name):
            item = self.module_list.currentItem()
            if item:
                self.module_list.blockSignals(True)
                try:
                    item.setCheckState(Qt.Unchecked)
                finally:
                    self.module_list.blockSignals(False)
                self._update_item_status(item, name, False)
            logger.info(f"已禁用模块：{name}")
        else:
            QMessageBox.warning(self, "禁用失败", f"模块 '{name}' 不存在。")

    def _on_reload(self):
        """重新加载当前选中模块。"""
        name = self._get_selected_module_name()
        if not name:
            QMessageBox.information(self, "提示", "请先选择一个模块。")
            return
        if task_library.reload_module(name):
            logger.info(f"已重新加载模块：{name}")
            QMessageBox.information(
                self, "重新加载成功", f"模块 '{name}' 已重新加载。"
            )
            self._refresh_module_list()
            self._select_module(name)
        else:
            QMessageBox.warning(
                self, "重新加载失败",
                f"模块 '{name}' 重载失败，请查看日志。",
            )

    def _on_remove(self):
        """移除当前选中模块。"""
        name = self._get_selected_module_name()
        if not name:
            QMessageBox.information(self, "提示", "请先选择一个模块。")
            return
        reply = QMessageBox.question(
            self, "确认移除",
            f"确定要从任务库移除模块 '{name}' 吗？\n（不会删除原始文件）",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        if task_library.remove_module(name):
            logger.info(f"已移除模块：{name}")
            self._refresh_module_list()
        else:
            QMessageBox.warning(self, "移除失败", f"模块 '{name}' 不存在。")

    def _on_refresh(self):
        """刷新所有模块（逐个重载）。"""
        logger.info("用户请求刷新任务库（重载所有模块）")
        all_modules = task_library.get_all_modules()
        success_count = 0
        for name in list(all_modules.keys()):
            if task_library.reload_module(name):
                success_count += 1
        self._refresh_module_list()
        QMessageBox.information(
            self, "刷新完成",
            f"已刷新任务库，成功 {success_count}/{len(all_modules)} 个模块，"
            f"当前共 {self.module_list.count()} 个模块。",
        )

    def _on_save_config(self):
        """保存当前模块列表到 settings.json。"""
        if task_library.save_to_config():
            logger.info("任务库配置已保存")
            QMessageBox.information(
                self, "保存成功", "任务库配置已保存到 settings.json。"
            )
        else:
            QMessageBox.warning(
                self, "保存失败", "任务库配置保存失败，请查看日志。"
            )

    # ==================================================================
    # 内部辅助
    # ==================================================================
    def _select_module(self, name):
        """选中指定名称的模块。"""
        item = self._find_item_by_name(name)
        if item is not None:
            self.module_list.setCurrentItem(item)
