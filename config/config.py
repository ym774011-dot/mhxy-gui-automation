# -*- coding: utf-8 -*-
"""
配置管理器模块。

提供 Config 类（单例模式），负责加载、保存、读取和设置配置项。
配置以 JSON 格式持久化到 config/settings.json。
支持点分路径访问嵌套配置项，例如 "window.title"。
"""
import os
import json
import threading

from utils.logger import logger


class Config:
    """
    配置管理器（单例模式）。

    通过 `_instance` 与 `_lock` 实现线程安全的单例。
    使用时直接 import 模块级实例 `config` 即可。

    示例::

        from config.config import config
        title = config.get("window.title", "")
        config.set("window.title", "梦幻西游")
        config.save()
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        # 线程安全的单例实现
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                # 初始化标志，避免重复初始化
                cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        # 仅初始化一次
        if getattr(self, "_initialized", False):
            return
        # 配置文件路径：当前文件所在目录下的 settings.json
        self._config_dir = os.path.dirname(os.path.abspath(__file__))
        self._config_path = os.path.join(self._config_dir, "settings.json")
        # 项目根目录（config 目录的上一级）
        self._project_root = os.path.dirname(self._config_dir)
        # 内存中的配置数据
        self._data = {}
        self._initialized = True
        # 启动时自动加载一次配置
        self.load()

    # ------------------------------------------------------------------
    # 基本加载与保存
    # ------------------------------------------------------------------
    def load(self):
        """从 settings.json 加载配置到内存。文件不存在时使用空配置。"""
        try:
            if os.path.exists(self._config_path):
                with open(self._config_path, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
            else:
                self._data = {}
        except (json.JSONDecodeError, OSError) as e:
            # 加载失败时使用空配置，避免影响程序启动
            self._data = {}
            logger.error(f"[Config] 加载配置失败: {e}")
        return self._data

    def save(self):
        """将内存中的配置保存到 settings.json。"""
        try:
            # 确保目录存在
            os.makedirs(self._config_dir, exist_ok=True)
            with open(self._config_path, "w", encoding="utf-8") as f:
                # ensure_ascii=False 保证中文可读，indent 提升可读性
                json.dump(self._data, f, ensure_ascii=False, indent=2)
            return True
        except OSError as e:
            logger.error(f"[Config] 保存配置失败: {e}")
            return False

    # ------------------------------------------------------------------
    # 通用读取/设置（支持点分路径）
    # ------------------------------------------------------------------
    def get(self, key, default=None):
        """
        获取配置项，支持点分路径。

        :param key: 点分路径，例如 "window.title"
        :param default: 键不存在时返回的默认值
        :return: 配置值，不存在则返回 default
        """
        if not key:
            return default
        current = self._data
        for part in key.split("."):
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return default
        return current

    def set(self, key, value):
        """
        设置配置项，支持点分路径。会自动创建中间层级。

        :param key: 点分路径，例如 "window.title"
        :param value: 要设置的值
        """
        if not key:
            return
        parts = key.split(".")
        current = self._data
        for part in parts[:-1]:
            # 中间层级不存在或类型不正确则创建字典
            if part not in current or not isinstance(current[part], dict):
                current[part] = {}
            current = current[part]
        current[parts[-1]] = value

    # ------------------------------------------------------------------
    # 快捷方法
    # ------------------------------------------------------------------
    def get_window_config(self):
        """获取窗口配置字典。"""
        return self.get("window", {})

    def get_recognition_config(self):
        """获取识别配置字典。"""
        return self.get("recognition", {})

    def get_logging_config(self):
        """获取日志配置字典。"""
        return self.get("logging", {})

    def get_task_library_config(self):
        """获取任务库配置字典。"""
        return self.get("task_library", {})

    # ------------------------------------------------------------------
    # 其他辅助方法
    # ------------------------------------------------------------------
    @property
    def project_root(self):
        """返回项目根目录绝对路径。"""
        return self._project_root

    @property
    def config_path(self):
        """返回配置文件绝对路径。"""
        return self._config_path

    # 旧版坐标文件外部路径（兼容存量数据用，仅作一次性回退，不在新代码散落）
    _LEGACY_MAP_COORD_FILE = r"E:/DS/梦幻西游脚本函数包/地图数据/地图坐标.txt"
    _map_coord_file_legacy_warned = False

    @property
    def map_coord_file(self) -> str:
        """
        地图坐标文件路径（单一事实来源，消除硬编码绝对路径）。

        解析优先级：
            1. settings.json 的 ``paths.map_coord_file``（用户自定义，可移植）
            2. 项目内 ``data/地图坐标.txt``（便携默认，随项目移动）
            3. 旧版外部路径（兼容存量数据；仅首次回退时告警一次，提示迁移）

        这样 GUI / 引擎只需引用 ``config.map_coord_file``，不再出现散落的
        绝对路径字面量；切换机器或目录时改一处配置即可。
        """
        custom = self.get("paths.map_coord_file")
        if custom:
            return custom
        portable = os.path.join(self._project_root, "data", "地图坐标.txt")
        if os.path.exists(portable):
            return portable
        if os.path.exists(self._LEGACY_MAP_COORD_FILE):
            if not Config._map_coord_file_legacy_warned:
                Config._map_coord_file_legacy_warned = True
                logger.warning(
                    "[Config] 地图坐标文件回退到旧路径 %s，"
                    "建议迁移到 %s 或在 settings.json 配置 paths.map_coord_file",
                    self._LEGACY_MAP_COORD_FILE, portable,
                )
            return self._LEGACY_MAP_COORD_FILE
        return portable

    def as_dict(self):
        """返回配置数据的深拷贝引用（调用方应只读不写）。"""
        return self._data


# 模块级单例实例，供全局使用
config = Config()
