# -*- coding: utf-8 -*-
"""任务引擎即时中断基础设施（2026-08-28）。

问题：GUI 停止按钮原先只在事件边界生效，单个函数事件内部的长循环
（地图包走路/等待，动辄数十秒 time.sleep）无法及时打断。

方案：协作式 + 兜底式两层中断：
1. **线程感知的可中断 sleep**（协作层）：install() 把 time.sleep 替换为
   线程感知版本——只有"注册过的工作线程"（引擎 worker）睡眠时按 0.05s
   分片并轮询 should_stop，命中即抛 TaskInterrupted；其他线程走原
   sleep 快速路径，零影响。pack 全部用 `time.sleep` 属性调用（无
   `from time import` 绑定），模块级补丁对其天然生效。
2. **异步异常注入**（兜底层）：stop() 后 worker 若 1s 仍未退出（卡在
   纯 Python 长循环 / 非 sleep 路径），用 PyThreadState_SetAsyncExc 向
   worker 注入 TaskInterrupted，在下一个字节码边界打断。

关键设计：TaskInterrupted 继承 BaseException 而非 Exception——
pack / task_library.call_function 里的 `except Exception` 不会吞掉它，
异常可一路穿透到 _run_sequence 的显式捕获点。

限制（已知边界）：正在进行的 C 级阻塞调用（socket recv / PostMessage）
无法被异步异常打断，最坏延迟 = 当前一次阻塞调用的超时（pack 内
HTTP 调用超时 ≤10s）。
"""
import threading
import time

# 全局补丁只装一次
_patched = False
_orig_sleep = None
_patch_lock = threading.Lock()

# 线程 ident -> should_stop 探针（返回 True=请求停止）
_stop_checkers: dict = {}


class TaskInterrupted(BaseException):
    """停止请求触发的即时中断（继承 BaseException，避免被 except Exception 吞掉）。"""


def register_worker(thread: threading.Thread, checker) -> None:
    """注册工作线程及其停止探针（checker 返回 True 表示请求停止）。"""
    if thread.ident is not None:
        _stop_checkers[thread.ident] = checker


def unregister_worker(thread: threading.Thread) -> None:
    """工作线程退出时注销（ident 可能被系统复用，必须清理）。"""
    _stop_checkers.pop(thread.ident, None)


def install() -> None:
    """安装线程感知 time.sleep 补丁（幂等，进程级一次）。"""
    global _patched, _orig_sleep
    with _patch_lock:
        if _patched:
            return
        _orig_sleep = time.sleep

        def _sleep(seconds):
            # 未注册线程 / 极短睡眠：原速直通（零额外开销路径）
            checker = _stop_checkers.get(threading.get_ident())
            if checker is None or seconds <= 0.06:
                return _orig_sleep(seconds)
            # 工作线程：0.05s 分片睡眠，停止请求立即中断
            deadline = time.time() + seconds
            while True:
                if checker():
                    raise TaskInterrupted("收到停止请求（睡眠中即时中断）")
                remaining = deadline - time.time()
                if remaining <= 0:
                    return
                _orig_sleep(min(0.05, remaining))

        time.sleep = _sleep
        _patched = True


def inject_exception(thread_ident: int, exc: BaseException) -> int:
    """向目标线程注入异步异常（在下一个字节码边界抛出）。

    返回 PyThreadState_SetAsyncExc 结果：1=已排队，0=线程不存在，
    >1=异常（立即清理）。对阻塞在 C 调用中的线程无效（等调用返回后才抛）。
    """
    import ctypes
    res = ctypes.pythonapi.PyThreadState_SetAsyncExc(
        ctypes.c_long(thread_ident), ctypes.py_object(exc))
    if res > 1:
        # 异常状态：清掉刚注入的，避免线程卡在未知状态
        ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_long(thread_ident), None)
    return res
