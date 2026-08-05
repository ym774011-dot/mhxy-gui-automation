# -*- coding: utf-8 -*-
"""
通用辅助函数模块。

提供时间、文件系统等常用工具函数。
"""
import os
import time
from datetime import datetime


def delay(seconds):
    """
    非阻塞延迟（time.sleep 封装）。

    在简单脚本场景中用作同步等待。注意：在 Qt 主线程中调用会阻塞事件循环，
    如需在 GUI 线程中非阻塞等待，请使用 QTimer 或 QThread。

    :param seconds: 延迟秒数（可为小数）
    """
    if seconds and seconds > 0:
        time.sleep(seconds)


def get_timestamp(fmt="%Y%m%d_%H%M%S"):
    """
    返回格式化的时间戳字符串。

    :param fmt: 时间格式，默认 "%Y%m%d_%H%M%S"
    :return: 当前时间字符串，例如 "20260730_211500"
    """
    return datetime.now().strftime(fmt)


def ensure_dir(path):
    """
    确保目录存在，不存在则递归创建。

    :param path: 目录路径（相对或绝对）
    :return: 传入的目录路径（便于链式调用）
    """
    if path:
        os.makedirs(path, exist_ok=True)
    return path
