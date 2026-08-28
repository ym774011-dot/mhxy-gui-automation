# -*- coding: utf-8 -*-
"""
MHXY GUI 自动化脚本平台 - 主窗口框架（Task 9）。

本模块实现 ``MainWindow(QMainWindow)``，作为整个应用的主框架，包含：
    - 菜单栏（文件 / 设置 / 帮助）
    - 工具栏（开始执行 / 暂停 / 停止 / 绑定窗口 / 窗口状态标签）
    - 中央区域（QTabWidget，4 个标签页，当前为占位面板）
    - 状态栏（运行状态显示）

核心逻辑：
    - 通过 ``task_engine`` 单例控制任务执行（start / pause / stop）
    - 通过 ``window_manager`` 单例绑定目标窗口
    - 通过 ``config`` 单例加载 / 保存配置
    - 通过 ``task_library`` 单例加载任务库
    - 连接 ``task_engine`` 的 4 个信号到槽函数，更新 UI 状态

后续 Task 10/11/13/14 将分别替换 4 个占位面板为真实功能面板，
通过 ``self.status_panel / self.task_editor / self.task_library_panel /
self.config_panel`` 引用访问。
"""
import os
import sys

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QAction,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QStatusBar,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from config.config import config
from core.task_engine import task_engine
from core.task_library_manager import task_library
from core.window_manager import window_manager
from gui.config_panel import ConfigPanel
from gui.status_panel import StatusPanel
from gui.task_editor import TaskEditor
from gui.task_library import TaskLibraryPanel
from gui.window_selector import WindowSelectorDialog
from models.task_sequence import TaskSequence
from utils.logger import logger


# ----------------------------------------------------------------------
# 占位面板
# ----------------------------------------------------------------------
class PlaceholderPanel(QWidget):
    """
    占位面板。

    在对应功能模块（StatusPanel / TaskEditor / TaskLibraryPanel / ConfigPanel）
    实现之前，作为标签页的占位内容显示提示信息。
    后续 Task 可直接通过 ``MainWindow`` 的 setter 方法替换为真实面板。
    """

    def __init__(self, panel_name: str, task_no: str, parent=None):
        """
        :param panel_name: 面板显示名称（如 "主控制面板"）
        :param task_no: 将实现该面板的任务编号（如 "Task 10"）
        :param parent: 父 widget
        """
        super().__init__(parent)
        self._panel_name = panel_name
        self._task_no = task_no

        layout = QVBoxLayout(self)
        # 居中显示提示文字
        label = QLabel(
            f"{panel_name}\n\n此面板将在 {task_no} 中实现\n（当前为占位面板）"
        )
        label.setAlignment(Qt.AlignCenter)
        # 让文字稍微显眼一些
        font = label.font()
        font.setPointSize(14)
        font.setBold(True)
        label.setFont(font)
        # 灰色字提示
        label.setStyleSheet("color: #888;")
        layout.addWidget(label)


# ----------------------------------------------------------------------
# 主窗口
# ----------------------------------------------------------------------
class MainWindow(QMainWindow):
    """
    应用主窗口。

    集成菜单栏、工具栏、标签页中央区域、状态栏，并连接 ``task_engine`` 信号
    实现任务执行控制。4 个标签页暂时使用占位面板，后续任务会替换为真实面板。
    """

    # ------------------------------------------------------------------
    # 信号定义（供外部控制器或后续面板连接）
    # ------------------------------------------------------------------
    # 工具栏控制信号
    start_clicked = pyqtSignal()
    pause_clicked = pyqtSignal()
    stop_clicked = pyqtSignal()

    # 文件菜单信号
    new_task = pyqtSignal()
    open_task = pyqtSignal(str)  # 参数：任务文件路径
    save_task = pyqtSignal()

    # 日志转发信号：将 task_engine.log_signal 转发给主控制面板的日志区
    # 参数：(级别字符串, 消息字符串)
    log_forward = pyqtSignal(str, str)

    # ------------------------------------------------------------------
    # 初始化
    # ------------------------------------------------------------------
    def __init__(self, parent=None):
        super().__init__(parent)

        # 各标签页对应的面板引用（初始为占位面板）
        # 后续 Task 10/11/13/14 会替换为真实面板
        self.status_panel: QWidget = None        # 主控制面板（Task 10）
        self.task_editor: QWidget = None          # 任务编辑器（Task 11）
        self.task_library_panel: QWidget = None   # 任务库面板（Task 13）
        self.config_panel: QWidget = None         # 配置面板（Task 14）

        # 当前编辑中的任务序列（用于新建/打开/保存）
        self._current_task_sequence: TaskSequence = None

        # ----------------------------------------------------------------
        # 1. 加载配置
        # ----------------------------------------------------------------
        try:
            config.load()
            logger.info("配置加载完成")
        except Exception as e:
            logger.error(f"加载配置失败: {e}")

        # ----------------------------------------------------------------
        # 2. 加载任务库
        # ----------------------------------------------------------------
        try:
            count = task_library.load_from_config()
            logger.info(f"任务库加载完成，共导入 {count} 个模块")
        except Exception as e:
            logger.error(f"加载任务库失败: {e}")

        # ----------------------------------------------------------------
        # 3. 初始化 UI
        # ----------------------------------------------------------------
        self.init_ui()

        # ----------------------------------------------------------------
        # 4. 连接 task_engine 信号
        # ----------------------------------------------------------------
        self._connect_signals()

        # ----------------------------------------------------------------
        # 5. 更新窗口状态显示 + 自动恢复上次绑定
        # ----------------------------------------------------------------
        self._try_auto_restore_binding()
        self._update_window_status()

        # 初始化任务序列：优先从自动保存文件加载，否则创建空序列
        self._current_task_sequence = self._load_autosave_or_create()
        # 将初始任务序列同步到任务编辑器（_init_real_panels 已创建 task_editor）
        if self.task_editor is not None and isinstance(self.task_editor, TaskEditor):
            self.task_editor.set_task_sequence(self._current_task_sequence)
            # 连接任务序列变化信号到自动保存
            self.task_editor.task_sequence_changed.connect(
                self._auto_save_task_sequence
            )

        # 状态栏初始状态
        self._set_status_text("就绪")

        logger.info("主窗口初始化完成")

    # ==================================================================
    # UI 初始化
    # ==================================================================
    def init_ui(self):
        """初始化所有 UI 组件：窗口属性、菜单栏、工具栏、标签页、状态栏。"""
        # ----------------------------------------------------------------
        # 窗口属性
        # ----------------------------------------------------------------
        # ★2026-08-25 多组标识：窗口标题带组号，方便多实例区分
        import os as _os
        try:
            self._group_id = int(_os.environ.get("MHXY_GROUP", "1"))
        except ValueError:
            self._group_id = 1
        from core.group_config import group_title, load_group_config, GROUP_STYLE
        self._group_cfg = load_group_config(self._group_id)
        # 组标题（角色名由 _update_window_status 动态补全）
        self.setWindowTitle(group_title(self._group_id, roles=self._group_cfg.get("window", {}).get("roles")))
        # 组配色（标题栏/强调色区分）
        _st = GROUP_STYLE.get(self._group_id)
        if _st:
            self.setStyleSheet(
                "QMainWindow::title { color: %s; } QLabel#groupBadge { color: %s; font-weight: bold; }"
                % (_st["accent"], _st["accent"]))
        self.resize(1280, 800)

        # ----------------------------------------------------------------
        # 菜单栏 / 工具栏 / 中央标签页 / 状态栏
        # ----------------------------------------------------------------
        self._init_menu_bar()
        self._init_tool_bar()
        self._init_central_tabs()
        self._init_status_bar()

        # 用真实功能面板替换占位面板（Task 10+）
        self._init_real_panels()

        # 居中显示窗口
        self._center_window()

    # ------------------------------------------------------------------
    # 菜单栏
    # ------------------------------------------------------------------
    def _init_menu_bar(self):
        """构建菜单栏：文件 / 设置 / 帮助。"""
        menubar = self.menuBar()

        # ---------------- 文件菜单 ----------------
        file_menu = menubar.addMenu("文件")

        new_action = QAction("新建任务序列", self)
        new_action.setShortcut("Ctrl+N")
        new_action.setStatusTip("清空当前编辑器，新建一个空任务序列")
        new_action.triggered.connect(self._on_new_task)
        file_menu.addAction(new_action)

        open_action = QAction("打开任务序列...", self)
        open_action.setShortcut("Ctrl+O")
        open_action.setStatusTip("从 JSON 文件加载任务序列")
        open_action.triggered.connect(self._on_open_task)
        file_menu.addAction(open_action)

        save_action = QAction("保存任务序列", self)
        save_action.setShortcut("Ctrl+S")
        save_action.setStatusTip("将当前任务序列保存为 JSON 文件")
        save_action.triggered.connect(self._on_save_task)
        file_menu.addAction(save_action)

        file_menu.addSeparator()

        exit_action = QAction("退出", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.setStatusTip("退出程序")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # ---------------- 设置菜单 ----------------
        settings_menu = menubar.addMenu("设置")

        save_config_action = QAction("保存配置", self)
        save_config_action.setStatusTip("将当前配置保存到 settings.json")
        save_config_action.triggered.connect(self._on_save_config)
        settings_menu.addAction(save_config_action)

        reload_config_action = QAction("重新加载配置", self)
        reload_config_action.setStatusTip("从 settings.json 重新加载配置")
        reload_config_action.triggered.connect(self._on_reload_config)
        settings_menu.addAction(reload_config_action)

        # ---------------- 帮助菜单 ----------------
        help_menu = menubar.addMenu("帮助")

        manual_action = QAction("用户手册", self)
        manual_action.setStatusTip("查看用户手册")
        manual_action.triggered.connect(self._on_show_manual)
        help_menu.addAction(manual_action)

    # ------------------------------------------------------------------
    # 工具栏
    # ------------------------------------------------------------------
    def _init_tool_bar(self):
        """构建工具栏：开始执行 / 暂停 / 停止 + 绑定窗口 + 窗口状态标签。"""
        toolbar = QToolBar("主工具栏", self)
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        # 开始执行按钮（绿色）
        start_action = QAction("▶ 开始执行", self)
        start_action.setStatusTip("开始执行当前任务序列（全部任务）")
        start_action.triggered.connect(self._on_start)
        toolbar.addAction(start_action)

        # 仅执行当前任务按钮（蓝色）：只跑任务下拉框选中的那个任务
        single_action = QAction("▶ 执行当前任务", self)
        single_action.setStatusTip("只执行任务列表下拉框当前选中的任务")
        single_action.triggered.connect(self._on_start_single)
        toolbar.addAction(single_action)

        # 暂停按钮（黄色）
        pause_action = QAction("⏸ 暂停", self)
        pause_action.setStatusTip("暂停任务执行")
        pause_action.triggered.connect(self._on_pause)
        toolbar.addAction(pause_action)

        # 停止按钮（红色）
        stop_action = QAction("⏹ 停止", self)
        stop_action.setStatusTip("停止任务执行")
        stop_action.triggered.connect(self._on_stop)
        toolbar.addAction(stop_action)

        # 分隔符
        toolbar.addSeparator()

        # 绑定窗口按钮
        bind_action = QAction("🔗 绑定窗口", self)
        bind_action.setStatusTip("绑定目标游戏窗口")
        bind_action.triggered.connect(self._on_bind_window)
        toolbar.addAction(bind_action)

        # 窗口状态标签（显示"未绑定"或"已绑定: <标题>"）
        self._window_status_label = QLabel("未绑定")
        self._window_status_label.setStyleSheet(
            "padding: 0 8px; color: #c0392b; font-weight: bold;"
        )
        toolbar.addWidget(self._window_status_label)

        # ★2026-08-25 多组：一键启动其他组 GUI（独立进程）
        toolbar.addSeparator()
        self._group_menu_btn = None
        try:
            from PyQt5.QtWidgets import QToolButton, QMenu
            from PyQt5.QtCore import Qt
            self._group_menu = QMenu(self)
            self._group_menu.triggered.connect(self._on_launch_group)
            # 所有组（排除当前组）
            for g in (1, 2, 3, 4):
                if g == getattr(self, "_group_id", 1):
                    continue
                act = self._group_menu.addAction(f"启动组{g} GUI")
                act.setData(g)
            btn = QToolButton(self)
            btn.setText("🚀 启动其他组")
            btn.setPopupMode(QToolButton.InstantPopup)
            btn.setMenu(self._group_menu)
            btn.setStyleSheet("padding: 4px 10px; font-weight: bold;")
            toolbar.addWidget(btn)
            self._group_menu_btn = btn
        except Exception as e:
            logger.warning(f"多组启动按钮初始化失败: {e}")

    # ------------------------------------------------------------------
    # 中央标签页
    # ------------------------------------------------------------------
    def _init_central_tabs(self):
        """构建中央 QTabWidget，包含 4 个占位标签页。"""
        self._tab_widget = QTabWidget(self)
        self.setCentralWidget(self._tab_widget)

        # 创建 4 个占位面板并保留引用（后续 Task 会替换）
        self.status_panel = PlaceholderPanel("主控制面板 (StatusPanel)", "Task 10")
        self.task_editor = PlaceholderPanel("任务编辑 (TaskEditor)", "Task 11")
        self.task_library_panel = PlaceholderPanel("任务库 (TaskLibraryPanel)", "Task 13")
        self.config_panel = ConfigPanel(self)

        # 标签页索引缓存（便于切换）
        self._tab_index = {
            "status": 0,
            "task": 1,
            "library": 2,
            "config": 3,
        }

        self._tab_widget.addTab(self.status_panel, "主控制面板")
        self._tab_widget.addTab(self.task_editor, "任务编辑")
        self._tab_widget.addTab(self.task_library_panel, "任务库")
        self._tab_widget.addTab(self.config_panel, "配置")

    # ------------------------------------------------------------------
    # 真实面板初始化（替换占位面板）
    # ------------------------------------------------------------------
    def _init_real_panels(self):
        """
        创建真实功能面板并替换对应占位面板。

        各 Task 实现对应面板后，在此处实例化并通过 ``set_*_panel`` 替换占位面板。
        当前已实现：
            - Task 10：StatusPanel（主控制面板）
            - Task 11：TaskEditor（任务编辑）
            - Task 13：TaskLibraryPanel（任务库）
            - Task 14：ConfigPanel（配置）
        """
        # 主控制面板（Task 10）
        self.status_panel = StatusPanel(self)
        self.set_status_panel(self.status_panel)
        logger.info("主控制面板（StatusPanel）已加载")

        # 任务编辑器（Task 11）
        self.task_editor = TaskEditor(self)
        self.set_task_editor(self.task_editor)
        logger.info("任务编辑器（TaskEditor）已加载")

        # 任务库面板（Task 13）
        self.task_library_panel = TaskLibraryPanel(self)
        self.set_library_panel(self.task_library_panel)
        logger.info("任务库面板（TaskLibraryPanel）已加载")

    # ------------------------------------------------------------------
    # 状态栏
    # ------------------------------------------------------------------
    def _init_status_bar(self):
        """构建状态栏。"""
        self._status_bar = QStatusBar(self)
        self.setStatusBar(self._status_bar)
        # ★2026-08-25 组徽章：常驻显示"组N · x号 · 网关:port"（多实例一眼区分）
        try:
            from core.group_config import group_status_text, GROUP_STYLE
            _port = (self._group_cfg.get("gateway") or {}).get("port", 18082)
            _st = GROUP_STYLE.get(self._group_id)
            _roles = (self._group_cfg.get("window") or {}).get("roles") or []
            self._group_badge_text = group_status_text(self._group_id, _port, len(_roles))
            self._group_badge = QLabel(self._group_badge_text + "  ○离线")
            if _st:
                self._group_badge.setStyleSheet("color: %s; font-weight: bold; padding: 0 8px;" % _st["accent"])
            self._group_badge.setObjectName("groupBadge")
            self._status_bar.addPermanentWidget(self._group_badge)
            # ★2026-08-28 补丁1：徽章实时化——网关状态与 GUI 展示一一对应。
            # 判定复用 gateway_guard._ready（与任务库自愈同一事实源）；
            # /api/status 就绪字段带 2s TTL 缓存，轮询零 RPC 开销。
            self._gw_timer = QTimer(self)
            self._gw_timer.setInterval(5000)
            self._gw_timer.timeout.connect(self._refresh_gateway_badge)
            QTimer.singleShot(800, self._refresh_gateway_badge)  # 启动后首次快速刷新
            self._gw_timer.start()
        except Exception:
            pass
        # 永久标签用于显示运行状态文字（如"就绪"、"运行中"、"已暂停"等）
        self._status_label = QLabel("就绪")
        self._status_bar.addPermanentWidget(self._status_label)
        # 进度信息标签（显示当前事件进度）
        self._progress_label = QLabel("")
        self._status_bar.addWidget(self._progress_label)

    def _refresh_gateway_badge(self):
        """★2026-08-28 补丁1：网关徽章实时刷新（补丁对应 gateway-config-review.md）。

        状态映射（判定复用 gateway_guard._ready —— GUI 展示与任务自愈同源）：
          ●在线        绿色  HTTP 通 + attach 本组游戏 PID + lua 已捕获
          ⚠启动中      橙色  网关在线但未就绪（attach / lua 捕获进行中）
          ⚠pid不匹配   橙色  网关在线但 attach 的是别的进程（ensure_gateway 将自愈换绑）
          ○离线        灰色  HTTP 不通（网关未拉起/已停止）

        本地无法确定游戏 PID 时降级为"⚠pid不匹配"语义不成立，改按离线外
        的保守态处理（网关通则显示启动中）。
        """
        try:
            from core.gateway_guard import _bound_pid, _ready, _status
            pid = _bound_pid()
            st = _status(timeout=1.5)
            if st and pid and _ready(st, pid):
                dot, color = "●在线", "#3a9d5d"
            elif st and pid and st.get("pid") == pid:
                dot, color = "⚠启动中", "#c97b2d"
            elif st and pid:
                dot, color = "⚠pid不匹配", "#c97b2d"
            elif st:
                dot, color = "⚠启动中", "#c97b2d"   # 网关通但本地未绑定 PID
            else:
                dot, color = "○离线", "#888888"
        except Exception:
            dot, color = "○离线", "#888888"
        try:
            self._group_badge.setText(f"{self._group_badge_text}  {dot}")
            self._group_badge.setStyleSheet(
                "color: %s; font-weight: bold; padding: 0 8px;" % color)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 窗口居中
    # ------------------------------------------------------------------
    def _center_window(self):
        """将窗口移动到屏幕中央显示。"""
        try:
            screen = self.screen().availableGeometry() if self.screen() else None
            if screen is None:
                return
            x = (screen.width() - self.width()) // 2
            y = (screen.height() - self.height()) // 2
            self.move(screen.x() + x, screen.y() + y)
        except Exception as e:
            logger.warning(f"窗口居中失败: {e}")

    # ==================================================================
    # 信号连接
    # ==================================================================
    def _connect_signals(self):
        """
        连接 task_engine 的信号到槽函数：
            - progress_signal → 更新状态栏和进度
            - log_signal      → 转发到主控制面板的日志区（通过 log_forward 信号）
            - status_signal   → 更新状态栏
            - finished_signal → 弹出完成提示，更新按钮状态
        """
        # 进度信号：(当前事件下标, 总事件数, 事件名称)
        task_engine.progress_signal.connect(self._on_progress)
        # 日志信号：(级别, 消息)
        task_engine.log_signal.connect(self._on_engine_log)
        # 状态信号：状态文本
        task_engine.status_signal.connect(self._on_engine_status)
        # 完成信号：(是否成功, 完成消息)
        task_engine.finished_signal.connect(self._on_engine_finished)

        # ----------------------------------------------------------------
        # 将信号连接到主控制面板（StatusPanel）
        # ----------------------------------------------------------------
        # 进度信号 -> 面板进度更新
        task_engine.progress_signal.connect(self.status_panel.update_progress)
        # 状态信号 -> 面板状态标签更新
        task_engine.status_signal.connect(self.status_panel.update_status)
        # 日志转发信号 -> 面板日志追加（log_forward 由 _on_engine_log 转发
        # task_engine.log_signal，故连接 log_forward 即可接收引擎日志）
        self.log_forward.connect(self.status_panel.append_log)
        # 任务详情信号 -> 面板导出（函数事件成功返回的游戏任务信息落盘 IPC）
        task_engine.quest_detail_signal.connect(
            lambda d: self.status_panel.set_quest_detail(**d)
        )

        logger.info("已连接 task_engine 信号到主窗口槽函数")

    # ==================================================================
    # 工具栏回调
    # ==================================================================
    def _on_start_single(self):
        """工具栏 -> 执行当前任务：只跑任务下拉框选中的那个任务。"""
        logger.info("用户点击：执行当前任务")
        self.start_clicked.emit()

        # 获取任务编辑器当前选中的任务下标
        try:
            idx = self.task_editor.get_current_task_index()
        except Exception as e:
            logger.warning(f"获取当前任务下标失败: {e}")
            idx = -1
        if idx < 0:
            QMessageBox.warning(
                self, "提示", "任务列表中未选中任何任务，请先在任务列表下拉框选择。"
            )
            return

        task_sequence = self._get_current_task_sequence()
        if task_sequence is None or not task_sequence.tasks:
            QMessageBox.warning(self, "提示", "当前没有可执行的任务序列。")
            return
        if idx >= len(task_sequence.tasks):
            QMessageBox.warning(self, "提示", "选中的任务下标越界，请重新选择。")
            return

        task_name = task_sequence.tasks[idx].name
        ok = task_engine.start(task_sequence, task_indices=[idx])
        if ok:
            self._set_status_text("运行中")
            self._progress_label.setText(f"执行单个任务: {task_name}")
            self.status_panel.set_task_name(f"{task_name}（仅此任务）")
        else:
            QMessageBox.warning(
                self, "启动失败", "任务引擎启动失败，可能已在运行中。"
            )

    def _on_start(self):
        """工具栏 -> 开始执行：获取当前任务序列并启动 task_engine。"""
        logger.info("用户点击：开始执行")
        # 发射信号，便于外部控制器监听
        self.start_clicked.emit()

        # 获取当前任务序列
        task_sequence = self._get_current_task_sequence()
        if task_sequence is None:
            QMessageBox.warning(
                self, "提示", "当前没有可执行的任务序列，请先新建或打开任务。"
            )
            return

        if not task_sequence.tasks:
            QMessageBox.warning(
                self, "提示", "任务序列为空，请先在任务编辑器中添加任务。"
            )
            return

        # 调用 task_engine 启动
        ok = task_engine.start(task_sequence)
        if ok:
            self._set_status_text("运行中")
            self._progress_label.setText("任务执行中...")
            # 同步任务名称到主控制面板
            self.status_panel.set_task_name(task_sequence.name)
        else:
            QMessageBox.warning(
                self, "启动失败", "任务引擎启动失败，可能已在运行中。"
            )

    def _on_pause(self):
        """工具栏 -> 暂停：调用 task_engine.pause()。"""
        logger.info("用户点击：暂停")
        self.pause_clicked.emit()
        task_engine.pause()
        # 状态由 status_signal 回调更新，这里不重复设置

    def _on_stop(self):
        """工具栏 -> 停止：调用 task_engine.stop()。"""
        logger.info("用户点击：停止")
        self.stop_clicked.emit()
        task_engine.stop()
        # 状态由 status_signal 回调更新

    def closeEvent(self, event):
        """★2026-08-27 关窗收尾：强制停止任务引擎 + 本组网关。

        铁律：必须走 stop_gateway 的优雅 shutdown（detach frida session），
        直接 taskkill 会导致游戏闪退。清空网关运行数据后，下次打开 GUI
        由启动逻辑重新拉起网关并重新 attach/捕获 Lua state。
        """
        logger.info("用户关闭 GUI：停止任务引擎与本组网关...")
        try:
            if task_engine.is_running:
                task_engine.stop()
        except Exception as e:
            logger.warning(f"停止任务引擎异常（忽略）: {e}")
        try:
            from core.gateway_guard import stop_gateway
            ok, info = stop_gateway(verbose=True)
            logger.info(f"网关已{'停止' if ok else '停止失败'}: {info}")
        except Exception as e:
            logger.warning(f"停止网关异常（忽略）: {e}")
        event.accept()

    # ==================================================================
    # 绑定窗口
    # ==================================================================
    def _on_launch_group(self, action):
        """★2026-08-25 多组：点击"启动组N"→ 独立进程拉起对应组 GUI。

        组2 是独立进程（window_manager/网关单例无法同进程双组），
        从当前 GUI 用 subprocess 拉起另一个 python main.py --group N。
        """
        try:
            target = int(action.data())
        except (TypeError, ValueError):
            return
        import sys, subprocess, os
        py = sys.executable or r"E:\py\python.exe"
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        try:
            proc = subprocess.Popen(
                [py, os.path.join(root, "main.py"), "--group", str(target)],
                cwd=root,
                creationflags=getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
                close_fds=True,
            )
            logger.info(f"已拉起组{target} GUI (pid={proc.pid})")
            self._set_status_text(f"已启动组{target} GUI")
        except Exception as e:
            logger.error(f"启动组{target} GUI 失败: {e}")
            self._set_status_text(f"启动组{target}失败: {e}")

    def _on_bind_window(self):
        """
        工具栏 -> 绑定窗口：弹出游戏窗口列表对话框，
        由用户选择要锁定的窗口（多开时用 PID 区分）。

        与 yolo_auto_train 的 select_game_window 行为对齐：
        window_manager.list_game_windows() 枚举 → 表格选择 →
        window_manager.bind(pid=...) 绑定 → 持久化到 config → 启动自动恢复。
        """
        dlg = WindowSelectorDialog(self)
        dlg.exec_()

        # 绑定结果反馈（对话框内已处理，这里只刷新工具栏状态标签）
        self._update_window_status()
        if window_manager.bound:
            logger.info(
                f"窗口绑定成功: pid={window_manager.pid}, "
                f"hwnd=0x{window_manager.hwnd:X}, "
                f"title={window_manager.window_title!r}"
            )

    def _update_window_status(self):
        """
        更新工具栏的窗口状态标签。

        根据 ``window_manager`` 当前绑定状态显示"未绑定"或"已绑定: PID"。
        ★2026-08-25：同时刷新窗口标题（组号 + 已绑角色名）。
        """
        try:
            valid = window_manager.is_valid()
        except Exception:
            valid = False

        # ★多组：刷新标题带已绑角色名
        try:
            from core.group_config import group_title
            _role = ""
            try:
                _title = getattr(window_manager, "window_title", "") or ""
                import re as _re
                _m = _re.search(r"\(([^()\[\]]+?)\[", _title)
                if _m:
                    _role = _m.group(1).strip()
            except Exception:
                pass
            self.setWindowTitle(group_title(self._group_id, roles=[_role] if _role else None))
        except Exception:
            pass

        if valid and window_manager.hwnd:
            pid_text = f"PID={window_manager.pid}" if window_manager.pid else "无PID"
            text = f"已绑定: {pid_text}"
            self._window_status_label.setText(text)
            self._window_status_label.setStyleSheet(
                "padding: 0 8px; color: #27ae60; font-weight: bold;"
            )
        else:
            self._window_status_label.setText("未绑定")
            self._window_status_label.setStyleSheet(
                "padding: 0 8px; color: #c0392b; font-weight: bold;"
            )

    def _try_auto_restore_binding(self):
        """
        启动时自动尝试恢复上次绑定的窗口。

        仅当配置中 auto_restore 为 True 时执行。
        """
        auto_restore = bool(config.get("window.auto_restore", True))
        if not auto_restore:
            logger.info("自动恢复绑定已禁用，跳过")
            return

        try:
            success = window_manager.try_restore_last_binding()
            if success:
                pid = window_manager.pid
                logger.info(f"自动恢复绑定成功: PID={pid}")
        except Exception as e:
            logger.error(f"自动恢复绑定异常: {e}")

    # ==================================================================
    # 文件菜单回调
    # ==================================================================
    def _on_new_task(self):
        """文件 -> 新建任务序列：清空当前编辑器，创建空任务序列。"""
        logger.info("用户请求：新建任务序列")
        self.new_task.emit()

        # 若当前有未保存的任务序列，提示用户确认
        if (self._current_task_sequence is not None and
                self._current_task_sequence.tasks):
            reply = QMessageBox.question(
                self, "确认新建",
                "当前已有任务序列，新建将清空当前内容。是否继续？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return

        # 创建空任务序列
        self._current_task_sequence = TaskSequence(name="新建任务序列")
        # 同步到任务编辑器，刷新编辑界面
        if isinstance(self.task_editor, TaskEditor):
            self.task_editor.set_task_sequence(self._current_task_sequence)
        self._progress_label.setText("")
        self._set_status_text("就绪")
        logger.info("已新建空任务序列")

        # 提示用户
        QMessageBox.information(self, "新建", "已新建空任务序列。")

    def _on_open_task(self):
        """文件 -> 打开任务序列：弹出文件选择对话框，加载 JSON 文件。"""
        logger.info("用户请求：打开任务序列")
        path, _ = QFileDialog.getOpenFileName(
            self,
            "打开任务序列",
            "",
            "任务序列文件 (*.json);;所有文件 (*.*)",
        )
        if not path:
            return

        # 发射信号通知外部
        self.open_task.emit(path)

        # 调用 TaskSequence.load 加载
        task_sequence = TaskSequence.load(path)
        if task_sequence is None:
            QMessageBox.critical(
                self, "打开失败", f"加载任务序列失败：\n{path}"
            )
            return

        self._current_task_sequence = task_sequence
        # 同步到任务编辑器，刷新编辑界面
        if isinstance(self.task_editor, TaskEditor):
            self.task_editor.set_task_sequence(self._current_task_sequence)
        self._set_status_text(f"已加载: {task_sequence.name}")
        logger.info(f"已加载任务序列: {path} (name={task_sequence.name!r})")
        QMessageBox.information(
            self, "打开成功",
            f"任务序列加载成功：\n名称：{task_sequence.name}\n"
            f"任务数：{len(task_sequence.tasks)}",
        )

    def _on_save_task(self):
        """文件 -> 保存任务序列：弹出保存对话框，保存当前任务序列为 JSON。"""
        logger.info("用户请求：保存任务序列")
        self.save_task.emit()

        task_sequence = self._get_current_task_sequence()
        if task_sequence is None:
            QMessageBox.warning(self, "提示", "当前没有可保存的任务序列。")
            return

        # 默认文件名使用任务序列名称
        default_name = (task_sequence.name or "task_sequence") + ".json"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "保存任务序列",
            default_name,
            "任务序列文件 (*.json);;所有文件 (*.*)",
        )
        if not path:
            return

        # 确保文件后缀为 .json
        if not path.lower().endswith(".json"):
            path += ".json"

        ok = task_sequence.save(path)
        if ok:
            logger.info(f"任务序列已保存: {path}")
            QMessageBox.information(self, "保存成功", f"任务序列已保存：\n{path}")
        else:
            QMessageBox.critical(self, "保存失败", f"保存任务序列失败：\n{path}")

    # ==================================================================
    # 设置菜单回调
    # ==================================================================
    def _on_save_config(self):
        """设置 -> 保存配置：将当前配置保存到 settings.json。"""
        logger.info("用户请求：保存配置")
        try:
            ok = config.save()
            if ok:
                logger.info("配置已保存到 settings.json")
                QMessageBox.information(self, "保存配置", "配置已保存。")
            else:
                QMessageBox.warning(self, "保存配置", "配置保存失败。")
        except Exception as e:
            logger.error(f"保存配置异常: {e}")
            QMessageBox.critical(self, "保存配置", f"保存配置异常：\n{e}")

    def _on_reload_config(self):
        """设置 -> 重新加载配置：从 settings.json 重新加载配置。"""
        logger.info("用户请求：重新加载配置")
        try:
            config.load()
            logger.info("配置已重新加载")
            # 更新窗口状态显示
            self._update_window_status()
            QMessageBox.information(self, "重新加载配置", "配置已重新加载。")
        except Exception as e:
            logger.error(f"重新加载配置异常: {e}")
            QMessageBox.critical(self, "重新加载配置", f"重新加载配置异常：\n{e}")

    # ==================================================================
    # 帮助菜单回调
    # ==================================================================
    def _on_show_manual(self):
        """帮助 -> 用户手册：打开 docs/user_manual.md，暂用 QMessageBox 提示。"""
        # 计算 docs/user_manual.md 的绝对路径
        project_root = config.project_root
        manual_path = os.path.join(project_root, "docs", "user_manual.md")

        if os.path.exists(manual_path):
            # 文件存在，提示用户文件路径（后续可扩展为打开阅读器）
            QMessageBox.information(
                self, "用户手册",
                f"用户手册位于：\n{manual_path}\n\n"
                f"（后续版本将集成内置阅读器）",
            )
        else:
            # 文件不存在，用占位提示
            QMessageBox.information(
                self, "用户手册",
                "用户手册（docs/user_manual.md）暂未提供。\n"
                "请参考项目 docs 目录下的其他文档。",
            )

    # ==================================================================
    # task_engine 信号槽函数
    # ==================================================================
    def _on_progress(self, current: int, total: int, event_name: str):
        """
        progress_signal 槽：更新状态栏和进度显示。

        :param current: 当前事件下标
        :param total: 总事件数
        :param event_name: 事件名称
        """
        # 进度信息显示在状态栏左侧
        self._progress_label.setText(
            f"进度: {current + 1}/{total} - {event_name}"
        )
        # 状态栏显示当前事件
        self._status_label.setText(f"运行中 [{event_name}]")

    def _on_engine_log(self, level: str, message: str):
        """
        log_signal 槽：转发到主控制面板的日志区（通过 log_forward 信号）。

        后续 Task 10 实现 StatusPanel 后，主控制面板可连接
        ``MainWindow.log_forward`` 信号以接收日志。

        :param level: 日志级别字符串
        :param message: 日志消息
        """
        # 转发信号（供后续 StatusPanel 连接）
        self.log_forward.emit(level, message)
        # 同时写入 logger（带级别），保证日志文件有记录
        # 注意：task_engine 内部已经调用过 logger，这里不再重复记录，
        # 避免日志重复。仅做信号转发。

    def _on_engine_status(self, status: str):
        """
        status_signal 槽：更新状态栏。

        :param status: 状态文本（如 "运行中"、"已暂停"、"已停止"、"已完成"）
        """
        self._set_status_text(status)

    def _on_engine_finished(self, success: bool, message: str):
        """
        finished_signal 槽：弹出完成提示，更新按钮状态。

        :param success: 是否成功完成
        :param message: 完成消息
        """
        # 更新进度标签
        self._progress_label.setText("任务已结束")
        # 更新状态栏
        self._set_status_text("已完成" if success else "已停止")

        # 弹出完成提示
        # 注意：QMessageBox.information 的第 4 个参数是 StandardButtons 而非 Icon，
        # 要在成功/失败时显示不同图标，需使用实例方式设置 icon。
        title = "任务完成" if success else "任务终止"
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle(title)
        msg_box.setText(message)
        msg_box.setIcon(
            QMessageBox.Information if success else QMessageBox.Warning
        )
        msg_box.exec_()
        logger.info(f"任务执行结束: success={success}, message={message}")

    # ==================================================================
    # 内部工具方法
    # ==================================================================
    def _set_status_text(self, status: str):
        """更新状态栏的运行状态文字。"""
        self._status_label.setText(status)

    def _get_current_task_sequence(self) -> TaskSequence:
        """
        获取当前任务编辑器中的任务序列。

        优先从 TaskEditor 获取（编辑器与主窗口共享同一 TaskSequence
        引用，所有增删改直接作用于该对象）；编辑器未就绪时回退到
        ``self._current_task_sequence``。
        """
        if isinstance(self.task_editor, TaskEditor):
            ts = self.task_editor.get_task_sequence()
            if ts is not None:
                return ts
        return self._current_task_sequence

    # ==================================================================
    # 任务序列自动保存 / 加载
    # ==================================================================
    # 自动保存文件路径（相对项目根目录）
    _AUTOSAVE_PATH = "data/task_sequence_autosave.json"

    def _autosave_path(self) -> str:
        """任务序列自动保存路径（多组隔离，2026-08-25）。

        组1（默认）：data/task_sequence_autosave.json（历史兼容）
        组2+：优先组配置 task_sequence（如 data/task_sequence_group2.json），
              缺失则回退 data/task_sequence_autosave_g{N}.json
        """
        try:
            from core.group_config import current_group, load_group_config
            g = current_group()
            if g > 1:
                cfg = load_group_config(g)
                p = cfg.get("task_sequence")
                if p:
                    return str(p)
                return f"data/task_sequence_autosave_g{g}.json"
        except Exception:
            pass
        return self._AUTOSAVE_PATH

    def _load_autosave_or_create(self) -> TaskSequence:
        """
        启动时从自动保存文件加载任务序列；文件不存在或加载失败时
        创建一个新的空任务序列。
        """
        path = self._autosave_path()
        ts = TaskSequence.load(path)
        if ts is not None:
            task_count = len(ts.tasks)
            event_count = sum(len(t.events) for t in ts.tasks)
            logger.info(
                f"已从自动保存加载任务序列: name={ts.name!r}, "
                f"任务数={task_count}, 事件数={event_count} (path={path})"
            )
            return ts
        # 加载失败，创建空序列
        return TaskSequence(name="新建任务序列")

    def _auto_save_task_sequence(self):
        """
        自动保存当前任务序列到文件。

        连接到 task_editor 的 task_sequence_changed 信号，
        每次任务/事件增删改时自动触发保存。保存失败仅记录日志，不弹窗打扰用户。
        """
        ts = self._get_current_task_sequence()
        if ts is None:
            return
        try:
            success = ts.save(self._autosave_path())
            if success:
                logger.debug(
                    f"任务序列已自动保存: name={ts.name!r}, "
                    f"任务数={len(ts.tasks)}"
                )
        except Exception as e:
            logger.error(f"任务序列自动保存失败: {e}")

    # ==================================================================
    # 对外公开方法：标签页切换
    # ==================================================================
    def _switch_tab(self, key: str):
        """
        切换到指定标签页。

        :param key: 标签页键名（status / task / library / config）
        """
        index = self._tab_index.get(key)
        if index is not None and 0 <= index < self._tab_widget.count():
            self._tab_widget.setCurrentIndex(index)

    def switch_to_status(self):
        """切换到主控制面板标签页。"""
        self._switch_tab("status")

    def switch_to_task_editor(self):
        """切换到任务编辑标签页。"""
        self._switch_tab("task")

    def switch_to_library(self):
        """切换到任务库标签页。"""
        self._switch_tab("library")

    def switch_to_config(self):
        """切换到配置标签页。"""
        self._switch_tab("config")

    # ==================================================================
    # 对外公开方法：面板替换接口（供后续 Task 10/11/13/14 调用）
    # ==================================================================
    def _replace_tab(self, index: int, new_widget: QWidget, title: str):
        """
        替换指定索引处的标签页内容（保留标签标题）。

        :param index: 标签页索引
        :param new_widget: 新的面板 widget
        :param title: 标签页标题
        """
        if not (0 <= index < self._tab_widget.count()):
            logger.warning(f"替换标签页失败：索引 {index} 越界")
            return
        # 先移除旧 widget（不删除对象，由调用方管理生命周期）
        self._tab_widget.removeTab(index)
        self._tab_widget.insertTab(index, new_widget, title)
        self._tab_widget.setCurrentIndex(index)

    def set_status_panel(self, panel: QWidget):
        """替换主控制面板（Tab1，Task 10 实现）。"""
        self.status_panel = panel
        self._replace_tab(self._tab_index["status"], panel, "主控制面板")

    def set_task_editor(self, panel: QWidget):
        """替换任务编辑器（Tab2，Task 11 实现）。"""
        self.task_editor = panel
        self._replace_tab(self._tab_index["task"], panel, "任务编辑")

    def set_library_panel(self, panel: QWidget):
        """替换任务库面板（Tab3，Task 13 实现）。"""
        self.task_library_panel = panel
        self._replace_tab(self._tab_index["library"], panel, "任务库")

    def set_config_panel(self, panel: QWidget):
        """替换配置面板（Tab4，Task 14 实现）。"""
        self.config_panel = panel
        self._replace_tab(self._tab_index["config"], panel, "配置")

    # ==================================================================
    # 对外公开方法：面板获取接口
    # ==================================================================
    def get_status_panel(self) -> QWidget:
        """返回主控制面板 widget。"""
        return self.status_panel

    def get_task_editor(self) -> QWidget:
        """返回任务编辑器 widget。"""
        return self.task_editor

    def get_library_panel(self) -> QWidget:
        """返回任务库面板 widget。"""
        return self.task_library_panel

    def get_config_panel(self) -> QWidget:
        """返回配置面板 widget。"""
        return self.config_panel

    def get_tab_widget(self) -> QTabWidget:
        """返回中央 QTabWidget，便于外部进一步操作。"""
        return self._tab_widget


# ----------------------------------------------------------------------
# 模块自测：直接运行本文件时弹出主窗口
# ----------------------------------------------------------------------
if __name__ == "__main__":
    from PyQt5.QtWidgets import QApplication

    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())
