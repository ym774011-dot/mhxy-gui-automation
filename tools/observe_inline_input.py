# -*- coding: utf-8 -*-
"""inline hook user32 输入函数入口，观测游戏是否动态调用（GetProcAddress 不在 IAT）。

hook GetAsyncKeyState / GetKeyState / GetKeyboardState 三个函数入口，
计数调用次数后跳回原函数（零干扰）。5 秒后自动恢复。

用法: python observe_inline_input.py 2116
"""
import ctypes
import ctypes.wintypes as wt
import struct
import sys
import time
import os

import pefile

kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
psapi = ctypes.WinDLL('psapi', use_last_error=True)

PROCESS_ALL_ACCESS = 0x1F0FFF
MEM_COMMIT = 0x1000
MEM_RESERVE = 0x2000
PAGE_EXECUTE_READWRITE = 0x40
PAGE_READWRITE = 0x04

FUNCS = ['NtUserGetAsyncKeyState', 'NtUserGetKeyState', 'NtUserGetKeyboardState']


def find_module_base(pid, name_b):
    h = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
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
    kernel32.CloseHandle(h)
    return base


def get_export_addr(pid, module, func):
    base = find_module_base(pid, module.encode())
    syswow = os.path.join(os.environ.get('WINDIR', r'C:/Windows'), 'SysWOW64', module)
    pe = pefile.PE(syswow, fast_load=True)
    pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_EXPORT']])
    rva = None
    for exp in pe.DIRECTORY_ENTRY_EXPORT.symbols:
        if exp.name == func.encode():
            rva = exp.address
            break
    pe.close()
    if rva is None:
        raise RuntimeError(f'{module}!{func} 未找到')
    return (base + rva) & 0xFFFFFFFF


def wpm(h, addr, data):
    rd = ctypes.c_size_t(0)
    ok = kernel32.WriteProcessMemory(h, ctypes.c_void_p(addr), data, len(data), ctypes.byref(rd))
    if not ok or rd.value != len(data):
        raise RuntimeError(f'WPM @0x{addr:08X} err={ctypes.get_last_error()}')
    chk = ctypes.create_string_buffer(len(data))
    r2 = ctypes.c_size_t(0)
    kernel32.ReadProcessMemory(h, ctypes.c_void_p(addr), chk, len(data), ctypes.byref(r2))
    if chk.raw != data:
        raise RuntimeError(f'校验失败 @0x{addr:08X}')


def rd32(h, a):
    b = ctypes.create_string_buffer(4)
    r = ctypes.c_size_t(0)
    kernel32.ReadProcessMemory(h, ctypes.c_void_p(a), b, 4, ctypes.byref(r))
    return struct.unpack('<I', b.raw)[0]


def main():
    pid = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    if not pid:
        print('用法: python observe_inline_input.py PID')
        return
    h = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
    if not h:
        print(f'[err] OpenProcess: {ctypes.get_last_error()}')
        return

    hooks = []
    for fn in FUNCS:
        try:
            addr = get_export_addr(pid, 'win32u.dll', fn)
        except RuntimeError as e:
            print(f'  {fn}: {e}')
            continue
        orig = ctypes.create_string_buffer(8)
        rd = ctypes.c_size_t(0)
        kernel32.ReadProcessMemory(h, ctypes.c_void_p(addr), orig, 8, ctypes.byref(rd))
        ob = orig.raw
        print(f'  {fn} @0x{addr:08X} 入口字节: {ob[:5].hex(" ")}')
        # 分配注入区：data(16) + counter_inc + code_new
        alloc = int(kernel32.VirtualAllocEx(h, None, 16 + 64 + 64, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE)) & 0xFFFFFFFF
        ctr = alloc
        code_new = alloc + 16
        inc_addr = code_new + 64
        wpm(h, ctr, struct.pack('<I', 0))
        # counter_inc: mov eax,[ctr]; inc eax; mov [ctr],eax; ret
        inc = b'\xA1' + struct.pack('<I', ctr) + b'\x40\xA3' + struct.pack('<I', ctr) + b'\xC3'
        wpm(h, inc_addr, inc)
        # code_new: pushad / call inc / popad / 原5字节 / jmp 回
        code = b'\x60' + b'\xE8' + struct.pack('<i', inc_addr - (code_new + 5)) + b'\x61' + ob[:5] + b'\xE9' + struct.pack('<i', (addr + 5) - (code_new + 5 + 5 + 5))
        wpm(h, code_new, code)
        # 覆盖入口 5 字节
        jmp = b'\xE9' + struct.pack('<i', code_new - addr - 5)
        kernel32.VirtualProtectEx(h, ctypes.c_void_p(addr), 5, PAGE_EXECUTE_READWRITE, ctypes.byref(wt.DWORD()))
        wpm(h, addr, jmp)
        kernel32.VirtualProtectEx(h, ctypes.c_void_p(addr), 5, PAGE_EXECUTE_READWRITE, ctypes.byref(wt.DWORD()))
        hooks.append({'fn': fn, 'addr': addr, 'orig': ob[:5], 'ctr': ctr})
        print(f'    → inline hook @0x{addr:08X} 计数 @0x{ctr:08X}')

    print('[monitor] 8 秒（前4秒保持前台，后4秒切后台对比）')
    t0 = time.time()
    last = {x['fn']: rd32(h, x['ctr']) for x in hooks}
    while time.time() - t0 < 8:
        time.sleep(1)
        cur = {x['fn']: rd32(h, x['ctr']) for x in hooks}
        print('  t=%ds  ' % int(time.time() - t0) + '  '.join(f'{k}:+{cur[k]-last[k]}(总{cur[k]})' for k in cur))
        last = cur

    print('[unhook] 恢复')
    for x in hooks:
        cur_b = ctypes.create_string_buffer(5)
        r2 = ctypes.c_size_t(0)
        kernel32.ReadProcessMemory(h, ctypes.c_void_p(x['addr']), cur_b, 5, ctypes.byref(r2))
        if cur_b.raw[0] == 0xE9:
            kernel32.VirtualProtectEx(h, ctypes.c_void_p(x['addr']), 5, PAGE_EXECUTE_READWRITE, ctypes.byref(wt.DWORD()))
            wpm(h, x['addr'], x['orig'])
            kernel32.VirtualProtectEx(h, ctypes.c_void_p(x['addr']), 5, PAGE_EXECUTE_READWRITE, ctypes.byref(wt.DWORD()))
            print(f'  [ok] {x["fn"]} 已恢复 {x["orig"].hex(" ")}')
        else:
            print(f'  [ok] {x["fn"]} 未被修改')
    kernel32.CloseHandle(h)


if __name__ == '__main__':
    main()
