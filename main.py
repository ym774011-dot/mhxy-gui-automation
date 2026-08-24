# -*- coding: utf-8 -*-
"""
MHXY GUI 自动化脚本平台 - 主入口。

启动 PyQt5 应用并显示主窗口。
"""
import sys
import os

# 确保项目根目录在 sys.path 中，保证包内导入可用
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _preload_vcruntime():
    """修复 torch/easyocr 的 c10.dll [WinError 1114] DLL 加载失败。

    根因（2026-08-05 10:10 实测，10:23 精确复现）：
      - **真正的冲突是 PyQt5 + cv2(OpenCV) 先加载了各自版本的 MSVC 运行库，
        之后 torch 加载 c10.dll 时依赖的 VC 运行库符号与已加载的冲突
        → c10.dll DllMain 初始化失败 [WinError 1114]**；
      - 单独 import torch 永远 OK，但 `PyQt5 → cv2 → torch` 同进程必失败；
      - C:\\Windows\\System32 的 VC 运行库是 14.50（最新）。

    修复原理：在导入任何包之前，用 ctypes 显式预加载 System32 的**最新版**
    MSVC 运行库（vcruntime140 / vcruntime140_1 / msvcp140 / msvcp140_1）。
    Windows 按模块名去重——进程已加载正确版本后，PyQt5/cv2/torch 请求同名
    DLL 都会复用已加载模块，不再各加载各的版本 → 消除符号冲突。

    若此方案仍失效（个别机器 PyQt5 强制加载自带 DLL），备选：
      把 System32 版复制覆盖 E:\\py 下的旧版（备份为 vcruntime140.dll.bak_1442）。
    """
    try:
        import ctypes
        _sys32 = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")
        for _dll in ("vcruntime140.dll", "vcruntime140_1.dll",
                     "msvcp140.dll", "msvcp140_1.dll"):
            _p = os.path.join(_sys32, _dll)
            if os.path.exists(_p):
                ctypes.WinDLL(_p)
    except Exception:
        # 预加载失败不阻断启动（torch 可用则用，不可用走降级路径）
        pass


# 在任何 PyQt5/torch/easyocr/ultralytics/cv2 导入前预加载正确版本 MSVC 运行库
# （必须放在最前面——PyQt5 先加载会引入冲突版本）
_preload_vcruntime()

from PyQt5.QtWidgets import QApplication


def main():
    """程序入口：创建 QApplication 并显示主窗口。"""
    # 多组参数: python main.py --group N
    import argparse
    ap = argparse.ArgumentParser(description="MHXY GUI 自动化脚本平台")
    ap.add_argument("--group", type=int, default=1, help="组号（1/2/3/4），默认 1")
    args, _ = ap.parse_known_args()
    os.environ["MHXY_GROUP"] = str(args.group)

    # 日志自动清理（启动时一次性执行，按 settings.json 的 auto_clean_days）
    try:
        from config.config import config
        from utils.logger import cleanup_old_logs
        log_path = config.get("logging.file_path", "logs/automation.log")
        days = int(config.get("logging.auto_clean_days", 7) or 0)
        if days > 0:
            removed = cleanup_old_logs(log_path, days)
            if removed:
                print(f"[main] 已清理 {removed} 个过期日志文件（>{days}天）")
    except Exception as e:
        # 清理失败不阻断启动
        print(f"[main] 日志清理异常（不影响启动）: {e}")

    app = QApplication(sys.argv)

    # 延迟导入主窗口，避免循环依赖并加快启动
    from gui.main_window import MainWindow

    window = MainWindow()
    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
