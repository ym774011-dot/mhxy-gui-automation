# -*- coding: utf-8 -*-
# GetCursorPos hook 客户端：写伪造坐标（供 input_controller._sync_cursor 使用）
# 流程：读共享内存 MHXY_CURSOR_HOOK 拿目标进程数据区地址 → OpenProcess →
#       WriteProcessMemory 写 flag=1,fx,fy → 游戏 GetCursorPos 读到伪造坐标。
# 不依赖 hook 时（未注入）安全返回 False，调用方回退 SetCursorPos。
import ctypes
import ctypes.wintypes as wt
import struct

kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
PROCESS_ALL_ACCESS = 0x1F0FFF
SHM_NAME = 'MHXY_CURSOR_HOOK'
SHM_SIZE = 64

_known_addr = None      # 缓存数据区地址
_known_pid = None
_h = None               # 目标进程句柄（缓存）


def _shm_read_addr():
    """读共享内存里的数据区地址（0=未注入）"""
    global _known_addr
    try:
        kernel32.OpenFileMappingW.restype = ctypes.c_void_p
        kernel32.OpenFileMappingW.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_wchar_p]
        kernel32.MapViewOfFile.restype = ctypes.c_void_p
        kernel32.MapViewOfFile.argtypes = [
            ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_size_t]
        h = kernel32.OpenFileMappingW(0x0002, False, SHM_NAME)
        if not h:
            _known_addr = 0
            return 0
        p = kernel32.MapViewOfFile(h, 0x0006, 0, 0, SHM_SIZE)
        if not p:
            kernel32.CloseHandle(h)
            _known_addr = 0
            return 0
        addr = struct.unpack('<I', ctypes.string_at(p, 4))[0]
        kernel32.UnmapViewOfFile(p)
        kernel32.CloseHandle(h)
        _known_addr = addr
        return addr
    except Exception:
        _known_addr = 0
        return 0


def is_hooked(pid=None) -> bool:
    """hook 是否已注入（共享内存里有数据区地址）"""
    addr = _shm_read_addr()
    return addr != 0


def _ensure_handle(pid):
    global _known_pid, _h
    if _h and _known_pid == pid:
        return _h
    if _h:
        kernel32.CloseHandle(_h)
        _h = None
    h = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
    if h:
        _h = h
        _known_pid = pid
    return h


def set_cursor(pid, px, py):
    """写伪造坐标（flag=1, fx, fy）。返回 True=已伪造，False=未注入/失败。"""
    addr = _shm_read_addr()
    if not addr:
        return False
    h = _ensure_handle(pid)
    if not h:
        return False
    try:
        # flag=1, fx, fy（12 字节）
        data = struct.pack('<Iii', 1, int(px), int(py))
        rd = ctypes.c_size_t(0)
        ok = kernel32.WriteProcessMemory(h, ctypes.c_void_p(addr), data, len(data), ctypes.byref(rd))
        return bool(ok and rd.value == len(data))
    except Exception:
        return False


def clear(pid):
    """清空伪造（flag=0 → 游戏读真实光标）。返回 True=已清空。"""
    addr = _shm_read_addr()
    if not addr:
        return False
    h = _ensure_handle(pid)
    if not h:
        return False
    try:
        data = struct.pack('<Iii', 0, 0, 0)
        rd = ctypes.c_size_t(0)
        ok = kernel32.WriteProcessMemory(h, ctypes.c_void_p(addr), data, len(data), ctypes.byref(rd))
        return bool(ok and rd.value == len(data))
    except Exception:
        return False


def close():
    global _h
    if _h:
        kernel32.CloseHandle(_h)
        _h = None
