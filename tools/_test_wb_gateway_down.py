# -*- coding: utf-8 -*-
"""_http_json 网关失联挂起自愈 离线回归（2026-08-28 10061 三连炸修复）。

场景复现：23:16-23:35 游戏 attach 被拒 → 网关 spawn 即退 → 18082 持续
10061；旧逻辑 heal 失败后试一次就 raise，farm 事件被炸掉三次。
新逻辑：挂起等待自愈，恢复后无缝续跑；超时/用户停止/非失联错误才抛出。

运行：E:/py/python.exe tools/_test_wb_gateway_down.py
"""
import json
import sys, os
import urllib.error as ue
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tasks.library.WORLD_BOSS as WB


def _refused():
    return ue.URLError(ConnectionRefusedError(10061, "由于目标计算机积极拒绝，无法连接。"))


class _Resp:
    """模拟 urlopen 返回的上下文管理器响应。"""
    def __init__(self, payload):
        self._p = json.dumps(payload).encode("utf-8")
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False
    def read(self):
        return self._p


fails = 0

def check(name, cond, detail=""):
    global fails
    ok = bool(cond)
    if not ok:
        fails += 1
    print(f"  {'PASS' if ok else 'FAIL'}  {name}  {detail}")


# --- 用例1：失联两次后网关恢复 → 返回结果，期间调用过自愈 ---
with mock.patch.object(WB, "_urlopen",
                       side_effect=[_refused(), _refused(), _Resp({"ok": 1})]) as m_open, \
     mock.patch.object(WB, "_heal_gateway", return_value=True) as m_heal, \
     mock.patch.object(WB, "_gui_stop_requested", return_value=False), \
     mock.patch.object(WB, "GATEWAY_DOWN_POLL_S", 0.01), \
     mock.patch.object(WB, "GATEWAY_DOWN_MAX_WAIT_S", 30.0):
    r = WB._http_json("http://127.0.0.1:18082", "/api/lua", {"code": "x"})
    check("失联后恢复→返回结果", r == {"ok": 1})
    check("失联期间自愈被调用", m_heal.called)
    check("共请求3次(1失败+1失败+1成功)", m_open.call_count == 3,
          f"call_count={m_open.call_count}")

# --- 用例2：持续失联超过挂起上限 → 抛出最后一次异常 ---
with mock.patch.object(WB, "_urlopen", side_effect=_refused()) as m_open, \
     mock.patch.object(WB, "_heal_gateway", return_value=False), \
     mock.patch.object(WB, "_gui_stop_requested", return_value=False), \
     mock.patch.object(WB, "GATEWAY_DOWN_POLL_S", 0.01), \
     mock.patch.object(WB, "GATEWAY_DOWN_MAX_WAIT_S", 0.05):
    try:
        WB._http_json("http://127.0.0.1:18082", "/api/lua", {"code": "x"})
        check("挂起超时→抛出", False, "未抛出")
    except ue.URLError:
        check("挂起超时→抛出", True)
    check("超时路径反复探测", m_open.call_count >= 2, f"call_count={m_open.call_count}")

# --- 用例3：非失联错误（如超时）→ 立即抛出，不自愈不挂起 ---
with mock.patch.object(WB, "_urlopen",
                       side_effect=ue.URLError(OSError("timed out"))) as m_open, \
     mock.patch.object(WB, "_heal_gateway", return_value=True) as m_heal, \
     mock.patch.object(WB, "GATEWAY_DOWN_POLL_S", 0.01):
    try:
        WB._http_json("http://127.0.0.1:18082", "/api/lua", {"code": "x"})
        check("非失联错误→照旧抛出", False, "未抛出")
    except ue.URLError:
        check("非失联错误→照旧抛出", True)
    check("非失联错误不自愈", not m_heal.called)
    check("非失联错误只请求1次", m_open.call_count == 1)

# --- 用例4：用户点停止 → 立即抛出，不再挂起 ---
with mock.patch.object(WB, "_urlopen", side_effect=_refused()) as m_open, \
     mock.patch.object(WB, "_heal_gateway", return_value=True), \
     mock.patch.object(WB, "_gui_stop_requested", return_value=True), \
     mock.patch.object(WB, "GATEWAY_DOWN_POLL_S", 0.01), \
     mock.patch.object(WB, "GATEWAY_DOWN_MAX_WAIT_S", 30.0):
    try:
        WB._http_json("http://127.0.0.1:18082", "/api/lua", {"code": "x"})
        check("用户停止→抛出", False, "未抛出")
    except ue.URLError:
        check("用户停止→抛出", True)

print(f"\n=== {'ALL PASS' if fails == 0 else f'{fails} FAIL'} ===")
sys.exit(0 if fails == 0 else 1)
