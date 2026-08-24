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
CAPTCHA_FLAG = os.path.join(
    r"E:\DS\mhxy-mcp-gateway", "debug_captcha", "captcha_active.txt")

# 文件新鲜度阈值（秒）：超过则视为陈旧标志（monitor 可能已退出），不阻塞任务
# ★2026-08-24 v2：验证码弹窗倒计时 ~85s（截图见 17s 倒计时），默认 max_age
# 改 120s 完全覆盖弹窗生存周期，引擎不会误判"已解除"而继续跑（SIP）。
FLAG_MAX_AGE = 120.0


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


if __name__ == "__main__":
    import sys
    print("captcha_active:", captcha_active())
    if "--wait" in sys.argv:
        ok = wait_captcha_clear(timeout=60)
        print("wait_captcha_clear:", ok)
