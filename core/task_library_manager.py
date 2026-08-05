# -*- coding: utf-8 -*-
"""
任务库管理器模块。

提供 TaskLibraryManager 类，负责动态导入、扫描、管理任务脚本模块（.py 文件）。
支持从 config 配置加载预置模块、运行时动态导入/移除/重载模块、调用模块中的函数等。

模块信息存储结构::

    modules = {
        "JHRW": {
            "module":   <module 对象>,            # 已导入的 Python 模块
            "path":     "E:\\DS\\...\\JHRW.py",   # 文件绝对路径
            "enabled":  True,                     # 是否启用
            "category": "custom",                 # 分类（custom / map / ...）
            "functions": [                        # scan_functions 扫描结果缓存
                ("JHRW", <func>, "(target_location=None, ...)"),
                ...
            ],
        },
        ...
    }

使用方式::

    from core.task_library_manager import task_library

    task_library.load_from_config()                      # 从配置加载预置模块
    funcs = task_library.get_functions("JHRW")           # 获取模块函数列表
    ok, result, err = task_library.call_function(        # 调用模块函数
        "JHRW", "JHRW", verbose=False
    )
"""
import os
import sys
import inspect
import importlib.util
import threading

from config.config import config
from utils.logger import logger


class TaskLibraryManager:
    """
    任务库管理器。

    负责管理所有动态导入的任务脚本模块。线程安全（内部使用 RLock 保护
    ``modules`` 字典的并发访问）。
    """

    def __init__(self):
        # 已导入的模块信息字典：{模块名: 信息字典}
        # 信息字典字段：module / path / enabled / category / functions
        self.modules = {}
        # 可重入锁，保护 self.modules 的并发访问
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # 模块导入与扫描
    # ------------------------------------------------------------------
    def load_from_config(self):
        """
        从 config 加载所有预置模块配置并导入。

        读取 ``settings.json`` 中 ``task_library.modules`` 列表，逐个尝试导入。
        单个模块导入失败不会影响其他模块，仅记录错误日志。

        :return: 成功导入的模块数量
        """
        modules_cfg = config.get("task_library.modules", []) or []
        success_count = 0
        logger.info(f"开始从配置加载任务库模块，共 {len(modules_cfg)} 个")

        for item in modules_cfg:
            name = item.get("name")
            path = item.get("path")
            enabled = item.get("enabled", True)
            category = item.get("category", "custom")

            if not name or not path:
                logger.warning(f"跳过无效配置项（缺少 name 或 path）: {item}")
                continue

            ok = self.import_module(name, path, category=category)
            if ok:
                # 按配置文件中的 enabled 状态覆盖默认值
                with self._lock:
                    if name in self.modules:
                        self.modules[name]["enabled"] = bool(enabled)
                success_count += 1

        logger.info(f"任务库加载完成，成功 {success_count}/{len(modules_cfg)} 个模块")
        return success_count

    def import_module(self, name, path, category="custom"):
        """
        动态导入一个 .py 文件作为任务模块。

        使用 ``importlib.util.spec_from_file_location`` + ``module_from_spec``
        + ``exec_module`` 三步完成动态导入。导入后自动扫描可调用函数并记录到
        ``modules`` 字典。

        :param name: 模块名（作为 modules 字典的键）
        :param path: .py 文件路径（绝对路径或相对项目根目录的路径）
        :param category: 模块分类，默认 "custom"
        :return: 是否导入成功
        """
        if not name or not path:
            logger.error(f"导入失败：name 或 path 为空 (name={name!r}, path={path!r})")
            return False

        # 路径规范化：相对路径基于项目根目录解析
        if not os.path.isabs(path):
            path = os.path.join(config.project_root, path)
        path = os.path.abspath(path)

        if not os.path.exists(path):
            logger.error(f"导入失败：文件不存在 - {path}")
            return False
        if not path.lower().endswith(".py"):
            logger.error(f"导入失败：不是 .py 文件 - {path}")
            return False

        try:
            # 使用带前缀的唯一 spec 名，避免与 sys.modules 中已注册的同名模块冲突
            spec_name = f"task_lib_{name}"
            spec = importlib.util.spec_from_file_location(spec_name, path)
            if spec is None or spec.loader is None:
                logger.error(f"导入失败：无法创建模块 spec - {path}")
                return False

            module = importlib.util.module_from_spec(spec)

            # 注册到 sys.modules（部分模块内部会用到 __name__ 或相对导入机制）
            sys.modules[spec_name] = module
            try:
                spec.loader.exec_module(module)
            except Exception:
                # exec_module 执行失败：清理 sys.modules 残留后重新抛出
                sys.modules.pop(spec_name, None)
                raise

            # 扫描可调用函数
            functions = self.scan_functions(module)

            with self._lock:
                # 若已存在同名模块，保留原 enabled 状态；否则默认启用
                prev_enabled = self.modules.get(name, {}).get("enabled", True)
                self.modules[name] = {
                    "module": module,
                    "path": path,
                    "enabled": prev_enabled,
                    "category": category,
                    "functions": functions,
                }

            logger.info(
                f"成功导入模块 '{name}' (category={category})，"
                f"共 {len(functions)} 个函数: {path}"
            )
            return True

        except Exception as e:
            # 任意异常都不影响其他模块的导入
            logger.exception(f"导入模块 '{name}' 失败: {path} - {e}")
            return False

    def scan_functions(self, module):
        """
        扫描模块中的可调用函数。

        过滤规则：
            - 排除以下划线开头的名称（_xxx、__xxx__，包括 __name__、__doc__ 等）
            - 只保留 callable 且不是模块、不是类的对象

        :param module: 已导入的模块对象
        :return: [(函数名, 函数对象, 函数签名字符串), ...] 按函数名排序
        """
        result = []
        if module is None:
            return result

        for attr_name in dir(module):
            # 排除下划线开头（_xxx 和 __xxx__ 都会被过滤）
            if attr_name.startswith("_"):
                continue

            try:
                obj = getattr(module, attr_name)
            except Exception:
                # 某些属性的访问可能抛异常（如动态属性），直接跳过
                continue

            # 必须可调用
            if not callable(obj):
                continue
            # 排除模块对象和类对象
            if inspect.ismodule(obj) or inspect.isclass(obj):
                continue

            # 获取函数签名
            sig_str = self._get_signature_str(obj)
            result.append((attr_name, obj, sig_str))

        # 按函数名排序，便于查看
        result.sort(key=lambda x: x[0])
        return result

    @staticmethod
    def _get_signature_str(obj):
        """
        获取可调用对象的签名字符串，失败时返回空串。

        优先尝试读取 ``obj.__module__`` 模块的 ``__function_meta__`` 字典,
        若命中该函数名,返回 ``f"{title}  |  {orig_sig}"`` 形式(中文标题 + 原签名),
        用于 GUI 下拉框的直观显示。未声明 meta 时回退到 ``inspect.signature(obj)``。

        模块约定(可选):
            __function_meta__ = {
                "<function_name>": {
                    "title": "中文一行说明",
                    "args": {"<param>": "中文说明", ...},
                },
                ...
            }

        :return: 显示字符串;无法获取签名时返回空串。
        """
        try:
            sig = inspect.signature(obj)
            orig_sig = str(sig)
        except (ValueError, TypeError):
            return ""

        # 优先取模块自带的 __function_meta__（function_lib_<name> 已注册到 sys.modules）
        module_name = getattr(obj, "__module__", None)
        if module_name:
            mod = sys.modules.get(module_name)
            meta = getattr(mod, "__function_meta__", None) if mod else None
            if isinstance(meta, dict):
                entry = meta.get(obj.__name__)
                if isinstance(entry, dict):
                    title = entry.get("title")
                    if isinstance(title, str) and title.strip():
                        return f"{title}  |  {orig_sig}"
        return orig_sig

    # ------------------------------------------------------------------
    # 启用 / 禁用 / 移除 / 重载
    # ------------------------------------------------------------------
    def enable_module(self, name):
        """启用指定模块。返回是否操作成功。"""
        with self._lock:
            if name in self.modules:
                self.modules[name]["enabled"] = True
                logger.info(f"已启用模块 '{name}'")
                return True
        logger.warning(f"启用失败：模块不存在 - {name}")
        return False

    def disable_module(self, name):
        """禁用指定模块。返回是否操作成功。"""
        with self._lock:
            if name in self.modules:
                self.modules[name]["enabled"] = False
                logger.info(f"已禁用模块 '{name}'")
                return True
        logger.warning(f"禁用失败：模块不存在 - {name}")
        return False

    def remove_module(self, name):
        """
        移除模块。

        同时从 ``self.modules`` 字典与 ``sys.modules`` 中清理对应条目。

        :return: 是否移除成功
        """
        with self._lock:
            if name not in self.modules:
                logger.warning(f"移除失败：模块不存在 - {name}")
                return False
            info = self.modules.pop(name)
            # 清理 sys.modules 中导入时注册的 spec_name
            sys.modules.pop(f"task_lib_{name}", None)
        logger.info(f"已移除模块 '{name}' (category={info.get('category')})")
        return True

    def reload_module(self, name):
        """
        重新加载模块（开发时修改了脚本后刷新）。

        使用原 path 与 category 重新执行导入流程，并保留原 ``enabled`` 状态。

        :return: 是否重载成功
        """
        with self._lock:
            info = self.modules.get(name)
            if info is None:
                logger.warning(f"重载失败：模块不存在 - {name}")
                return False
            path = info.get("path")
            category = info.get("category", "custom")
            enabled = info.get("enabled", True)

        # 先清理 sys.modules 中的旧实例，避免 importlib 复用缓存
        sys.modules.pop(f"task_lib_{name}", None)

        ok = self.import_module(name, path, category=category)
        if ok:
            # 恢复原有的 enabled 状态
            with self._lock:
                if name in self.modules:
                    self.modules[name]["enabled"] = enabled
            logger.info(f"已重载模块 '{name}'")
        return ok

    # ------------------------------------------------------------------
    # 查询接口
    # ------------------------------------------------------------------
    def get_module(self, name):
        """
        获取模块信息。

        :return: 模块信息字典的浅拷贝；模块不存在返回 None
        """
        with self._lock:
            info = self.modules.get(name)
            return dict(info) if info is not None else None

    def get_all_modules(self):
        """返回所有模块信息字典（浅拷贝），键为模块名。"""
        with self._lock:
            return {k: dict(v) for k, v in self.modules.items()}

    def get_enabled_modules(self):
        """返回所有已启用模块信息字典（浅拷贝）。"""
        with self._lock:
            return {
                k: dict(v) for k, v in self.modules.items() if v.get("enabled")
            }

    def get_functions(self, module_name):
        """
        获取指定模块的函数列表。

        :return: [(函数名, 函数对象, 函数签名), ...]；模块不存在返回空列表
        """
        with self._lock:
            info = self.modules.get(module_name)
            if info is None:
                logger.warning(f"获取函数失败：模块不存在 - {module_name}")
                return []
            # 返回列表浅拷贝，避免外部修改内部缓存
            return list(info.get("functions", []))

    # ------------------------------------------------------------------
    # 文档搜索
    # ------------------------------------------------------------------
    def search_by_keyword(self, keyword, category=None):
        """
        根据关键词在模块文档（__doc__）中搜索匹配的模块。

        :param keyword: 搜索关键词（如中文地图名 "东海湾"）
        :param category: 可选，限定搜索的模块分类（如 "map"）
        :return: 匹配的模块列表 [(模块名, 模块信息字典), ...]，按匹配度排序
        """
        results = []
        with self._lock:
            for name, info in self.modules.items():
                if not info.get("enabled"):
                    continue
                if category and info.get("category") != category:
                    continue

                module = info.get("module")
                if module is None:
                    continue

                doc = getattr(module, "__doc__", "") or ""
                if not doc:
                    continue

                # 关键词在文档中出现次数
                count = doc.count(keyword)
                if count > 0:
                    results.append((name, info, count))

        # 按匹配次数排序（匹配次数越多越相关）
        results.sort(key=lambda x: x[2], reverse=True)
        # 返回模块名和信息字典（去掉 count）
        return [(name, info) for name, info, _ in results]

    def search_map_by_name(self, chinese_name):
        """
        根据中文地图名查找对应的地图模块。

        :param chinese_name: 中文地图名（如 "东海湾"）
        :return: 匹配的地图模块名（如 "DHW"），找不到返回 None
        """
        results = self.search_by_keyword(chinese_name, category="map")
        if results:
            # 返回第一个匹配的模块名
            return results[0][0]
        return None

    # ------------------------------------------------------------------
    # 函数调用
    # ------------------------------------------------------------------
    def call_function(self, module_name, function_name, *args, **kwargs):
        """
        调用指定模块中的函数。

        :param module_name: 模块名
        :param function_name: 函数名
        :param args, kwargs: 透传给目标函数的参数
        :return: (success: bool, result: any, error: str)
                 - 成功： (True, 函数返回值, "")
                 - 失败： (False, None, 错误信息)
        """
        # 在锁内查找模块与函数对象，锁外执行实际调用（避免长耗时函数阻塞其他操作）
        with self._lock:
            info = self.modules.get(module_name)
            if info is None:
                msg = f"模块不存在: {module_name}"
                logger.error(msg)
                return False, None, msg

            if not info.get("enabled"):
                msg = f"模块已禁用: {module_name}"
                logger.warning(msg)
                return False, None, msg

            func = None
            # 优先从扫描结果中查找
            for fname, fobj, _ in info.get("functions", []):
                if fname == function_name:
                    func = fobj
                    break
            # 兜底：直接从模块对象获取（应对扫描后新增的属性）
            if func is None:
                module = info.get("module")
                if module is not None and hasattr(module, function_name):
                    func = getattr(module, function_name)

        if func is None or not callable(func):
            msg = f"函数不存在或不可调用: {module_name}.{function_name}"
            logger.error(msg)
            return False, None, msg

        # 过滤函数不支持的关键字参数（GUI「填入关键字参数」按通用规则生成 key，
        # 可能与具体函数签名不符，如 JNYW 等点击函数不接受 location/target_location）。
        # 必须在 _inject_bound_pid 之前执行：否则 bind_partial 会因未知关键字抛
        # TypeError 而跳过 PID 注入，导致地图函数回退到写死的 DEFAULT_PID。
        kwargs = self._filter_kwargs(func, module_name, function_name, kwargs)

        # 注入「脚本绑定的游戏 PID」：若目标函数接受 pid 参数、
        # 且调用方未显式传入，则默认使用 window_manager 单例里用户已绑定的 PID。
        # 这样无需在每个地图函数里写死 PID，也天然消歧多开场景。
        args, kwargs = self._inject_bound_pid(func, module_name, function_name, args, kwargs)

        # 注入「后台输入模式」：配置 window.input_mode=background 时，给接受
        # background 参数的函数（地图点击函数）自动注入 background=True，
        # 让点击走 PostMessage 后台分支（不抢焦点、不动真实鼠标）。
        # 调用方显式传入的 background 优先级更高（不覆盖）。
        try:
            args, kwargs = self._inject_background_mode(
                func, module_name, function_name, args, kwargs
            )
        except Exception as e:
            logger.debug(f"后台模式注入异常（不影响原调用）: {e}")

        # 地图禁区规避：目标坐标在传送热点/陷阱禁区内时，自动修正到
        # 最近的安全点，防止角色走上去触发跨图传送（用户 2026-08-05 反馈：
        # 建邺城江湖大盗 (171,109) 站在传送点上）。
        # 仅对地图函数（JYC/JNYW/DHW... 接受 target_coord 参数）生效。
        try:
            args, kwargs = self._avoid_no_go_zone(
                func, module_name, function_name, args, kwargs
            )
        except Exception as e:
            logger.debug(f"禁区规避异常（不影响原调用）: {e}")

        try:
            result = func(*args, **kwargs)
            return True, result, ""
        except Exception as e:
            msg = f"调用 {module_name}.{function_name} 异常: {e}"
            logger.exception(msg)
            return False, None, msg

    # ------------------------------------------------------------------
    # PID 注入（脚本绑定窗口）
    # ------------------------------------------------------------------
    def _inject_bound_pid(self, func, module_name, function_name, args, kwargs):
        """若目标函数接受 pid 参数且调用方未显式传入，则注入 window_manager 绑定的 PID。

        设计意图：
        - GUI 中用户通过「绑定窗口」明确选定了目标游戏进程（window_manager.pid）。
        - 地图函数包（JNYW/XLNR/DHW/JYC 等）原本各自写死 DEFAULT_PID，
          与绑定脱节，导致实际 PID 变化（重启/重开）后静默不点。
        - 在此统一注入，函数包保持独立、可 CLI 运行，同时经引擎调用时
          自动采用用户已绑定的 PID，天然消歧多开场景。

        :param func: 目标可调用对象
        :param args, kwargs: 原调用参数
        :return: (args, kwargs) 可能已注入 pid
        """
        # 1) 函数没有 pid 参数 —— 不处理
        try:
            sig = inspect.signature(func)
        except (ValueError, TypeError):
            return args, kwargs
        if "pid" not in sig.parameters:
            return args, kwargs

        # 2) 调用方已显式提供 pid（关键字或位置）—— 尊重调用方，不覆盖
        try:
            bound = sig.bind_partial(*args, **kwargs)
        except TypeError:
            # 位置参数不匹配签名（理论上不会，因实际调用也会抛同样错）；跳过注入
            return args, kwargs
        if "pid" in bound.arguments:
            return args, kwargs

        # 3) 取 window_manager 单例里用户绑定的 PID
        bound_pid = 0
        try:
            from core.window_manager import window_manager
            bound_pid = int(getattr(window_manager, "pid", 0) or 0)
        except Exception:
            bound_pid = 0

        if bound_pid > 0:
            kwargs["pid"] = bound_pid
            logger.info(
                f"[task_library] 注入脚本绑定 PID={bound_pid} → "
                f"{module_name}.{function_name}"
            )
        return args, kwargs

    # ------------------------------------------------------------------
    # 后台输入模式注入
    # ------------------------------------------------------------------
    def _inject_background_mode(self, func, module_name, function_name, args, kwargs):
        """配置 input_mode=background 时，给地图函数注入 background=True。

        地图函数（JNYW/JYC/DHW... 9 个）的 background 参数默认 False，走前台
        SetCursorPos+mouse_event（抢焦点、动真实鼠标）。全后台化时需按配置
        注入 True，让点击走 PostMessage 后台分支。

        规则：
          - 仅当配置 window.input_mode == "background" 且函数签名接受 background
          - 调用方显式传入的 background 优先（不覆盖，兼容个别想前台的操作）
        """
        try:
            from core.input_controller import input_controller
            mode = input_controller._get_mode()
        except Exception:
            return args, kwargs
        if mode != "background":
            return args, kwargs
        try:
            sig = inspect.signature(func)
            if "background" not in sig.parameters:
                return args, kwargs
        except (ValueError, TypeError):
            return args, kwargs
        if "background" in kwargs:
            return args, kwargs  # 调用方显式指定，尊重
        kwargs["background"] = True
        logger.info(
            f"[后台模式] 注入 background=True → {module_name}.{function_name}"
        )
        return args, kwargs

    # ------------------------------------------------------------------
    # 地图禁区规避
    # ------------------------------------------------------------------
    def _avoid_no_go_zone(self, func, module_name, function_name, args, kwargs):
        """目标坐标在地图禁区内时，修正到最近安全点。

        地图函数（JYC/JNYW/DHW...）接受 target_coord 参数；若该坐标落在
        data/map_no_go_zones.json 的禁区内（传送热点/陷阱），调用前自动
        偏移到禁区外最近点，防止角色走上去触发跨图传送。

        :param func: 目标可调用对象
        :param module_name: 模块名（如 'JYC'，用于映射地图名）
        :param function_name: 函数名（仅用于日志）
        :param args, kwargs: 原调用参数
        :return: (args, kwargs) 可能已修正 target_coord
        """
        # 1) 只有地图函数才处理（映射表里有模块名 = 地图函数）
        from core.map_no_go import MODULE_MAP_NAME, safe_target_for_module
        if module_name not in MODULE_MAP_NAME:
            return args, kwargs

        # 2) 从 kwargs 或 args 中找 target_coord
        coord = None
        is_kwarg = False
        is_expanded = False  # args 以 (x, y) 两个数字展开传参
        if "target_coord" in kwargs and kwargs["target_coord"] is not None:
            coord = kwargs["target_coord"]
            is_kwarg = True
        elif args:
            # 场景 A：JYC((x,y), ...) 元组传参 —— 第一个位置参数是 target_coord
            try:
                sig = inspect.signature(func)
                params = list(sig.parameters.values())
                if params and params[0].name == "target_coord":
                    _a0 = args[0]
                    # 仅当 args[0] 是坐标形态（元组/列表含两个数字）才采用
                    if isinstance(_a0, (list, tuple)) and len(_a0) >= 2:
                        coord = tuple(_a0)
                    elif isinstance(_a0, (int, float)):
                        pass  # 单个数字 → 不是坐标，留给场景 B
            except (ValueError, TypeError):
                coord = None
            # 场景 B：JYC(x, y) 展开 —— args 前两个都是数字
            if coord is None and len(args) >= 2 \
                    and isinstance(args[0], (int, float)) \
                    and isinstance(args[1], (int, float)):
                coord = (args[0], args[1])
                is_expanded = True

        if coord is None:
            return args, kwargs
        try:
            gx, gy = float(coord[0]), float(coord[1])
        except (TypeError, ValueError, IndexError):
            return args, kwargs

        # 3) 禁区修正（game 级：传送热点/陷阱）
        sx, sy, adjusted = safe_target_for_module(module_name, (gx, gy))
        if adjusted:
            gx, gy = sx, sy
            logger.info(
                f"[禁区规避] {module_name} 目标 在禁区内 → 修正为 ({gx:.0f},{gy:.0f})"
            )

        # 4) UI 遮挡避让（pixel 级：大地图/任务追踪面板/小地图）
        #    目标 game 坐标映射成客户区像素，落在 UI 矩形内则沿最近边界偏移
        from core.map_ui_block import map_coord_ui_avoid
        map_name = MODULE_MAP_NAME[module_name]
        ngx, ngy, ui_name = map_coord_ui_avoid(map_name, gx, gy)
        if ui_name:
            logger.info(
                f"[UI避让] {module_name} 目标 ({gx:.0f},{gy:.0f}) "
                f"像素在「{ui_name}」内 → 修正为 ({ngx:.0f},{ngy:.0f})"
            )
            gx, gy = ngx, ngy

        if not (adjusted or ui_name):
            return args, kwargs

        new_coord = (gx, gy)
        if is_kwarg:
            kwargs["target_coord"] = new_coord
        else:
            # 位置参数：元组传参替换 args[0]；展开传参替换 args[0], args[1]
            args = list(args)
            if is_expanded:
                args[0] = new_coord[0]
                args[1] = new_coord[1]
            else:
                args[0] = new_coord
            args = tuple(args)
        return args, kwargs

    # ------------------------------------------------------------------
    # 关键字参数过滤
    # ------------------------------------------------------------------
    def _filter_kwargs(self, func, module_name, function_name, kwargs):
        """过滤掉目标函数签名中不存在的关键字参数。

        背景：GUI「填入关键字参数」按通用规则生成 key（如 target_location），
        但不同地图函数签名各异——JHRW 接受 target_location，而
        JNYW/ALG/BXG/CSC/DHW/JYC/XLNR/ZZG 等点击函数只接受
        target_coord/pid/click/background/verbose，不接受任何 location 类参数。
        若不过滤，会抛 ``TypeError: XXX() got an unexpected keyword argument
        'location'``，导致整个函数调用事件失败。

        本方法统一剔除函数不支持的 kwargs，并记录 warning 便于排查配置错误。
        若函数声明了 ``**kwargs``，则接受任意关键字参数，不过滤。

        :param func: 目标可调用对象
        :param module_name: 模块名（仅用于日志）
        :param function_name: 函数名（仅用于日志）
        :param kwargs: 原关键字参数
        :return: 过滤后的 kwargs
        """
        if not kwargs:
            return kwargs
        try:
            sig = inspect.signature(func)
        except (ValueError, TypeError):
            return kwargs

        params = sig.parameters
        # 函数声明了 **kwargs → 接受任意关键字，不过滤
        if any(p.kind == p.VAR_KEYWORD for p in params.values()):
            return kwargs

        valid_keys = set(params.keys())
        filtered = {k: v for k, v in kwargs.items() if k in valid_keys}
        dropped = set(kwargs.keys()) - set(filtered.keys())
        if dropped:
            logger.warning(
                f"[task_library] 已过滤 {module_name}.{function_name} 不支持的"
                f"关键字参数: {sorted(dropped)}（函数仅接受 {sorted(valid_keys)}）"
            )
        return filtered

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------
    def save_to_config(self):
        """
        将当前模块列表保存到 config（持久化到 settings.json）。

        保存格式为 ``task_library.modules`` 列表，每项包含
        ``{name, path, enabled, category}``。

        :return: 是否保存成功
        """
        with self._lock:
            modules_list = [
                {
                    "name": name,
                    "path": info.get("path", ""),
                    "enabled": bool(info.get("enabled", True)),
                    "category": info.get("category", "custom"),
                }
                for name, info in self.modules.items()
            ]

        config.set("task_library.modules", modules_list)
        ok = config.save()
        if ok:
            logger.info(f"已保存 {len(modules_list)} 个模块配置到 settings.json")
        else:
            logger.error("保存模块配置失败")
        return ok


# 模块级单例实例，供全局使用
task_library = TaskLibraryManager()
