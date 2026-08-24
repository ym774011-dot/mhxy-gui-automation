# -*- coding: utf-8 -*-
"""C1 补测：captcha_link 验证码引擎联动（2026-08-24）。

- captcha_active()：状态文件存在+新鲜 → True；过期/不存在 → False
- wait_captcha_clear()：文件消失 → 返回 True；超时仍在 → False
状态文件路径在测试中替换为 tmp_path，不碰真实文件。
"""
import os
import time

import pytest

import core.captcha_link as cl


@pytest.fixture
def flag(tmp_path):
    """把状态文件路径指到临时目录。"""
    p = str(tmp_path / "captcha_active.txt")
    old = cl.CAPTCHA_FLAG
    cl.CAPTCHA_FLAG = p
    yield p
    cl.CAPTCHA_FLAG = old


def _touch(p, content="2026-08-24 21:00:00"):
    with open(p, "w", encoding="utf-8") as f:
        f.write(content)


class TestCaptchaActive:
    def test_no_file(self, flag):
        assert cl.captcha_active() is False

    def test_fresh_file(self, flag):
        _touch(flag)
        assert cl.captcha_active() is True

    def test_stale_file(self, flag):
        _touch(flag)
        # 把 mtime 改成超过 max_age 的旧时间
        old = time.time() - 60
        os.utime(flag, (old, old))
        assert cl.captcha_active() is False

    def test_removed_file(self, flag):
        _touch(flag)
        assert cl.captcha_active() is True
        os.remove(flag)
        assert cl.captcha_active() is False

    def test_max_age_param(self, flag):
        _touch(flag)
        # 文件 mtime 设成 1s 前，max_age=0.5 → 视为过期
        old = time.time() - 1.0
        os.utime(flag, (old, old))
        assert cl.captcha_active(max_age=0.5) is False


class TestWaitCaptchaClear:
    def test_not_active_immediately(self, flag):
        # 无标志文件 → 立即返回 True（未弹窗不阻塞）
        assert cl.wait_captcha_clear(timeout=3) is True

    def test_clears_after_removal(self, flag):
        _touch(flag)
        # 后台线程 0.5s 后删文件
        import threading

        def _del():
            time.sleep(0.5)
            os.remove(flag)

        threading.Thread(target=_del, daemon=True).start()
        assert cl.wait_captcha_clear(timeout=5) is True

    def test_timeout_still_active(self, flag):
        _touch(flag)
        # 文件一直存在 → 超时返回 False
        assert cl.wait_captcha_clear(timeout=1.0, poll=0.2) is False
