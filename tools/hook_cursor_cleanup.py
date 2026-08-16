# -*- coding: utf-8 -*-
"""hook 残留清理工具（2026-08-16 闪退事件后保留）

背景：GetCursorPos IAT hook 方案对 Galaxy2D 4.2 不可行——galaxy2d.dll
的 GetCursorPos 是运行时 GetProcAddress 动态解析（磁盘导入表/延迟导入表
均无），内存扫描把 DATA 节普通指针误当 IAT 槽重定向导致游戏闪退。
本工具扫描所有游戏进程 galaxy2d.dll 的 GetCursorPos 指针槽，
把被改过的值恢复为该进程 user32!GetCursorPos 真实地址。

用法: python hook_cursor_cleanup.py
"""
import ctypes
import ctypes.wintypes as wt
import struct
import pefile

kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
psapi = ctypes.WinDLL('psapi', use_last_error=True)
PROCESS_ALL_ACCESS = 0x1F0FFF
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010

GALAXY_RVA = 0x184294   # galaxy2d.dll 中 GetCursorPos 指针槽的 RVA（DATA 节）


def find_game_pids():
    out = []
    for pid in range(0, 65536):
        h = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
        if not h:
            continue
        buf = ctypes.create_string_buffer(256)
        ok = psapi.GetModuleBaseNameA(h, None, buf, 256)
        if ok and b'\xca\xae\xc4\xea\xd2\xbb\xc3\xce' in buf.value:
            out.append(pid)
        kernel32.CloseHandle(h)
    return out


def find_module_base(pid, name_b):
    h = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not h:
        return None
    needed = wt.DWORD(0)
    psapi.EnumProcessModulesEx(h, None, 0, ctypes.byref(needed), 3)
    count = needed.value // ctypes.sizeof(wt.HMODULE)
    hmods = (wt.HMODULE * count)()
    psapi.EnumProcessModulesEx(h, hmods, needed.value, ctypes.byref(needed), 3)
    psapi.GetModuleBaseNameA.argtypes = [wt.HANDLE, wt.HMODULE, ctypes.c_char_p, wt.DWORD]
    base = None
    for i in range(count):
        b = ctypes.create_string_buffer(64)
        psapi.GetModuleBaseNameA(h, hmods[i], b, 64)
        if b.value.lower() == name_b:
            base = int(hmods[i]) & 0xFFFFFFFF
            break
    kernel32.CloseHandle(h)
    return base


def get_user32_gc(pid):
    """该进程内 user32!GetCursorPos 的真实地址"""
    u32 = find_module_base(pid, b'user32.dll')
    if not u32:
        return None
    try:
        pe = pefile.PE(r'C:/Windows/SysWOW64/user32.dll', fast_load=True)
        pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_EXPORT']])
        rva = None
        for exp in pe.DIRECTORY_ENTRY_EXPORT.symbols:
            if exp.name == b'GetCursorPos':
                rva = exp.address
                break
        pe.close()
        if rva is None:
            return None
        return (u32 + rva) & 0xFFFFFFFF
    except Exception:
        return None


def read32(h, addr):
    buf = ctypes.create_string_buffer(4)
    rd = ctypes.c_size_t(0)
    if kernel32.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, 4, ctypes.byref(rd)) and rd.value == 4:
        return struct.unpack('<I', buf.raw)[0]
    return None


def write32(h, addr, val):
    rd = ctypes.c_size_t(0)
    old = wt.DWORD()
    kernel32.VirtualProtectEx(h, ctypes.c_void_p(addr), 4, 0x04, ctypes.byref(old))
    ok = kernel32.WriteProcessMemory(h, ctypes.c_void_p(addr), struct.pack('<I', val), 4, ctypes.byref(rd))
    kernel32.VirtualProtectEx(h, ctypes.c_void_p(addr), 4, old.value, ctypes.byref(wt.DWORD()))
    return ok and rd.value == 4


def main():
    pids = find_game_pids()
    print('游戏进程 %d 个: %s' % (len(pids), pids))
    fixed = 0
    for pid in pids:
        h = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
        if not h:
            continue
        gbase = find_module_base(pid, b'galaxy2d.dll')
        if not gbase:
            kernel32.CloseHandle(h)
            continue
        slot = (gbase + GALAXY_RVA) & 0xFFFFFFFF
        cur = read32(h, slot)
        true = get_user32_gc(pid)
        if cur is None or true is None:
            kernel32.CloseHandle(h)
            continue
        if cur != true:
            if write32(h, slot, true):
                print('  [恢复] PID %d: 槽 0x%08X 值 0x%08X -> 0x%08X' % (pid, slot, cur, true))
                fixed += 1
            else:
                print('  [失败] PID %d: 写回 0x%08X 失败' % (pid, slot))
        kernel32.CloseHandle(h)
    print('恢复完成: %d 个进程被修正' % fixed)


if __name__ == '__main__':
    main()
