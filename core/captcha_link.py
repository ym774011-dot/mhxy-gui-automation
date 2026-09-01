# -*- coding: utf-8 -*-
"""验证码引擎联动（2026-08-24 用户确认"引擎联动暂停避让"）。

任务引擎运行中，验证码弹窗（客户端防挂机）出现时：
  - captcha_monitor（外部守护）检测到 4 红框 → 写状态文件 captcha_active.txt
  - 本模块供 TaskEngine 读取：验证码弹窗中 → 引擎暂停任务流（不点击，避免
    干扰验证码窗口/误点），等 captcha_monitor 自动解完（文件消失）→ 继续。

状态文件路径与 captcha_monitor 的 DEBUG_DIR 一致（mhxy-mcp-gateway）。
"""
import os
import time

# 验证码弹窗状态文件（captcha_monitor 写/删，本模块只读）
# ★2026-08-25 多组隔离：组 N 读 captcha_active_gN.txt（组1 无后缀兼容旧路径）。
#   组号从环境变量 MHXY_GROUP（main.py --group N 设置）。
_GROUP_ID = int(os.environ.get("MHXY_GROUP", "1") or "1")
CAPTCHA_FLAG = os.path.join(
    r"E:\DS\mhxy-mcp-gateway", "debug_captcha",
    f"captcha_active_g{_GROUP_ID}.txt" if _GROUP_ID > 1 else "captcha_active.txt")

# 文件新鲜度阈值（秒）：超过则视为陈旧标志（monitor 可能已退出/弹窗已超时消失），不阻塞任务
# ★2026-08-24 v3（用户关键约束）：验证码弹窗 60s 内未验证成功 → 游戏自动下线。
# 所以引擎等待窗口必须 ≤60s：60s 内 monitor 解完（删文件）→ 引擎恢复；
# 60s 未解完 → 游戏下线，继续等待无意义，75s/120s 只会白等。
# max_age=60s = 弹窗完整生存周期，之后一律判定陈旧恢复任务（网关自愈兜底）。
FLAG_MAX_AGE = 60.0


def captcha_active(max_age: float = FLAG_MAX_AGE) -> bool:
    """验证码是否弹窗中（状态文件存在且新鲜）。

    文件由 captcha_monitor 在检测到 4 红框时写入、红框消失时删除。
    文件存在但过期（mtime 超过 max_age）→ 视为陈旧，不阻塞（monitor 死了
    不能把任务永远卡住）。
    """
    try:
        if not os.path.exists(CAPTCHA_FLAG):
            return False
        return (time.time() - os.path.getmtime(CAPTCHA_FLAG)) < max_age
    except Exception:
        return False


def wait_captcha_clear(timeout: float = 120.0, poll: float = 0.5) -> bool:
    """等待验证码被解除（captcha_monitor 自动解完删文件）。

    轮询期间可被停止信号打断（应停止时返回 False）。
    :param timeout: 最长等待秒数（验证码倒计时 ~55s，默认 120 足够）
    :return: True=已解除（或未弹窗）；False=超时仍弹窗中
    """
    t0 = time.time()
    while time.time() - t0 < timeout:
        if not captcha_active():
            return True
        time.sleep(poll)
    return not captcha_active()


# ---------------------------------------------------------------------------
# 开机自启双保险（2026-08-25 用户要求"检查开机自启，没自启就脚本拉起，闭环"）
# ---------------------------------------------------------------------------
GATEWAY_DIR = r"E:\DS\mhxy-mcp-gateway"
WATCHDOG_PY = os.path.join(GATEWAY_DIR, "captcha_watchdog.py")
PYW = r"E:\py\pythonw.exe"


def watchdog_running(group: int = None) -> bool:
    """当前组（或任意组）的 captcha_watchdog 是否在运行。

    :param group: 组号；None = 当前组（MHXY_GROUP）。组1 watchdog 可能
        不带 --group 参数（默认 1），组 N>1 必须带 --group N。
    """
    if group is None:
        try:
            from core.group_config import current_group
            group = current_group()
        except Exception:
            group = 1
    try:
        import psutil
    except Exception:
        return False
    for p in psutil.process_iter(["pid", "cmdline"]):
        try:
            cmd = " ".join(p.info["cmdline"] or [])
        except Exception:
            continue
        if "captcha_watchdog" not in cmd:
            continue
        if group <= 1:
            # 组1：不带 --group 或 --group 1 都算
            if "--group" not in cmd or "--group 1" in cmd:
                return True
        else:
            if f"--group {group}" in cmd:
                return True
    return False


def ensure_watchdog(group: int = None) -> tuple:
    """检查 watchdog 是否运行，没运行则拉起（幂等）。

    :return: (ok, info) — ok=True 表示 watchdog 在运行（含本次拉起成功）
    """
    # ★2026-08-31 00:22 永久禁用（用户定案）：多窗口自动化下 captcha watchdog+
    #   monitor 会绑错窗口高频 PostMessage/ESC/截图，实证为引擎异常退出干扰源
    #   （崩溃前 monitor 持续对错误窗口发消息）。farm 内置 _captcha_solve V7 直解
    #   已自足，无需独立 monitor。置 MHXY_NO_WATCHDOG=1 跳过拉起；默认仍保持
    #   原行为（不强制改变其他使用者的场景）。
    if os.environ.get("MHXY_NO_WATCHDOG") == "1":
        return True, "watchdog 已禁用（MHXY_NO_WATCHDOG=1）"
    if watchdog_running(group):
        return True, "watchdog 已在运行"
    if group is None:
        try:
            from core.group_config import current_group
            group = current_group()
        except Exception:
            group = 1
    try:
        import subprocess
        args = [PYW, WATCHDOG_PY, "--group", str(group)]
        subprocess.Popen(args, cwd=GATEWAY_DIR,
                         creationflags=getattr(subprocess, "DETACHED_PROCESS", 0)
                         or 0x08000000)
        return True, f"watchdog 未运行，已拉起 (group={group})"
    except Exception as e:
        return False, f"watchdog 拉起失败: {e}"


if __name__ == "__main__":
    import sys
    print("captcha_active:", captcha_active())
    if "--ensure" in sys.argv:
        ok, info = ensure_watchdog()
        print("ensure_watchdog:", ok, info)
    if "--wait" in sys.argv:
        ok = wait_captcha_clear(timeout=60)
        print("wait_captcha_clear:", ok)
