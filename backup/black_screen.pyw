# -*- coding: utf-8 -*-
"""全黑屏工具（等效物理关屏，但 GPU 会话不断）——整夜挂机用

原理：物理关显示器 = 电源断 = GPU 丢显示设备 = 全屏游戏崩。
本工具开一个全黑的无边框窗口盖满屏幕（黑屏效果），但 Windows/GDI
渲染会话保持，NVIDIA 显卡不感知设备移除，游戏后台照跑。

用法：
  - 双击运行 → 屏幕全黑（等效关屏）
  - 按 Esc 退出恢复
  - 需要看游戏画面时按 Alt+Tab 切出（黑窗口在最顶）→ 或直接 Esc 退出

注意：
  - 不影响 farm 的 PostMessage 后台操作（我们全程后台鼠标键盘）
  - 若 farm 崩溃需要人工介入，Esc 退出黑屏即可看到游戏
"""
import tkinter as tk
import sys

root = tk.Tk()
# 注意：overrideredirect 与 -fullscreen 互斥（同时设置会抛
# "can't set fullscreen attribute: override-redirect flag is set"）。
# fullscreen 本身已无边框无标题栏，直接用 -fullscreen + -topmost。
root.attributes("-topmost", True)     # 置顶
root.attributes("-fullscreen", True)  # 全屏（含无边框效果）
root.configure(bg="#000000")
# 隐藏鼠标光标（黑屏更彻底）
try:
    root.config(cursor="none")
except Exception:
    pass


def _on_key(event):
    if event.keysym == "Escape":
        root.destroy()


root.bind("<Key>", _on_key)
root.focus_force()
print("全黑屏已启动（等效关屏，GPU 会话保持）。按 Esc 退出。", flush=True)
root.mainloop()