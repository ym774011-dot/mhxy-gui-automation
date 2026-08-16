# -*- coding: utf-8 -*-
"""梦幻西游私服 主线程逆向工具

定位 PID 进程的主线程处理函数（主循环帧处理函数）：
1. 枚举所有线程（Toolhelp32）+ NtQueryInformationThread(9) 拿每个线程起始地址
2. 筛选落在 exe 代码段内的线程（游戏自有线程，排除系统/库线程）
3. 反汇编线程入口，追踪主循环，找每帧调用的候选函数

用法: E:/py/python.exe tools/find_main_thread.py PID [--disasm]
"""
import ctypes
import ctypes.wintypes as wt
import sys
import os

from capstone import Cs, CS_ARCH_X86, CS_MODE_32

kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
ntdll = ctypes.WinDLL('ntdll', use_last_error=True)
psapi = ctypes.WinDLL('psapi', use_last_error=True)

TH32CS_SNAPTHREAD = 0x00000004
THREAD_QUERY_INFORMATION = 0x0040
ThreadQuerySetWin32StartAddress = 9
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010


class THREADENTRY32(ctypes.Structure):
    _fields_ = [
        ('dwSize', wt.DWORD),
        ('cntUsage', wt.DWORD),
        ('th32ThreadID', wt.DWORD),
        ('th32OwnerProcessID', wt.DWORD),
        ('tpBasePri', ctypes.c_long),
        ('tpDeltaPri', ctypes.c_long),
        ('dwFlags', wt.DWORD),
    ]


def enum_threads(pid):
    """枚举进程所有线程，返回 [(tid, owner_pid)]"""
    threads = []
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
    if snap == ctypes.c_void_p(-1).value or not snap:
        print(f"[err] CreateToolhelp32Snapshot: {ctypes.get_last_error()}")
        return threads
    te = THREADENTRY32()
    te.dwSize = ctypes.sizeof(THREADENTRY32)
    if kernel32.Thread32First(snap, ctypes.byref(te)):
        while True:
            if te.th32OwnerProcessID == pid:
                threads.append((te.th32ThreadID, te.th32OwnerProcessID))
            if not kernel32.Thread32Next(snap, ctypes.byref(te)):
                break
    kernel32.CloseHandle(snap)
    return threads


def thread_start_address(tid):
    """NtQueryInformationThread(ThreadQuerySetWin32StartAddress=9) 返回线程起始地址"""
    h = kernel32.OpenThread(THREAD_QUERY_INFORMATION, False, tid)
    if not h:
        return 0
    buf = ctypes.c_void_p(0)
    ret = ctypes.c_ulong(0)
    status = ntdll.NtQueryInformationThread(
        h, ThreadQuerySetWin32StartAddress,
        ctypes.byref(buf), ctypes.sizeof(buf), ctypes.byref(ret))
    kernel32.CloseHandle(h)
    if status != 0:
        return 0
    return buf.value or 0


def get_modules(pid):
    """枚举进程模块，返回 [(base, size, name, entry)]（用 pymem）"""
    import pymem
    try:
        pm = pymem.Pymem()
        pm.open_process_from_id(pid)
        mods = []
        for m in pm.list_modules():
            mods.append((m.lpBaseOfDll, m.SizeOfImage, m.name, 0))
        return mods
    except Exception as e:
        print(f"[err] pymem 模块枚举: {e}")
        # 兜底：手动 OpenProcess + EnumProcessModulesEx
        h = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
        if not h:
            return []
        needed = wt.DWORD(0)
        psapi.EnumProcessModulesEx(h, None, 0, ctypes.byref(needed), 3)
        count = needed.value // ctypes.sizeof(wt.HMODULE)
        hmods = (wt.HMODULE * count)()
        psapi.EnumProcessModulesEx(h, hmods, needed.value, ctypes.byref(needed), 3)

        class MODULEINFO(ctypes.Structure):
            _fields_ = [('lpBaseOfDll', ctypes.c_void_p),
                        ('SizeOfImage', wt.DWORD),
                        ('EntryPoint', ctypes.c_void_p)]

        psapi.GetModuleInformation.argtypes = [wt.HANDLE, wt.HMODULE,
                                               ctypes.POINTER(MODULEINFO), wt.DWORD]
        psapi.GetModuleBaseNameW.argtypes = [wt.HANDLE, wt.HMODULE, wt.LPWSTR, wt.DWORD]
        mods = []
        for i in range(count):
            mi = MODULEINFO()
            psapi.GetModuleInformation(h, hmods[i], ctypes.byref(mi), ctypes.sizeof(mi))
            name = ctypes.create_unicode_buffer(260)
            psapi.GetModuleBaseNameW(h, hmods[i], name, 260)
            mods.append((mi.lpBaseOfDll, mi.SizeOfImage, name.value, mi.EntryPoint))
        kernel32.CloseHandle(h)
        return mods


def read_mem(pid, addr, size):
    """读进程内存"""
    h = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not h:
        return b''
    buf = ctypes.create_string_buffer(size)
    read = ctypes.c_size_t(0)
    ok = kernel32.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, size, ctypes.byref(read))
    kernel32.CloseHandle(h)
    return buf.raw[:read.value] if ok else b''


def disasm(data, base, max_insn=60):
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    md.detail = False
    out = []
    for insn in md.disasm(data, base):
        out.append(f"  0x{insn.address:08X}  {insn.bytes.hex():<20} {insn.mnemonic} {insn.op_str}")
        if len(out) >= max_insn:
            out.append("  ... (截断)")
            break
        if insn.mnemonic in ('ret', 'retn') and len(out) > 5:
            break
    return out


def main():
    pid = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    do_disasm = '--disasm' in sys.argv
    if not pid:
        print("用法: python find_main_thread.py PID [--disasm]")
        return

    print(f"=== 进程 {pid} 线程枚举 ===")
    threads = enum_threads(pid)
    print(f"线程总数: {len(threads)}")

    mods = get_modules(pid)
    exe_mods = [m for m in mods if m[2].lower().endswith('.exe')]
    print(f"\n模块总数: {len(mods)}，exe 模块:")
    for base, size, name, entry in exe_mods:
        print(f"  {name}: base=0x{base:X} size=0x{size:X} entry=0x{entry:X}")
    if not exe_mods:
        exe_mods = mods[:1]

    print(f"\n=== 线程起始地址分析 ===")
    results = []
    for tid, _ in threads:
        start = thread_start_address(tid)
        # 判断起始地址属于哪个模块
        owner = '?'
        offset = 0
        for base, size, name, _ in exe_mods + mods:
            if base <= start < base + size:
                owner = name
                offset = start - base
                break
        results.append((tid, start, owner, offset))
        print(f"  TID={tid:<6} start=0x{start:08X} 模块={owner} 偏移=0x{offset:X}" if start else f"  TID={tid:<6} start=读取失败")

    # 游戏自有线程（起始地址在 exe 模块内）
    print(f"\n=== 游戏自有线程（exe 模块内）===")
    own = [r for r in results if r[2] and r[2].lower().endswith('.exe')]
    for tid, start, owner, offset in own:
        print(f"  TID={tid:<6} start=0x{start:08X} 偏移=0x{offset:X}")

    # 主线程候选：exe 模块内的线程
    if not own:
        print("  未找到 exe 模块内线程，可能主线程在其它模块启动")
        return

    # 反汇编主线程候选入口
    if do_disasm:
        for tid, start, owner, offset in own[:3]:
            print(f"\n=== 反汇编 TID={tid} 入口 (0x{start:08X}, {owner} 偏移 0x{offset:X}) ===")
            data = read_mem(pid, start, 200)
            if not data:
                print("  读取失败")
                continue
            for line in disasm(data, start):
                print(line)


if __name__ == '__main__':
    main()
