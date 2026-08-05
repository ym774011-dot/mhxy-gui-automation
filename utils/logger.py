# -*- coding: utf-8 -*-
"""
日志工具模块。

基于 Python 标准 logging 模块，同时输出日志到控制台与文件。
提供 PyQt5 信号支持，便于 GUI 实时显示日志。

使用方式::

    from utils.logger import logger
    logger.info("开始执行任务")
    logger.error("识别失败")
"""
import os
import time
import logging

from PyQt5.QtCore import QObject, pyqtSignal


class LogSignal(QObject):
    """
    日志信号对象。

    通过 ``log_signal`` 发射 (级别, 消息) 元组，
    GUI 可连接该信号以实现日志实时显示。
    """
    # 参数：(级别字符串, 日志消息字符串)
    log_signal = pyqtSignal(str, str)


class Logger:
    """
    日志封装类。

    包装标准 logging.Logger，并提供 PyQt5 信号发射能力。
    每次记录日志时，除了写入控制台和文件，还会通过 ``log_signal`` 发射信号。
    """

    def __init__(self, name="mhxy", log_file=None, level="INFO"):
        self._logger = logging.getLogger(name)
        # 设置日志级别
        self._logger.setLevel(getattr(logging, str(level).upper(), logging.INFO))
        # 避免重复添加 handler（模块被多次导入时）
        if not self._logger.handlers:
            self._setup_handlers(log_file)
        # 阻止日志向上层 root logger 传播，避免重复输出
        self._logger.propagate = False
        # 信号对象（QObject），GUI 连接 logger.signal.log_signal 即可
        self._signal = LogSignal()

    def _setup_handlers(self, log_file):
        """配置控制台与文件 handler。"""
        fmt = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        # 控制台 handler
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(fmt)
        self._logger.addHandler(console_handler)

        # 文件 handler（如果指定了路径）
        if log_file:
            # 支持相对路径：相对于项目根目录解析
            if not os.path.isabs(log_file):
                project_root = os.path.dirname(
                    os.path.dirname(os.path.abspath(__file__))
                )
                log_file = os.path.join(project_root, log_file)
            # 确保日志目录存在
            log_dir = os.path.dirname(log_file)
            if log_dir:
                os.makedirs(log_dir, exist_ok=True)
            try:
                file_handler = logging.FileHandler(log_file, encoding="utf-8")
                file_handler.setFormatter(fmt)
                self._logger.addHandler(file_handler)
            except OSError as e:
                # 文件 handler 创建失败不应阻断程序运行
                print(f"[Logger] 无法创建日志文件 {log_file}: {e}")

    @property
    def signal(self):
        """返回 LogSignal 实例，供 GUI 连接信号。"""
        return self._signal

    @property
    def level(self):
        """当前日志级别。"""
        return self._logger.level

    def set_level(self, level):
        """动态设置日志级别，level 可为字符串或 logging 常量。"""
        if isinstance(level, str):
            level = getattr(logging, level.upper(), logging.INFO)
        self._logger.setLevel(level)

    # ------------------------------------------------------------------
    # 内部：记录并发射信号
    # ------------------------------------------------------------------
    def _emit_signal(self, level_str, msg):
        """向 GUI 发射日志信号，失败时静默忽略。"""
        try:
            self._signal.log_signal.emit(level_str, str(msg))
        except Exception:
            # 信号发射失败不应影响日志记录
            pass

    # ------------------------------------------------------------------
    # 标准日志方法
    # ------------------------------------------------------------------
    def debug(self, msg, *args, **kwargs):
        self._logger.debug(msg, *args, **kwargs)
        self._emit_signal("DEBUG", msg)

    def info(self, msg, *args, **kwargs):
        self._logger.info(msg, *args, **kwargs)
        self._emit_signal("INFO", msg)

    def warning(self, msg, *args, **kwargs):
        self._logger.warning(msg, *args, **kwargs)
        self._emit_signal("WARNING", msg)

    def error(self, msg, *args, **kwargs):
        self._logger.error(msg, *args, **kwargs)
        self._emit_signal("ERROR", msg)

    def exception(self, msg, *args, **kwargs):
        self._logger.exception(msg, *args, **kwargs)
        self._emit_signal("ERROR", msg)

    def critical(self, msg, *args, **kwargs):
        self._logger.critical(msg, *args, **kwargs)
        self._emit_signal("CRITICAL", msg)


def cleanup_old_logs(log_file_path: str, days: int) -> int:
    """清理指定日志目录下超过 N 天的同名前缀日志文件。

    :param log_file_path: 当前日志文件路径（如 logs/automation.log）
    :param days: 保留天数；<= 0 跳过
    :return: 删除的文件数
    """
    if not log_file_path or days <= 0:
        return 0
    try:
        # 相对路径 → 相对于项目根目录
        path = log_file_path
        if not os.path.isabs(path):
            project_root = os.path.dirname(
                os.path.dirname(os.path.abspath(__file__))
            )
            path = os.path.join(project_root, path)
        log_dir = os.path.dirname(os.path.abspath(path))
        base = os.path.basename(path)
        prefix = base.rsplit(".", 1)[0] if "." in base else base
        if not os.path.isdir(log_dir):
            return 0
        cutoff = time.time() - days * 86400
        removed = 0
        for fn in os.listdir(log_dir):
            # 匹配：同名前缀 + .log 结尾，但排除当前日志本身（fn == base）
            if fn == base:
                continue
            if not (fn.startswith(prefix + ".") and fn.endswith(".log")):
                continue
            fp = os.path.join(log_dir, fn)
            if not os.path.isfile(fp):
                continue
            try:
                if os.path.getmtime(fp) < cutoff:
                    os.remove(fp)
                    removed += 1
                    print(f"[Logger] 已清理过期日志: {fn}")
            except OSError:
                pass
        return removed
    except Exception as e:
        print(f"[Logger] 清理日志失败: {e}")
        return 0


# 模块级单例实例，默认日志文件为项目根目录下 logs/automation.log，级别 INFO
logger = Logger(name="mhxy", log_file="logs/automation.log", level="INFO")
