# -*- coding: utf-8 -*-
"""扫描游戏模块导出表找输入 API + 验证 user32 入口字节"""
import ctypes
import ctypes.wintypes as wt
import os
import pefile

k32 = ctypes.WinDLL('kernel32', use_last_error=True)
psapi = ctypes.WinDLL('psapi', use_last_error=True)
PID = 2116


def find_module_base(pid, name_b):
    h = k32.OpenProcess(0x1F0FFF, False, pid)
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
        buf = ctypes.create_string_buffer(64)
        psapi.GetModuleBaseNameA(h, hmods[i], buf, 64)
        if buf.value.lower() == name_b:
            base = int(hmods[i]) & 0xFFFFFFFF
            break
    k32.CloseHandle(h)
    return base


def export_rva(dll_path, fn):
    pe = pefile.PE(dll_path, fast_load=True)
    pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_EXPORT']])
    for e in getattr(pe, 'DIRECTORY_ENTRY_EXPORT', None).symbols:
        if e.name == fn.encode():
            pe.close()
            return e.address
    pe.close()
    return None


def main():
    h = k32.OpenProcess(0x1F0FFF, False, PID)
    u32 = find_module_base(PID, b'user32.dll')
    print(f'user32 base=0x{u32:08X}')
    for fn in ['GetAsyncKeyState', 'GetKeyState', 'GetKeyboardState', 'PeekMessageA', 'SendInput']:
        rva = export_rva(os.path.join(os.environ.get('WINDIR', r'C:/Windows'), 'SysWOW64', 'user32.dll'), fn)
        if rva is None:
            print(f'  {fn}: RVA 未找到')
            continue
        addr = (u32 + rva) & 0xFFFFFFFF
        buf = ctypes.create_string_buffer(8)
        r = ctypes.c_size_t(0)
        k32.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, 8, ctypes.byref(r))
        print(f'  user32!{fn:20s} @0x{addr:08X} 入口: {buf.raw[:6].hex(" ")}')
    k32.CloseHandle(h)

    print()
    print('=== galaxy2d.dll 导出表（输入相关）===')
    pe = pefile.PE(r'G:/00/Galaxy2d.dll', fast_load=True)
    pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_EXPORT']])
    syms = getattr(pe, 'DIRECTORY_ENTRY_EXPORT', None)
    if syms:
        total = len(syms.symbols)
        print(f'  共 {total} 个导出')
        for e in syms.symbols:
            if e.name:
                n = e.name.decode('latin1')
                ln = n.lower()
                if any(k in ln for k in ['key', 'input', 'mouse', 'press', 'click', 'hot', 'button', 'getmsg', 'wnd', 'window', 'focus', 'active']):
                    print(f'  0x{e.address:06X}  {n}')
    pe.close()


if __name__ == '__main__':
    main()
