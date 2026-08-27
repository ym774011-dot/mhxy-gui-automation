# -*- coding: utf-8 -*-
"""监控游戏进程（比较用）CPU / 内存 / 句柄，判断"越跑越卡"的类型。

用途：
    卡顿出现在前台窗口（左上角）2784，后台窗口 17000 不卡。
    本脚本同时采样两个 PID，区分两种情况：
      1) 客户端内存泄漏 -> 内存/句柄随时间单调上涨（尤其 2784）
      2) 外部负载压渲染 -> 整体占用高但数值稳定，不随时间涨

用法（管理员运行更准，能读到句柄）：
    python monitor_lag.py 2784 17000 [时长秒=1800] [间隔秒=10]

输出：
    实时打印 dual-pid 采样 + 结束时两段时间趋势摘要。
"""
import sys
import time
import os
import ctypes
from ctypes import wintypes

# PROCESS_MEMORY_COUNTERS_EX 结构体（ctypes.wintypes 未内置）
class PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
        ("PrivateUsage", ctypes.c_size_t),
    ]

# ---- 采样进程指标工具（不依赖 psutil，纯 ctypes） ----
def _open_process(pid, access=0x1000 | 0x0400 | 0x0410):
    """PROCESS_QUERY_INFORMATION | PROCESS_VM_READ | PROCESS_QUERY_LIMITED."""
    import ctypes as c
    k32 = c.WinDLL('kernel32', use_last_error=True)
    h = k32.OpenProcess(access, False, pid)
    if not h:
        return None
    return h


def _read_mem_and_handle(h):
    """返回 (mem_kb, handle_count)，失败返回 (None, None)。"""
    k32 = ctypes.WinDLL('kernel32', use_last_error=True)
    psapi = ctypes.WinDLL('psapi', use_last_error=True)
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    psapi.GetProcessMemoryInfo.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(PROCESS_MEMORY_COUNTERS_EX),
        wintypes.DWORD,
    ]
    pmc = PROCESS_MEMORY_COUNTERS_EX()
    pmc.cb = ctypes.sizeof(pmc)
    if psapi.GetProcessMemoryInfo(ctypes.c_void_p(h), ctypes.byref(pmc), pmc.cb):
        mem_kb = pmc.WorkingSetSize // 1024
    else:
        mem_kb = None
    handle = wintypes.DWORD()
    if k32.GetProcessHandleCount(h, ctypes.byref(handle)):
        hcount = handle.value
    else:
        hcount = None
    return mem_kb, hcount


def _read_cpu(h):
    """返回 (cpu_percent, 自采样以来 kernel+user 时间增量/s)。"""
    k32 = ctypes.WinDLL('kernel32', use_last_error=True)
    ft_sys, ft_user = wintypes.FILETIME(), wintypes.FILETIME()
    if not k32.GetProcessTimes(h, ctypes.byref(ctypes.c_ulonglong(0)),
                               ctypes.byref(ctypes.c_ulonglong(0)),
                               ctypes.byref(ft_sys), ctypes.byref(ft_user)):
        return None
    return _filetime_to_100ns(ft_sys) + _filetime_to_100ns(ft_user)


def _filetime_to_100ns(ft):
    return (ft.dwHighDateTime << 32) | ft.dwLowDateTime


def cpu_delta(last_ticks, cur_ticks, seconds):
    """100ns 计数差分 -> 归一化为"1 秒用掉多少 CPU 秒"（>=1 表示满核）。"""
    if last_ticks is None or cur_ticks is None or seconds <= 0:
        return 0.0
    delta = max(0, cur_ticks - last_ticks)
    # 100ns -> 秒
    return delta / 1e7 / seconds


def get_metrics(pid):
    h = _open_process(pid)
    if not h:
        return None
    mem, hc = _read_mem_and_handle(h)
    cpu = _read_cpu(h)
    ctypes.WinDLL('kernel32', use_last_error=True).CloseHandle(h)
    return mem, hc, cpu


def main():
    if len(sys.argv) < 3:
        print("用法: python monitor_lag.py PID1 PID2 [时长秒=1800] [间隔秒=10]")
        return
    pid1 = int(sys.argv[1])
    pid2 = int(sys.argv[2])
    duration = float(sys.argv[3]) if len(sys.argv) > 3 else 1800.0
    interval = float(sys.argv[4]) if len(sys.argv) > 4 else 10.0

    print(f"监控 PID1={pid1}(前台2784)  PID2={pid2}(后台17000)")
    print(f"时长={duration:.0f}s  间隔={interval:.0f}s  Ctrl+C 提前结束\n")
    print(f"{'时间':<12}{'PID':>6} | {'CPU核':>6} {'内存MB':>9} {'句柄':>7}")
    print("-" * 52)

    fidx = {pid1: 0, pid2: 1}
    last_tick = {pid1: None, pid2: None}
    last_print = None
    start = time.time()

    while time.time() - start < duration:
        now = time.time()
        if last_print is not None and (now - last_print) < interval:
            time.sleep(0.2)
            continue
        last_print = now

        m = get_metrics(pid1)
        if m:
            mem, hc, cpu = m
            cpu_v = cpu_delta(last_tick[pid1], cpu, interval)
            last_tick[pid1] = cpu
            print(f"{time.asctime()[-8:]:<12}{pid1:>7} | {cpu_v:6.2f} {mem/1024.:>9.1f} "
                  f"{'?' if hc is None else hc:>7}")

        m = get_metrics(pid2)
        if m:
            mem, hc, cpu = m
            cpu_v = cpu_delta(last_tick[pid2], cpu, interval)
            last_tick[pid2] = cpu
            print(f"{'':<12}{pid2:>7} | {cpu_v:6.2f} {mem/1024.:>9.1f} "
                  f"{'?' if hc is None else hc:>7}")
        print("-" * 52)

    # 结束摘要：测两段内存，看是否上涨
    print("\n=== 结束采样：对比初始/结束内存（判断是否在泄漏） ===")
    for pid, name in ((pid1, "前台2784"), (pid2, "后台17000")):
        m = get_metrics(pid)
        if m:
            print(f"  {name} PID={pid}: 当前内存={m[0]/1024.:.1f} MB, "
                  f"句柄={m[1] if m[1] else '?'}")

    print("\n判断：内存/句柄随时间单调上涨 -> 客户端泄漏；"
          "数值平稳但卡 -> 外部负载(截图/OCR)压渲染。")


if __name__ == "__main__":
    main()