# -*- coding: utf-8 -*-
"""决定性实验：同时挂 user32+win32u 全部输入函数计数 hook，
外部 keybd_event 触发 ALT+E，看游戏生效瞬间调用哪个 API。
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
user32 = ctypes.WinDLL('user32', use_last_error=True)

PROCESS_ALL_ACCESS = 0x1F0FFF
MEM_COMMIT = 0x1000
MEM_RESERVE = 0x2000
PAGE_EXECUTE_READWRITE = 0x40
PAGE_READWRITE = 0x04

TARGETS = [
    ('user32.dll', 'GetAsyncKeyState'),
    ('user32.dll', 'GetKeyState'),
    ('user32.dll', 'GetKeyboardState'),
    ('win32u.dll', 'NtUserGetAsyncKeyState'),
    ('win32u.dll', 'NtUserGetKeyState'),
    ('win32u.dll', 'NtUserGetKeyboardState'),
]


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
    if not base:
        raise RuntimeError(f'{module} 未加载')
    syswow = os.path.join(os.environ.get('WINDIR', r'C:/Windows'), 'SysWOW64', module)
    pe = pefile.PE(syswow, fast_load=True)
    pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_EXPORT']])
    rva = None
    for e in pe.DIRECTORY_ENTRY_EXPORT.symbols:
        if e.name == func.encode():
            rva = e.address
            break
    pe.close()
    if rva is None:
        raise RuntimeError(f'{func} 导出未找到')
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
        print('用法: python observe_all_input.py PID')
        return
    h = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
    if not h:
        print(f'[err] OpenProcess: {ctypes.get_last_error()}')
        return

    hooks = []
    for module, fn in TARGETS:
        try:
            addr = get_export_addr(pid, module, fn)
        except RuntimeError as e:
            print(f'  {module}!{fn}: {e}')
            continue
        orig = ctypes.create_string_buffer(8)
        rd = ctypes.c_size_t(0)
        kernel32.ReadProcessMemory(h, ctypes.c_void_p(addr), orig, 8, ctypes.byref(rd))
        ob = orig.raw
        alloc = int(kernel32.VirtualAllocEx(h, None, 16 + 64 + 64, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE)) & 0xFFFFFFFF
        ctr = alloc
        code_new = alloc + 16
        inc_addr = code_new + 64
        wpm(h, ctr, struct.pack('<I', 0))
        inc = b'\xA1' + struct.pack('<I', ctr) + b'\x40\xA3' + struct.pack('<I', ctr) + b'\xC3'
        wpm(h, inc_addr, inc)
        code = b'\x60' + b'\xE8' + struct.pack('<i', inc_addr - (code_new + 5)) + b'\x61' + ob[:5] + b'\xE9' + struct.pack('<i', (addr + 5) - (code_new + 11))
        wpm(h, code_new, code)
        jmp = b'\xE9' + struct.pack('<i', code_new - addr - 5)
        k32_prot = wt.DWORD()
        okp = kernel32.VirtualProtectEx(h, ctypes.c_void_p(addr), 5, PAGE_EXECUTE_READWRITE, ctypes.byref(k32_prot))
        if not okp:
            print(f'  {module}!{fn}: VirtualProtectEx 失败 err={ctypes.get_last_error()}，跳过')
            continue
        wpm(h, addr, jmp)
        # 立即验证入口
        chk = ctypes.create_string_buffer(6)
        r2 = ctypes.c_size_t(0)
        kernel32.ReadProcessMemory(h, ctypes.c_void_p(addr), chk, 6, ctypes.byref(r2))
        print(f'  hook {module}!{fn} @0x{addr:08X} 入口now={chk.raw[:6].hex(" ")} 原={ob[:6].hex(" ")}')
        hooks.append({'name': f'{module}!{fn}', 'addr': addr, 'orig': ob[:5], 'ctr': ctr})

    if not hooks:
        print('[err] 全部 hook 失败')
        kernel32.CloseHandle(h)
        return

    def snapshot():
        return {x['name']: rd32(h, x['ctr']) for x in hooks}

    print('[monitor-1] baseline 3 秒')
    time.sleep(3)
    b0 = snapshot()
    print('  baseline:', {k: v for k, v in b0.items() if v})

    print('[action] 外部 keybd_event 注入 ALT+E ×3（游戏应前台）')
    for i in range(3):
        user32.keybd_event(0x12, 0, 0, 0)      # ALT down
        time.sleep(0.08)
        user32.keybd_event(0x45, 0, 0, 0)      # E down
        time.sleep(0.08)
        user32.keybd_event(0x45, 0, 2, 0)      # E up
        time.sleep(0.08)
        user32.keybd_event(0x12, 0, 2, 0)      # ALT up
        print(f'  [{i+1}/3] ALT+E 已注入')
        time.sleep(1)
    b1 = snapshot()
    print('[结果] keybd_event 注入后各 API 计数增量:')
    for name in b1:
        if b1[name] != b0.get(name, 0):
            print(f'  {name}: +{b1[name] - b0.get(name, 0)} (总{b1[name]})')
    if all(b1[n] == b0.get(n, 0) for n in b1):
        print('  （全部 0 增量 —— 游戏不通过任何标准输入 API 读键）')

    print('[unhook]')
    for x in hooks:
        cur_b = ctypes.create_string_buffer(5)
        r2 = ctypes.c_size_t(0)
        kernel32.ReadProcessMemory(h, ctypes.c_void_p(x['addr']), cur_b, 5, ctypes.byref(r2))
        if cur_b.raw[0] == 0xE9 and cur_b.raw != x['orig']:
            kernel32.VirtualProtectEx(h, ctypes.c_void_p(x['addr']), 5, PAGE_EXECUTE_READWRITE, ctypes.byref(wt.DWORD()))
            wpm(h, x['addr'], x['orig'])
            print(f'  [ok] {x["name"]} 已恢复')
        else:
            print(f'  [?] {x["name"]} 当前={cur_b.raw.hex(" ")} 原={x["orig"].hex(" ")}')
    kernel32.CloseHandle(h)


if __name__ == '__main__':
    main()
