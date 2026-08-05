# -*- coding: utf-8 -*-
"""
MHXY GUI 自动化脚本平台 - 主控制面板（Task 10）。

本模块实现 ``StatusPanel(QWidget)``，作为主窗口的第一个标签页（"主控制面板"），
实时显示任务执行状态、进度、事件信息和执行日志。

布局（垂直）：
    1. 顶部状态区（QGroupBox "执行状态"）：
       - 当前任务名称标签
       - 执行状态标签（就绪 / 运行中 / 已暂停 / 已停止 / 已完成）
       - 进度条（QProgressBar）
       - 当前事件标签
    2. 中间日志区（QGroupBox "执行日志"）：
       - 只读 QTextEdit，自动滚动到底部
       - 日志按级别彩色显示：DEBUG=灰、INFO=黑、WARNING=橙、ERROR=红
       - 每条日志格式：[时间] [级别] 消息
    3. 底部按钮区（QHBoxLayout）：
       - 清空日志
       - 保存日志（保存到文件）

信号连接（在 MainWindow 中完成）：
    - task_engine.progress_signal  -> update_progress
    - MainWindow.log_forward       -> append_log
    - task_engine.status_signal    -> update_status
"""
import html
import json
import os
import time
from datetime import datetime

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QTextCursor
from PyQt5.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from utils.logger import logger


class StatusPanel(QWidget):
    """
    主控制面板：实时显示执行状态、进度与日志。

    通过 ``update_status`` / ``update_progress`` / ``append_log`` 等公开方法更新界面，
    这些方法可直接作为 PyQt5 信号的槽函数。
    """

    # ==================================================================
    # 样式映射表
    # ==================================================================
    # 日志级别 -> HTML 颜色
    _LEVEL_COLORS = {
        "DEBUG": "#888888",      # 灰色
        "INFO": "#000000",       # 黑色
        "WARNING": "#FF8C00",    # 橙色
        "ERROR": "#FF0000",      # 红色
        "CRITICAL": "#B22222",   # 深红
    }

    # 状态文本 -> 颜色
    _STATUS_COLORS = {
        "就绪": "#888888",
        "运行中": "#27AE60",
        "已暂停": "#FF8C00",
        "已停止": "#C0392B",
        "已完成": "#2980B9",
        "正在停止": "#FF8C00",
    }

    # ==================================================================
    # 初始化
    # ==================================================================
    def __init__(self, parent=None):
        super().__init__(parent)
        # 当前任务名称缓存
        self._current_task_name = ""

        # 当前任务详情缓存（可选，由 TaskEngine / 任务库函数通过 set_quest_detail 填充）
        # 未填充时为 None，导出 JSON 时如实反映，绝不臆造数据。
        self._quest_map = None      # 目标地图，如 "东海湾"
        self._quest_coord = None    # 目标坐标，如 (104, 82)
        self._quest_npc = None      # 目标 NPC，如 "江湖大盗"
        self._quest_loops = None    # 循环次数，如 203
        self._progress_current = 0
        self._progress_total = 0

        # 构建 UI
        self._init_ui()

        # 初始状态显示
        self.update_status("就绪")
        # 启动欢迎日志（便于首次显示时验证日志区工作）
        self.append_log("INFO", "主控制面板已就绪，等待任务执行。")

    # ==================================================================
    # UI 构建
    # ==================================================================
    def _init_ui(self):
        """构建整体布局：状态区 + 日志区 + 按钮区。"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # 1. 顶部状态区
        layout.addWidget(self._create_status_group())

        # 2. 中间日志区（拉伸因子 1，占满剩余空间）
        layout.addWidget(self._create_log_group(), 1)

        # 3. 底部按钮区
        layout.addLayout(self._create_button_bar())

    # ------------------------------------------------------------------
    # 顶部状态区
    # ------------------------------------------------------------------
    def _create_status_group(self) -> QGroupBox:
        """创建"执行状态"分组：任务名 / 状态 / 进度条 / 当前事件。"""
        group = QGroupBox("执行状态", self)
        g_layout = QVBoxLayout(group)
        g_layout.setSpacing(6)

        # 当前任务名称行
        name_row = QHBoxLayout()
        name_label = QLabel("当前任务:")
        name_label.setMinimumWidth(72)
        name_row.addWidget(name_label)
        self.task_name_label = QLabel("（无）")
        self.task_name_label.setStyleSheet("font-weight: bold;")
        name_row.addWidget(self.task_name_label, 1)
        g_layout.addLayout(name_row)

        # 执行状态行
        status_row = QHBoxLayout()
        status_label = QLabel("执行状态:")
        status_label.setMinimumWidth(72)
        status_row.addWidget(status_label)
        self.status_label = QLabel("就绪")
        self.status_label.setStyleSheet("font-weight: bold; color: #888888;")
        status_row.addWidget(self.status_label, 1)
        g_layout.addLayout(status_row)

        # 进度条
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("未开始")
        g_layout.addWidget(self.progress_bar)

        # 当前事件行（事件名 + 进度数值文本）
        event_row = QHBoxLayout()
        event_label = QLabel("当前事件:")
        event_label.setMinimumWidth(72)
        event_row.addWidget(event_label)
        self.current_event_label = QLabel("（无）")
        self.current_event_label.setStyleSheet("color: #555;")
        event_row.addWidget(self.current_event_label, 1)
        # 右侧显示进度数值，如 "3 / 10"
        self.progress_text_label = QLabel("0 / 0")
        self.progress_text_label.setStyleSheet("color: #555;")
        event_row.addWidget(self.progress_text_label)
        g_layout.addLayout(event_row)

        return group

    # ------------------------------------------------------------------
    # 中间日志区
    # ------------------------------------------------------------------
    def _create_log_group(self) -> QGroupBox:
        """创建"执行日志"分组：只读 QTextEdit，等宽字体，自动滚动。"""
        group = QGroupBox("执行日志", self)
        g_layout = QVBoxLayout(group)
        g_layout.setSpacing(4)

        self.log_edit = QTextEdit(self)
        self.log_edit.setReadOnly(True)
        # 使用等宽字体，便于时间戳与级别对齐
        font = self.log_edit.font()
        font.setFamily("Consolas")
        self.log_edit.setFont(font)
        # 浅色背景，接近控制台风格
        self.log_edit.setStyleSheet("QTextEdit { background-color: #FAFAFA; }")
        g_layout.addWidget(self.log_edit)

        return group

    # ------------------------------------------------------------------
    # 底部按钮区
    # ------------------------------------------------------------------
    def _create_button_bar(self) -> QHBoxLayout:
        """创建底部按钮栏：清空日志 + 保存日志。"""
        bar = QHBoxLayout()
        bar.addStretch(1)  # 按钮靠右

        self.clear_log_button = QPushButton("清空日志", self)
        self.clear_log_button.setStatusTip("清空日志区内容")
        self.clear_log_button.clicked.connect(self.clear_log)
        bar.addWidget(self.clear_log_button)

        self.save_log_button = QPushButton("保存日志", self)
        self.save_log_button.setStatusTip("将日志保存到文件")
        self.save_log_button.clicked.connect(self.save_log)
        bar.addWidget(self.save_log_button)

        return bar

    # ==================================================================
    # 公开槽方法（供信号连接）
    # ==================================================================
    def update_status(self, status: str):
        """
        更新执行状态标签（槽函数，可连接 status_signal）。

        :param status: 状态文本，如 "就绪"/"运行中"/"已暂停"/"已停止"/"已完成"
        """
        text = status if status else "就绪"
        color = self._STATUS_COLORS.get(text, "#000000")
        self.status_label.setText(text)
        self.status_label.setStyleSheet(f"font-weight: bold; color: {color};")
        self.export_quest()

    def update_progress(self, current: int, total: int, event_name: str):
        """
        更新进度条与当前事件标签（槽函数，可连接 progress_signal）。

        :param current: 当前事件下标（从 0 开始）
        :param total: 总事件数
        :param event_name: 当前事件名称
        """
        # current 是下标（0-based），显示时按"第几个"换算为 current+1
        try:
            current = int(current)
            total = int(total)
        except (TypeError, ValueError):
            current, total = 0, 0

        if total > 0:
            cur = max(0, min(current + 1, total))
            percent = int(cur / total * 100)
            self.progress_bar.setValue(percent)
            self.progress_bar.setFormat(f"{percent}% ({cur}/{total})")
            self.progress_text_label.setText(f"{cur} / {total}")
        else:
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat("未开始")
            self.progress_text_label.setText("0 / 0")

        # 当前事件名
        self.current_event_label.setText(event_name if event_name else "（无）")

        # 缓存进度供导出使用
        self._progress_current = current
        self._progress_total = total
        self.export_quest()

    def set_task_name(self, name: str):
        """
        设置当前任务名称（供 MainWindow 在启动任务时调用）。

        :param name: 任务名称
        """
        self._current_task_name = name or ""
        self.task_name_label.setText(self._current_task_name or "（无）")
        self.export_quest()

    def set_quest_detail(self, map_name=None, coord=None, npc=None, loops=None, task=None):
        """
        填充游戏内任务详情（地图 / 坐标 / NPC / 循环次数 / 任务名）。

        该数据通常来自 TaskEngine 执行 function 事件（如 JHRW 接任务）后的返回结果，
        由 MainWindow 在收到 quest_detail_signal 时调用本方法。未填充的字段保持 None，
        导出时如实反映。

        :param map_name: 目标地图名，如 "东海湾"
        :param coord: 目标坐标元组，如 (104, 82)
        :param npc: 目标 NPC 名，如 "江湖大盗"
        :param loops: 当前循环次数，如 203
        :param task: 游戏内任务名，如 "初出江湖"（覆盖 PyQt 任务名，更贴近实际当前任务）
        """
        self._quest_map = map_name
        self._quest_coord = coord
        self._quest_npc = npc
        self._quest_loops = loops
        if task:
            # 用游戏内真实任务名覆盖 PyQt 任务名（若存在），同步更新标签
            self._current_task_name = str(task)
            self.task_name_label.setText(self._current_task_name)
        self.export_quest()

    def export_quest(self):
        """
        将当前任务快照导出为 JSON 文件（IPC 接口），供外部进程稳定读取，
        彻底避免「逆向内存 / 反 CE / ASLR」等痛点。

        输出路径：``<项目根>/data/current_quest.json``

        字段说明：
            - task    : 当前 PyQt 任务名（set_task_name 设置）
            - status  : 执行状态文本（就绪 / 运行中 / ...）
            - progress: {current, total}
            - map/coord/npc/loops : 游戏内任务详情，由 set_quest_detail 填充；未填充为 None
            - ts      : 导出时间戳（time.time()，秒）

        采用「临时文件 + os.replace」原子写入，读取方不会读到半截数据。
        """
        data = {
            "task": self._current_task_name or None,
            "status": self.status_label.text(),
            "progress": {
                "current": self._progress_current,
                "total": self._progress_total,
            },
            "map": self._quest_map,
            "coord": self._quest_coord,
            "npc": self._quest_npc,
            "loops": self._quest_loops,
            "ts": time.time(),
        }
        try:
            root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            out_dir = os.path.join(root, "data")
            os.makedirs(out_dir, exist_ok=True)
            out_path = os.path.join(out_dir, "current_quest.json")
            tmp_path = out_path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, out_path)
        except OSError as e:
            logger.error(f"导出当前任务失败: {e}")

    def append_log(self, level: str, message: str):
        """
        追加一条日志到日志区，带时间戳与级别颜色（槽函数，可连接 log_signal/log_forward）。

        日志格式：[时间] [级别] 消息

        :param level: 日志级别字符串（DEBUG/INFO/WARNING/ERROR/CRITICAL）
        :param message: 日志消息
        """
        timestamp = datetime.now().strftime("%H:%M:%S")
        level_upper = (level or "INFO").upper()
        color = self._LEVEL_COLORS.get(level_upper, "#000000")

        # HTML 转义，避免消息中的 < > & 破坏显示
        safe_level = html.escape(level_upper)
        safe_msg = html.escape(str(message))

        # 整行着色
        line = (
            f'<span style="color:{color};">'
            f'[{timestamp}] [{safe_level}] {safe_msg}'
            f'</span>'
        )
        self.log_edit.append(line)
        self._auto_scroll()

    def clear_log(self):
        """清空日志区。"""
        self.log_edit.clear()
        self.append_log("INFO", "日志已清空。")

    def save_log(self):
        """将当前日志区内容保存到用户选择的文件。"""
        default_name = (
            f"execution_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        )
        path, _ = QFileDialog.getSaveFileName(
            self,
            "保存日志",
            default_name,
            "日志文件 (*.log);;文本文件 (*.txt);;所有文件 (*.*)",
        )
        if not path:
            return

        try:
            # 使用 toPlainText 获取纯文本，避免 HTML 标签
            text = self.log_edit.toPlainText()
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            self.append_log("INFO", f"日志已保存到: {path}")
            logger.info(f"日志已保存到: {path}")
        except OSError as e:
            QMessageBox.critical(self, "保存失败", f"保存日志失败：\n{e}")
            logger.error(f"保存日志失败: {e}")

    # ==================================================================
    # 内部方法
    # ==================================================================
    def _auto_scroll(self):
        """将日志区滚动到最底部，显示最新日志。"""
        cursor = self.log_edit.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.log_edit.setTextCursor(cursor)
        self.log_edit.ensureCursorVisible()


# ----------------------------------------------------------------------
# 模块自测：直接运行本文件时弹出主控制面板，验证布局与彩色日志
# ----------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    from PyQt5.QtWidgets import QApplication

    app = QApplication(sys.argv)
    panel = StatusPanel()
    panel.resize(640, 480)
    panel.show()

    # 模拟各级别日志，验证彩色显示
    panel.append_log("DEBUG", "这是一条 DEBUG 日志")
    panel.append_log("INFO", "这是一条 INFO 日志")
    panel.append_log("WARNING", "这是一条 WARNING 日志")
    panel.append_log("ERROR", "这是一条 ERROR 日志")
    # 模拟进度
    panel.set_task_name("示例任务")
    panel.update_progress(2, 5, "示例事件-点击按钮")
    panel.update_status("运行中")

    sys.exit(app.exec_())
