# -*- coding: utf-8 -*-
"""
函数专用精简 GUI —— 只完美支持现有任务库函数，零冗余。

设计原则（2026-08-31，用户定案）：
  - 旧 GUI（main.py + gui/ 四面板）承载了任务序列编辑器/事件链/条件分支/
    watchdog/captcha monitor 等大量"多余"逻辑，且部分组件（captcha
    monitor/watchdog）已被实测定为崩溃源。本 GUI 从零重写，只保留
    「选择现有函数 → 填参数 → 执行 → 看日志 → 停止」这条最小闭环。
  - __不 import core.captcha_link / monitor / watchdog__（崩溃源隔离）。
  - 函数发现 / 参数表单 / 函数调用 全部基于 core.task_library_manager 的
    动态扫描与 call_function（与旧 GUI 同源，语义一致：PID 注入/后台模式/
    禁区规避/关键字过滤都有）。

运行方式:
    E:\\py\\python.exe main.py
    （独立运行，无需旧 main.py；不拉起任何 watchdog/captcha monitor）
"""
import os
import sys
import json
import time
import threading
import traceback

# 项目根 = 本文件上一级
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# 预加载 MSVC 运行库，防 PyQt5 + cv2 加载冲突（与旧 main.py 同款铁律）
try:
    import ctypes
    _sys32 = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")
    for _dll in ("vcruntime140.dll", "vcruntime140_1.dll",
                 "msvcp140.dll", "msvcp140_1.dll"):
        _p = os.path.join(_sys32, _dll)
        if os.path.exists(_p):
            ctypes.WinDLL(_p)
except Exception:
    pass

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QFont, QColor, QTextCursor
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QLineEdit, QSpinBox,
    QDoubleSpinBox, QCheckBox, QPlainTextEdit, QGroupBox, QFormLayout,
    QScrollArea, QFrame, QSplitter, QMessageBox, QToolButton, QFileDialog,
    QListWidget, QListWidgetItem,
)

# ---- core 运行时（唯一依赖层） ----
# 注意：绝不 import core.captcha_link / core.captcha_v7 相关 watchdog/monitor。
from config.config import config
from core.window_manager import window_manager
from core.task_library_manager import task_library
from core.task_engine import task_engine  # 仅复用 should_stop 标志


# ======================================================================
# 参数表单构造器：根据 inspect.signature + __function_meta__ 生成控件
# ======================================================================
import inspect
inspect_sig_empty = inspect.Parameter.empty


class FuncParamForm(QWidget):
    """
    自动参数表单：按函数签名生成控件。

    规则：
      - bool                 → QCheckBox
      - int / Enum / int枚举  → QSpinBox（有上下限时用 range 映射）
      - float                → QDoubleSpinBox
      - str                  → QLineEdit
      - list / tuple / dict  → QLineEdit（json 文本，元组填 "(1,2)"）
      - 默认 None 且无明确类型 → QLineEdit（json 文本,综合parse）
    收集时：collect_kwargs() 返回 {参数名: 值}。
    """

    def __init__(self, module_name: str, function_name: str, func, meta: dict, parent=None):
        super().__init__(parent)
        self.module_name = module_name
        self.function_name = function_name
        self.func = func
        self.meta = meta or {}      # __function_meta__ 中该函数条目
        self._controls = {}         # 参数名 -> (kind, widget, extras)
        self._descriptions = {}     # 参数名 -> 中文说明

        try:
            self._sig = inspect.signature(func)
        except (ValueError, TypeError):
            self._sig = None

        self._build()

    # ------------------------------------------------------------------
    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        if self._sig is None:
            layout.addWidget(QLabel("（无法解析函数签名）"))
            return

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setContentsMargins(4, 4, 4, 4)
        form.setSpacing(6)

        # meta 中文标注（__function_meta__[func]["args"]）
        arg_meta = {}
        if isinstance(self.meta, dict):
            _m = self.meta.get("args")
            if isinstance(_m, dict):
                arg_meta = _m

        params = list(self._sig.parameters.values())
        for p in params:
            # 跳过 *args / **kwargs（任务库函数均不使用变参来承载语义参数）
            if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
                continue
            name = p.name
            desc = str(arg_meta.get(name, ""))
            default = p.default
            has_default = default is not inspect_sig_empty
            annotation = p.annotation

            label_txt = name
            widget, kind, extras = self._make_control(
                name, annotation, default, has_default, desc)

            lbl = QLabel(label_txt)
            lbl.setToolTip(f"{label_txt}\n{desc}" if desc else label_txt)
            if not has_default:
                lbl.setStyleSheet("color: #c0392b; font-weight: bold;")
            form.addRow(lbl, widget)
            self._controls[name] = (kind, widget, extras)
            self._descriptions[name] = desc

        # 参数较多时允许两列排布；简单起见保持单列滚动
        layout.addLayout(form)
        layout.addStretch(1)

    # ------------------------------------------------------------------
    def _make_control(self, name, annotation, default, has_default, desc):
        """按类型生成控件。返回 (widget, kind, extras)。"""
        # 1) 明确 bool
        if has_default and isinstance(default, bool) or annotation is bool:
            cb = QCheckBox()
            cb.setChecked(bool(default) if has_default else False)
            if has_default:
                cb.setText("✓" if default else "")
            if desc:
                cb.setToolTip(desc)
            return cb, "bool", {}

        # 2) int（含枚举值）
        if has_default and isinstance(default, int) and not isinstance(default, bool):
            return self._int_control(default, desc), "int", {}
        if annotation is int:
            return self._int_control(0 if not has_default else default, desc), "int", {}

        # 3) float
        if has_default and isinstance(default, float) and not isinstance(default, bool):
            return self._float_control(default, desc), "float", {}
        if annotation is float:
            return self._float_control(0.0 if not has_default else default, desc), "float", {}

        # 4) str
        if has_default and isinstance(default, str):
            return self._str_control(default, desc), "str", {}
        if annotation is str:
            return self._str_control("" if not has_default else default, desc), "str", {}

        # 5) 序列 / 字典 / 其它 → 文本 json 化（宽松解析）
        #    ★ tuple 类型（如 home_coord: Tuple[int,int]=(240,101)）→ 解析回 tuple
        _as_tuple = False
        if has_default and isinstance(default, tuple):
            _as_tuple = True
        elif self._is_tuple_annotation(annotation):
            _as_tuple = True
        _tv = self._text_control(default, has_default, desc, name, as_tuple=_as_tuple)
        return _tv, "text", {"as_tuple": _as_tuple}

    @staticmethod
    def _is_tuple_annotation(annotation) -> bool:
        if annotation in (tuple, ()):
            return True
        try:
            from typing import Tuple
            if annotation is Tuple or (hasattr(annotation, "__origin__")
                                       and getattr(annotation, "__origin__", None) is tuple):
                return True
        except Exception:
            pass
        return False

    def _int_control(self, value, desc):
        sp = QSpinBox()
        sp.setRange(-1 << 30, (1 << 30) - 1)
        sp.setValue(int(value) if isinstance(value, (int, float)) else 0)
        if desc:
            sp.setToolTip(desc)
        return sp

    def _float_control(self, value, desc):
        sp = QDoubleSpinBox()
        sp.setRange(-1e9, 1e9)
        sp.setDecimals(3)
        sp.setValue(float(value) if isinstance(value, (int, float)) else 0.0)
        if desc:
            sp.setToolTip(desc)
        return sp

    def _str_control(self, value, desc):
        ed = QLineEdit(value if isinstance(value, str) else str(value))
        ed.setPlaceholderText("字符串")
        if desc:
            ed.setToolTip(desc)
        return ed

    def _text_control(self, default, has_default, desc, name, as_tuple=False):
        ed = QLineEdit()
        # 默认值转 json 文本显示（tuple 显示为 "(240, 101)" 元组语法）
        if has_default and default is not None:
            if as_tuple:
                ed.setText(str(tuple(default)) if isinstance(default, (list, tuple))
                           else str(default))
            else:
                try:
                    ed.setText(json.dumps(default, ensure_ascii=False))
                except Exception:
                    ed.setText(str(default))
        ed.setPlaceholderText("json/元组/空=用默认")
        if desc:
            ed.setToolTip(desc)
        return ed

    # ------------------------------------------------------------------
    def collect_kwargs(self) -> dict:
        """收集表单值 → kwargs 字典。跳过与默认一致的项（尽量用函数默认）。"""
        kwargs = {}
        if self._controls is None:
            return kwargs
        for name, (kind, widget, extras) in self._controls.items():
            try:
                value = self._read_control(kind, widget, extras)
            except Exception:
                continue
            if value is _SKIP:
                continue
            kwargs[name] = value
        return kwargs

    def set_kwargs(self, kwargs: dict):
        """把已保存的 kwargs 回填到表单控件（参数持久化加载用）。

        - 只覆盖表单里存在的参数名；类型不匹配的项跳过并保持默认。
        - 文本类（str/text）直接 setText：str 原样、list/dict/tuple 转 json/元组语法。
        """
        if not kwargs or not self._controls:
            return
        for name, (kind, widget, extras) in self._controls.items():
            if name not in kwargs:
                continue
            try:
                value = kwargs[name]
                if kind == "bool":
                    widget.setChecked(bool(value))
                elif kind == "int":
                    widget.setValue(int(value))
                elif kind == "float":
                    widget.setValue(float(value))
                elif kind == "str":
                    widget.setText(str(value))
                elif kind == "text":
                    if extras.get("as_tuple") and isinstance(value, (list, tuple)):
                        widget.setText(str(tuple(value)))
                    else:
                        widget.setText(
                            json.dumps(value, ensure_ascii=False)
                            if isinstance(value, (list, dict, tuple)) else str(value))
            except Exception:
                continue  # 类型不适配的保留默认，不报错

    # ------------------------------------------------------------------
    def _read_control(self, kind, widget, extras=None):
        extras = extras or {}
        if kind == "bool":
            return widget.isChecked()
        if kind == "int":
            return widget.value()
        if kind == "float":
            return widget.value()
        if kind == "str":
            return widget.text()
        # text：宽松解析 json / 元组 / 原样字符串
        txt = widget.text().strip()
        if not txt:
            return _SKIP
        val = _loose_parse(txt)
        if extras.get("as_tuple") and isinstance(val, list):
            return tuple(val)
        return val


class _Skip:
    __slots__ = ()

    def __repr__(self):
        return "<skip>"


_SKIP = _Skip()


def _loose_parse(text: str):
    """宽松解析参数文本：
    - json 数组/字典/数字/bool/null → 原样 json
    - "(1, 2)" 元组文本 → 元组
    - 其它 → 按字符串处理
    """
    t = text.strip()
    # 元组语法 (a, b)
    if t.startswith("(") and t.endswith(")"):
        try:
            inner = t[1:-1].strip()
            if inner:
                parts = [p.strip() for p in inner.split(",")]
                return tuple(_loose_parse(p) for p in parts)
            return ()
        except Exception:
            pass
    try:
        return json.loads(t)
    except Exception:
        return t


# ======================================================================
# 函数专用主窗口
# ======================================================================
class FuncMainWindow(QMainWindow):
    """函数专用精简主窗口。"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("函数专用 · 精简执行器")
        self.resize(1180, 760)

        # 状态
        self._running = False
        self._worker: threading.Thread = None
        # 模块 -> 函数缓存: {模块名: [(函数名, func, sig, meta), ...]}
        self._func_cache: dict = {}
        self._current_form: FuncParamForm = None

        self._init_ui()
        self._load_library()
        self._refresh_window_list()

        # 网关状态定时刷新
        self._gw_timer = QTimer(self)
        self._gw_timer.setInterval(3000)
        self._gw_timer.timeout.connect(self._refresh_gateway_status)
        self._gw_timer.start()
        QTimer.singleShot(500, self._refresh_gateway_status)

        self._set_status("就绪")

    # ==================================================================
    # UI
    # ==================================================================
    def _init_ui(self):
        root = QWidget(self)
        self.setCentralWidget(root)
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(6, 6, 6, 6)
        root_layout.setSpacing(6)

        # ---------- 顶栏：窗口绑定 + 网关 ----------
        top = QHBoxLayout()
        top.setSpacing(6)

        top.addWidget(self._mk_label("游戏窗口："))
        self.window_combo = QComboBox()
        self.window_combo.setMinimumWidth(420)
        self.window_combo.setToolTip("游戏窗口列表（含多开器子窗口）")
        top.addWidget(self.window_combo, 1)

        self.bind_btn = QPushButton("绑定窗口")
        self.bind_btn.clicked.connect(self._on_bind)
        top.addWidget(self.bind_btn)

        self.unbind_btn = QPushButton("解除绑定")
        self.unbind_btn.clicked.connect(self._on_unbind)
        top.addWidget(self.unbind_btn)

        self.gw_status_label = QLabel("网关: ○离线")
        self.gw_status_label.setStyleSheet("font-weight: bold; color: #888;")
        top.addWidget(self.gw_status_label)

        self.gw_start_btn = QPushButton("启动网关")
        self.gw_start_btn.clicked.connect(lambda: self._ensure_gw())
        top.addWidget(self.gw_start_btn)

        self.gw_stop_btn = QPushButton("停网关")
        self.gw_stop_btn.setToolTip("软停：任务停止，frida 会话保留后台，下次启动自动复用（不重复 attach，防游戏崩溃）")
        self.gw_stop_btn.clicked.connect(self._on_stop_gateway)
        top.addWidget(self.gw_stop_btn)

        self.gw_kill_btn = QPushButton("彻底停(危险)")
        self.gw_kill_btn.setToolTip(
            "彻底停 = frida 会话 detach + 杀网关进程（下次启动需重新 attach）。\n"
            "实测：同一游戏进程反复 attach/detach 有极低概率引发游戏崩溃，非必要请用「停网关」")
        self.gw_kill_btn.clicked.connect(self._on_kill_gateway)
        top.addWidget(self.gw_kill_btn)

        top.addSpacing(8)

        # 运行按钮
        self.run_btn = QPushButton("▶ 执行函数")
        self.run_btn.setStyleSheet(
            "QPushButton { background:#27ae60; color:white; font-weight:bold; padding:6px 18px; }")
        self.run_btn.clicked.connect(self._on_run)
        top.addWidget(self.run_btn)

        self.stop_btn = QPushButton("⏹ 停止")
        self.stop_btn.setStyleSheet(
            "QPushButton { background:#c0392b; color:white; font-weight:bold; padding:6px 18px; }")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._on_stop)
        top.addWidget(self.stop_btn)

        root_layout.addLayout(top)

        # ---------- 中部：左=模块/函数树，右=参数表单 ----------
        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)

        # 左：QListWidget 两栏（模块 / 函数）
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)

        left_layout.addWidget(self._mk_label("模块（task_library）", bold=True))
        self.module_list = QListWidget()
        self.module_list.currentRowChanged.connect(self._on_module_changed)
        left_layout.addWidget(self.module_list, 1)

        left_layout.addWidget(self._mk_label("函数", bold=True))
        self.func_list = QListWidget()
        self.func_list.currentRowChanged.connect(self._on_func_changed)
        left_layout.addWidget(self.func_list, 1)

        left_panel.setMinimumWidth(340)
        splitter.addWidget(left_panel)

        # 右：函数描述 + 参数表单（滚动）
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(4)

        self.func_desc = QLabel("请选择模块与函数")
        self.func_desc.setWordWrap(True)
        self.func_desc.setStyleSheet("color:#555;")
        right_layout.addWidget(self.func_desc)

        # 参数操作按钮行：保存 / 加载 / 重置
        param_btn_row = QHBoxLayout()
        param_btn_row.setSpacing(6)
        self.params_save_btn = QPushButton("💾 保存参数")
        self.params_save_btn.setToolTip("将当前表单参数保存到 函数专用/params.json（下次自动恢复）")
        self.params_save_btn.clicked.connect(self._on_save_params)
        param_btn_row.addWidget(self.params_save_btn)
        self.params_load_btn = QPushButton("↺ 重置参数")
        self.params_load_btn.setToolTip("把控件恢复为函数默认值")
        self.params_load_btn.clicked.connect(self._on_reset_params)
        param_btn_row.addWidget(self.params_load_btn)
        param_btn_row.addStretch(1)
        right_layout.addLayout(param_btn_row)

        self.param_scroll = QScrollArea()
        self.param_scroll.setWidgetResizable(True)
        self.param_scroll.setStyleSheet("QScrollArea { border:1px solid #ccc; }")
        right_layout.addWidget(self.param_scroll, 1)

        splitter.addWidget(right_panel)
        splitter.setSizes([420, 740])

        root_layout.addWidget(splitter, 1)

        # ---------- 底栏：日志 ----------
        root_layout.addWidget(self._mk_label("运行日志", bold=True))
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(6000)
        font = QFont("Consolas", 9)
        self.log_view.setFont(font)
        root_layout.addWidget(self.log_view, 1)

        # 底部状态行
        status_row = QHBoxLayout()
        self.status_label = QLabel("就绪")
        self.status_label.setStyleSheet("color:#2980b9; font-weight:bold;")
        status_row.addWidget(self.status_label)
        status_row.addStretch(1)

        self.clear_log_btn = QPushButton("清空日志")
        self.clear_log_btn.clicked.connect(self.log_view.clear)
        status_row.addWidget(self.clear_log_btn)
        root_layout.addLayout(status_row)

    @staticmethod
    def _mk_label(text, bold=False):
        lb = QLabel(text)
        if bold:
            lb.setStyleSheet("font-weight:bold;")
        return lb

    # ==================================================================
    # 任务库加载（与旧 GUI 同源）
    # ==================================================================
    def _load_library(self):
        """从 config 加载任务库模块并扫描函数，填充模块/函数列表。"""
        count = 0
        try:
            count = task_library.load_from_config()
        except Exception as e:
            self._append_log(f"加载任务库失败: {e}")
        self._append_log(f"任务库加载完成，共 {count} 个模块")

        modules = task_library.get_all_modules()
        self.module_list.clear()
        self._func_cache.clear()
        enabled_names = []
        for name, info in modules.items():
            enabled_names.append(name)
            self._func_cache.setdefault(name, [])

        # 按名称排序显示
        for name in sorted(enabled_names):
            info = modules.get(name) or {}
            cat = info.get("category", "custom")
            enabled = info.get("enabled", True)
            mark = "" if enabled else "（禁用）"
            item = QListWidgetItem(f"{name} [{cat}]{mark}")
            item.setData(Qt.UserRole, name)
            self.module_list.addItem(item)

        # 自动选中第一个模块
        if self.module_list.count() > 0:
            self.module_list.setCurrentRow(0)

    def _scan_functions_of(self, module_name: str):
        """扫描模块函数（含 __function_meta__ 中文标题）。"""
        if module_name in self._func_cache and self._func_cache[module_name]:
            return self._func_cache[module_name]
        funcs = []
        try:
            raw = task_library.get_functions(module_name)  # [(name, func, sig_str)]
            info = task_library.get_module(module_name) or {}
            module = info.get("module")
            meta = {}
            if module is not None:
                meta = getattr(module, "__function_meta__", {}) or {}
            for fname, fobj, sig_str in raw:
                entry = meta.get(fname, {}) if isinstance(meta, dict) else {}
                title = entry.get("title", "") if isinstance(entry, dict) else ""
                funcs.append((fname, fobj, sig_str, title))
        except Exception as e:
            self._append_log(f"扫描 {module_name} 函数失败: {e}")
        funcs.sort(key=lambda x: x[0])
        self._func_cache[module_name] = funcs
        return funcs

    def _on_module_changed(self, row):
        if row < 0:
            return
        item = self.module_list.item(row)
        module_name = item.data(Qt.UserRole)
        funcs = self._scan_functions_of(module_name)
        self.func_list.clear()
        for fname, _fobj, sig_str, title in funcs:
            label = f"{title}  |  {fname}" if title else fname
            li = QListWidgetItem(label)
            li.setData(Qt.UserRole, (module_name, fname))
            li.setData(Qt.UserRole + 1, sig_str)
            self.func_list.addItem(li)
        if funcs:
            self.func_list.setCurrentRow(0)

    def _on_func_changed(self, row):
        if row < 0:
            return
        li = self.func_list.item(row)
        module_name, fname = li.data(Qt.UserRole)
        sig_str = li.data(Qt.UserRole + 1) or ""
        self._build_param_form(module_name, fname, sig_str)

    def _build_param_form(self, module_name, fname, sig_str):
        """按函数签名构建参数表单。"""
        if self._current_form is not None:
            self._current_form.setParent(None)
            self._current_form.deleteLater()
            self._current_form = None

        info = task_library.get_module(module_name) or {}
        module = info.get("module")
        fobj = None
        meta = {}
        if module is not None:
            meta = getattr(module, "__function_meta__", {}) or {}
            fobj = getattr(module, fname, None)

        self.func_desc.setText(
            f"模块: {module_name}   函数: {fname}\n签名: {sig_str}"
            if sig_str else f"模块: {module_name}   函数: {fname}"
        )

        if fobj is None or not callable(fobj):
            self.func_desc.setText(
                f"模块: {module_name}   函数: {fname}\n（无法获取函数对象，跳过参数表单）")
            return

        try:
            entry = meta.get(fname, {}) if isinstance(meta, dict) else {}
        except Exception:
            entry = {}
        form = FuncParamForm(module_name, fname, fobj, entry)

        self.param_scroll.setWidget(form)
        self._current_form = form

        # ★参数持久化：切换到该函数时自动回填已保存的参数（若存在）
        saved = self._load_params_for(module_name, fname)
        if saved:
            form.set_kwargs(saved)
            self._append_log(f"已恢复 {module_name}.{fname} 的保存参数")

    # ==================================================================
    # 参数持久化（save/load/reset）
    # ==================================================================
    _PARAMS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "params.json")

    def _params_db(self) -> dict:
        """读参数库 {module: {func: kwarg_dict}}；不存在返回 {}。"""
        try:
            with open(self._PARAMS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _load_params_for(self, module_name, fname) -> dict:
        """读取指定函数的已保存参数；无则返回 {}。"""
        db = self._params_db()
        return db.get(module_name, {}).get(fname, {}) if isinstance(db.get(module_name), dict) else {}

    def _on_save_params(self):
        """保存当前表单参数（按 module.func 分组覆盖）。"""
        if self._current_form is None:
            QMessageBox.information(self, "提示", "请先选择函数。")
            return
        module_name = self._current_form.module_name
        fname = self._current_form.function_name
        kwargs = self._current_form.collect_kwargs()
        try:
            db = self._params_db()
            db.setdefault(module_name, {})[fname] = kwargs
            with open(self._PARAMS_FILE, "w", encoding="utf-8") as f:
                json.dump(db, f, ensure_ascii=False, indent=2)
            self._append_log(f"💾 已保存 {module_name}.{fname} 参数（{len(kwargs)} 项）")
        except Exception as e:
            QMessageBox.warning(self, "保存失败", str(e))

    def _on_reset_params(self):
        """重置当前表单为函数默认值：重建表单（不保存）。"""
        if self._current_form is None:
            return
        module_name = self._current_form.module_name
        fname = self._current_form.function_name
        # 从函数列表行取回签名，重建（默认值）
        for i in range(self.func_list.count()):
            li = self.func_list.item(i)
            if li.data(Qt.UserRole) == (module_name, fname):
                self._build_param_form(module_name, fname, li.data(Qt.UserRole + 1) or "")
                self._append_log(f"↺ 已重置 {module_name}.{fname} 为函数默认值")
                return
        self._build_param_form(module_name, fname, "")

    # ==================================================================
    # 关闭收尾：优雅停网关（强杀会崩游戏，旧 GUI 铁律）
    # ==================================================================
    def closeEvent(self, event):
        """关窗时：停任务；网关会话保留后台常驻（防重复 attach 崩游戏）。"""
        self._append_log("关闭 GUI：停止任务；网关会话保留后台运行，下次打开自动复用...")
        try:
            if self._running:
                task_engine.should_stop.set()
        except Exception:
            pass
        try:
            from core.gateway_guard import stop_gateway
            # 软停：不 detach 不杀进程（2026-08-31 实测：同一游戏进程反复
            # attach/detach 会引发延迟 AV 崩溃），下次启动 ensure_gateway 直接复用
            ok, info = stop_gateway(verbose=False)
            self._append_log(f"网关软停(会话保留): ok={ok}")
        except Exception:
            pass
        event.accept()

    # ==================================================================
    # 窗口绑定 / 网关
    # ==================================================================
    def _refresh_window_list(self):
        """枚举游戏窗口填充下拉（含多开器子窗口）。"""
        try:
            wins = window_manager.list_game_windows()
        except Exception as e:
            self._append_log(f"枚举游戏窗口失败: {e}")
            wins = []
        self.window_combo.clear()
        for hwnd, title, pid, visible in wins:
            vis = "可见" if visible else "隐"
            self.window_combo.addItem(
                f"[{pid}] {title}（{vis}）", (hwnd, pid))
        # 若已绑定，选中对应项
        if window_manager.bound:
            bp = window_manager.pid
            for i in range(self.window_combo.count()):
                if self.window_combo.itemData(i) and self.window_combo.itemData(i)[1] == bp:
                    self.window_combo.setCurrentIndex(i)
                    break
        self._refresh_window_status()

    def _refresh_window_status(self):
        if window_manager.bound:
            self.bind_btn.setText(f"已绑定 PID={window_manager.pid}")
        else:
            self.bind_btn.setText("绑定窗口")

    def _on_bind(self):
        data = self.window_combo.currentData()
        if not data:
            QMessageBox.warning(self, "提示", "窗口列表为空，请先打开游戏。")
            return
        hwnd, pid = data
        ok = window_manager.bind(pid=int(pid))
        if ok:
            self._append_log(
                f"绑定成功: PID={pid}, hwnd=0x{hwnd:X}, title={window_manager.window_title!r}")
        else:
            self._append_log(f"绑定失败: PID={pid}")
        self._refresh_window_status()

    def _on_unbind(self):
        window_manager.unbind()
        self._append_log("已解除绑定")
        self._refresh_window_status()

    def _refresh_gateway_status(self):
        try:
            from core.gateway_guard import _status as _gw_status, _bound_pid
            pid = _bound_pid()
            st = _gw_status(timeout=1.2)
            if st and pid and st.get("attached") and st.get("pid") == pid \
                    and st.get("lua_state_captured") and not st.get("script_status_error"):
                self.gw_status_label.setText(f"网关: ●在线 (PID={pid})")
                self.gw_status_label.setStyleSheet("color:#3a9d5d; font-weight:bold;")
            elif st:
                self.gw_status_label.setText("网关: ⚠启动中/未就绪")
                self.gw_status_label.setStyleSheet("color:#c97b2d; font-weight:bold;")
            else:
                self.gw_status_label.setText("网关: ○离线")
                self.gw_status_label.setStyleSheet("color:#888; font-weight:bold;")
        except Exception:
            self.gw_status_label.setText("网关: ○离线")
            self.gw_status_label.setStyleSheet("color:#888; font-weight:bold;")

    def _ensure_gw(self):
        """拉起网关（后台线程，不阻塞 UI）。"""
        try:
            from core.gateway_guard import ensure_gateway
        except Exception:
            self._append_log("gateway_guard 导入失败")
            return

        self._append_log("启动网关中...")

        def _work():
            try:
                ok, info = ensure_gateway(timeout=90.0, verbose=True)
                if ok:
                    self._append_log(f"网关就绪: {info}")
                else:
                    self._append_log(f"网关启动失败: {info}")
            except Exception as e:
                self._append_log(f"网关启动异常: {e}")

        threading.Thread(target=_work, daemon=True, name="gw-start").start()

    def _on_stop_gateway(self):
        self._append_log("停网关（软停）：任务停止，frida 会话保留，下次启动自动复用，不重复 attach...")

        def _work():
            try:
                from core.gateway_guard import stop_gateway
                ok, info = stop_gateway(verbose=True)
                self._append_log(f"网关软停完成: ok={ok} action={info.get('action')} {info.get('note','')}")
            except Exception as e:
                self._append_log(f"网关软停异常: {e}")

        threading.Thread(target=_work, daemon=True, name="gw-stop").start()

    def _on_kill_gateway(self):
        """彻底停网关（危险）：detach frida 会话 + 杀网关进程，下次启动需重新 attach。

        2026-08-31 实测：同一游戏进程反复 attach/detach 有极低概率延迟引爆
        游戏 AV 崩溃（0xc0000005），仅排查异常/确需释放注入时使用。
        """
        ret = QMessageBox.question(
            self, "彻底停网关（危险）",
            "彻底停 = frida 会话 detach + 杀网关进程（下次启动需重新 attach）。\n"
            "实测：同一游戏进程反复 attach/detach 有极低概率引发游戏崩溃。\n\n"
            "确认彻底停止吗？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ret != QMessageBox.Yes:
            self._append_log("已取消彻底停网关")
            return

        def _work():
            try:
                from core.gateway_guard import stop_gateway
                ok, info = stop_gateway(kill=True, verbose=True)
                self._append_log(f"网关已彻底停止: ok={ok} {info}")
            except Exception as e:
                self._append_log(f"彻底停网关异常: {e}")

        threading.Thread(target=_work, daemon=True, name="gw-kill").start()

    # ==================================================================
    # 执行 / 停止
    # ==================================================================
    def _on_run(self):
        if self._running:
            return
        if self._current_form is None:
            QMessageBox.warning(self, "提示", "请先选择函数。")
            return

        module_name = self._current_form.module_name
        function_name = self._current_form.function_name
        kwargs = self._current_form.collect_kwargs()

        # 记录执行配置
        self._append_log(f"▶ 执行 {module_name}.{function_name}")
        if kwargs:
            self._append_log(f"   参数: {json.dumps(kwargs, ensure_ascii=False)}")

        # 停止标志复位（复用 task_engine.should_stop，现有函数 _gui_stop_requested 依赖）
        try:
            task_engine.should_stop.clear()
        except Exception:
            pass

        self._set_running(True)
        self._worker = threading.Thread(
            target=self._worker_run,
            args=(module_name, function_name, kwargs),
            daemon=True,
            name="func-run",
        )
        self._worker.start()

    def _worker_run(self, module_name, function_name, kwargs):
        """工作线程：调用 task_library.call_function。"""
        # 捕获 print 输出到日志区
        old_stdout, old_stderr = sys.stdout, sys.stderr
        sink = _LogSink()
        try:
            sys.stdout = sink
            sys.stderr = sink
            success, result, error = task_library.call_function(
                module_name, function_name, **kwargs)
            if success:
                _BRIDGE.log_signal.emit(
                    f"✔ 执行成功: {json.dumps(result, ensure_ascii=False, default=str)}")
            else:
                _BRIDGE.log_signal.emit(f"✘ 执行失败: {error}")
        except Exception as e:
            _BRIDGE.log_signal.emit(f"✘ 执行异常: {e}")
            _BRIDGE.log_signal.emit(traceback.format_exc())
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr
            _BRIDGE.log_signal.emit("━━━━━━━━━━ 函数结束 ━━━━━━━━━━")
            _BRIDGE.done_signal.emit()

    def _on_worker_done(self):
        """（主线程槽）执行结束复位按钮与状态。"""
        self._running = False
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self._set_status("就绪")

    def _on_stop(self):
        try:
            task_engine.should_stop.set()
            self._append_log("⏹ 已请求停止（函数内长循环将尽快退出）")
        except Exception:
            pass

    def _set_running(self, flag):
        self._running = flag
        self.run_btn.setEnabled(not flag)
        self.stop_btn.setEnabled(flag)
        self._set_status("运行中" if flag else "就绪")

    # ------------------------------------------------------------------
    # 线程安全的日志：Qt 信号桥
    # ------------------------------------------------------------------
    def _append_log(self, text):
        self.log_view.appendPlainText(str(text))
        # 滚到底
        c = self.log_view.textCursor()
        c.movePosition(QTextCursor.End)
        self.log_view.setTextCursor(c)

    def _set_status(self, s):
        self.status_label.setText(s)

    # ------------------------------------------------------------------
    # 日志镜像到文件（供外部/守护观察；与旧 WORLD_BOSS farm 的终端输出对齐）
    # ------------------------------------------------------------------
    def _append_log(self, text):
        self.log_view.appendPlainText(str(text))
        # 滚到底
        c = self.log_view.textCursor()
        c.movePosition(QTextCursor.End)
        self.log_view.setTextCursor(c)
        # 镜像到 run.log（线程安全：单写者主线程 + _LogSink 带锁，ata 追加）
        _mirror_write(str(text))


_RLOCK = threading.Lock()


def _mirror_write(text: str):
    """把日志行追加写到 函数专用/run.log（幂等，自动建目录）。"""
    if not text:
        return
    try:
        with _RLOCK:
            with open(_RUN_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(text if text.endswith("\n") else text + "\n")
    except Exception:
        pass


# 全局日志镜像路径（模块级变量，供 _LogSink 调用）
_RUN_LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "run.log")


# 线程安全日志桥：工作线程 emit 信号，主线程槽追加到 UI
from PyQt5.QtCore import QObject as _QtObject


class _LogBridge(_QtObject):
    log_signal = pyqtSignal(str)        # 日志文本
    done_signal = pyqtSignal()          # 执行完成（结束态复位）
    status_signal = pyqtSignal(str)     # 状态文本


_BRIDGE = _LogBridge()


class _LogSink(object):
    """把 print 输出桥接到主线程日志（经 pyqtSignal 跨线程）+ 镜像到 run.log。"""

    _CACHE = ""  # 行缓冲（print 常分段调用）

    def __init__(self, signal_obj=None):
        self._sig = signal_obj or _BRIDGE.log_signal
        self._buf = ""

    def write(self, text):
        if not text:
            return
        self._sig.emit(str(text))
        _mirror_write(str(text))

    def flush(self):
        pass


def main():
    app = QApplication(sys.argv)
    win = FuncMainWindow()
    _BRIDGE.log_signal.connect(win._append_log)
    _BRIDGE.done_signal.connect(win._on_worker_done)
    _BRIDGE.status_signal.connect(win._set_status)
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()