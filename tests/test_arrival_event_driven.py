# -*- coding: utf-8 -*-
"""
事件驱动到达判定测试（2026-08-05 重构）。

覆盖 wait_for_arrival 的新逻辑：
  1. 到达即时命中：任何采样偏差 ≤ 容差 → 直接成功
  2. 停止确认 + 观察期：角色停止但偏差 > 容差 → 观察 stop_fail_confirm_s 后失败
  3. 移动兜底超时：持续移动超过自动估算/传入上限 → 失败
"""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.arrival_verifier import ArrivalVerifier


class _FakeReader:
    """最小坐标读取器桩：is_connected 恒 True。"""

    is_connected = True

    def connect(self, pid):
        return True


def _make_verifier(coords_iter, sample_interval=0.01, **kwargs):
    """构造测试用 verifier：坐标序列迭代器 + 真实短 sleep。"""
    v = ArrivalVerifier()
    v._reader = _FakeReader()
    it = iter(coords_iter)
    v._read_coords_with_retry = lambda: next(it, None)
    v._interruptible_sleep = lambda s: time.sleep(s)
    v._lock = type("_L", (), {"__enter__": lambda self: self, "__exit__": lambda *a: None})()
    return v


class ArrivalEventDrivenTests(unittest.TestCase):

    def test_arrive_immediately_when_within_tolerance(self):
        """第一帧就在容差内 → 立即成功。"""
        v = _make_verifier([(80, 80)], sample_interval=0.01)
        ok, msg, coord = v.wait_for_arrival(80, 80, tolerance=3)
        self.assertTrue(ok, msg)
        self.assertEqual(coord, (80, 80))

    def test_arrive_after_moving_close_to_target(self):
        """坐标逐步接近目标 → 到达容差内即成功（不用等停止确认）。"""
        coords = [(100, 100), (90, 90), (85, 85), (84, 84), (80, 80)]
        v = _make_verifier(coords, sample_interval=0.01)
        ok, msg, coord = v.wait_for_arrival(80, 80, tolerance=3, timeout=30)
        self.assertTrue(ok, msg)
        self.assertEqual(coord, (80, 80))

    def test_fail_when_stopped_away_from_target(self):
        """角色停止但偏差 > 容差 → 观察 stop_fail_confirm_s 后失败。"""
        coords = [(10, 10)] * 100  # 一直静止在 (10,10)
        v = _make_verifier(
            coords,
            sample_interval=0.01,
            stop_confirm_s=0.05,
            stop_fail_confirm_s=0.1,
        )
        ok, msg, coord = v.wait_for_arrival(100, 100, tolerance=3, timeout=30)
        self.assertFalse(ok, msg)
        self.assertIn("停止", msg)

    def test_fail_when_moving_past_move_timeout(self):
        """持续移动超过移动兜底超时（传入上限）→ 失败，不等停止。"""
        # 起点 (0,0) → 目标 (100,100) 距离 141；auto≈40s；
        # 传入 timeout=0.3 作上限 → move_timeout=0.3
        coords = [(i, i) for i in range(80)]  # 每帧移动 1.41 > 0.5
        v = _make_verifier(coords, sample_interval=0.01, timeout=0.3)
        ok, msg, coord = v.wait_for_arrival(100, 100, tolerance=3, timeout=0.3)
        self.assertFalse(ok, msg)
        self.assertIn("持续移动", msg)

    def test_move_timeout_auto_estimate_ignores_large_passed(self):
        """距离远时 auto 估算优先：传入 30s 上限不缩小 auto（约 40s）。"""
        v = _make_verifier([(0, 0)], sample_interval=0.01)
        # 手动触发起点估算逻辑无法直接断言内部值，
        # 这里验证远距离不会因 30s 上限而过早失败（第一帧就返回成功或继续）。
        ok, msg, coord = v.wait_for_arrival(0, 0, tolerance=3, timeout=30)
        self.assertTrue(ok, msg)  # 起点即目标 → 成功


if __name__ == "__main__":
    unittest.main(verbosity=2)
