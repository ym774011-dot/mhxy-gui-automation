# -*- coding: utf-8 -*-
"""观测游戏输入 API：hook newjc.dll!GetKeyState 与 ExuiKrnln.dll!GetAsyncKeyState
的 IAT 槽，计数调用次数（计数后跳原函数，零干扰），确认游戏读哪个 API。

用法:
    python observe_input_api.py 2116            # 挂计数壳，观察 8 秒后自动恢复
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

GAME_DIR = r'G:/00'


def find_module_base(pid, name_b):
    h = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
    if not h:
        raise RuntimeError(f'OpenProcess: {ctypes.get_last_error()}')
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


def find_iat_slot_rva(dll_path, func_name):
    pe = pefile.PE(dll_path, fast_load=True)
    pe.parse_data_directories()
    image_base = pe.OPTIONAL_HEADER.ImageBase
    for entry in getattr(pe, 'DIRECTORY_ENTRY_IMPORT', []):
        for imp in entry.imports:
            if imp.name == func_name.encode():
                rva = (imp.address - image_base) & 0xFFFFFFFF
                pe.close()
                return rva
    pe.close()
    return None


def get_user32_export(pid, func):
    base = find_module_base(pid, b'user32.dll')
    syswow = os.path.join(os.environ.get('WINDIR', r'C:/Windows'), 'SysWOW64', 'user32.dll')
    pe = pefile.PE(syswow, fast_load=True)
    pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_EXPORT']])
    rva = None
    for exp in pe.DIRECTORY_ENTRY_EXPORT.symbols:
        if exp.name == func.encode():
            rva = exp.address
            break
    pe.close()
    return (base + rva) & 0xFFFFFFFF


def wpm(h, addr, data):
    rd = ctypes.c_size_t(0)
    ok = kernel32.WriteProcessMemory(h, ctypes.c_void_p(addr), data, len(data), ctypes.byref(rd))
    if not ok or rd.value != len(data):
        raise RuntimeError(f'WPM 失败 @0x{addr:08X} err={ctypes.get_last_error()}')
    chk = ctypes.create_string_buffer(len(data))
    r2 = ctypes.c_size_t(0)
    kernel32.ReadProcessMemory(h, ctypes.c_void_p(addr), chk, len(data), ctypes.byref(r2))
    if chk.raw != data:
        raise RuntimeError(f'校验失败 @0x{addr:08X}')


def build_counter(orig_slot_abs):
    """counter++ 后 jmp [orig_slot_abs]（原函数真值）"""
    return b'\xA1\x00\x00\x00\x00\x40\xA3\x00\x00\x00\x00' + b'\xFF\x25' + struct.pack('<I', orig_slot_abs)


def read_u32(h, addr):
    buf = ctypes.create_string_buffer(4)
    rd = ctypes.c_size_t(0)
    kernel32.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, 4, ctypes.byref(rd))
    return struct.unpack('<I', buf.raw)[0]


def main():
    pid = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    if not pid:
        print('用法: python observe_input_api.py PID')
        return
    h = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
    if not h:
        print(f'[err] OpenProcess: {ctypes.get_last_error()}')
        return

    targets = []
    # newjc.dll -> GetKeyState
    base = find_module_base(pid, b'newjc.dll')
    if base:
        rva = find_iat_slot_rva(os.path.join(GAME_DIR, 'newjc.dll'), 'GetKeyState')
        if rva is not None:
            targets.append(('newjc.dll!GetKeyState', (base + rva) & 0xFFFFFFFF))
    # ExuiKrnln.dll -> GetAsyncKeyState
    base = find_module_base(pid, b'exuikrnln.dll')
    if base:
        rva = find_iat_slot_rva(os.path.join(GAME_DIR, 'ExuiKrnln.dll'), 'GetAsyncKeyState')
        if rva is not None:
            targets.append(('ExuiKrnln.dll!GetAsyncKeyState', (base + rva) & 0xFFFFFFFF))
    if not targets:
        print('[err] 未找到可观测的 IAT 槽')
        kernel32.CloseHandle(h)
        return

    print(f'[ok] 观测目标:')
    hooks = []
    for name, slot in targets:
        orig = read_u32(h, slot)
        print(f'  {name}: 槽=0x{slot:08X} 原值=0x{orig:08X}')
        # 注入区：data(16) + counter壳(16)
        alloc = kernel32.VirtualAllocEx(h, None, 32, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE)
        alloc = int(alloc) & 0xFFFFFFFF
        wpm(h, alloc, struct.pack('<I', orig))                    # data: 原函数真值
        counter_addr = alloc + 4
        shell = build_counter(alloc)
        # 修正 counter 地址引用
        shell = shell[:1] + struct.pack('<I', counter_addr) + shell[5:6] + struct.pack('<I', counter_addr) + shell[10:]
        wpm(h, alloc + 16, shell)
        # 改槽
        kernel32.VirtualProtectEx(h, ctypes.c_void_p(slot), 4, PAGE_READWRITE, ctypes.byref(wt.DWORD()))
        wpm(h, slot, struct.pack('<I', alloc + 16))
        kernel32.VirtualProtectEx(h, ctypes.c_void_p(slot), 4, PAGE_READWRITE, ctypes.byref(wt.DWORD()))
        hooks.append({'name': name, 'slot': slot, 'orig': orig, 'counter': counter_addr})
        print(f'    → 已挂计数壳 @0x{alloc+16:08X}，counter @0x{counter_addr:08X}')

    print(f'[monitor] 观察 8 秒（游戏前后台均可，先保持当前状态 4 秒再切换一次）')
    t0 = time.time()
    last = {x['name']: read_u32(h, x['counter']) for x in hooks}
    while time.time() - t0 < 8:
        time.sleep(1)
        cur = {x['name']: read_u32(h, x['counter']) for x in hooks}
        line = '  '.join(f'{k}: +{cur[k]-last[k]} (总{cur[k]})' for k in cur)
        print(f'  t={time.time()-t0:.0f}s  {line}')
        last = cur

    print('[unhook] 自动恢复')
    for x in hooks:
        cur_v = read_u32(h, x['slot'])
        if cur_v != x['orig']:
            kernel32.VirtualProtectEx(h, ctypes.c_void_p(x['slot']), 4, PAGE_READWRITE, ctypes.byref(wt.DWORD()))
            wpm(h, x['slot'], struct.pack('<I', x['orig']))
            kernel32.VirtualProtectEx(h, ctypes.c_void_p(x['slot']), 4, PAGE_READWRITE, ctypes.byref(wt.DWORD()))
            print(f'  [ok] {x["name"]} 槽已恢复 0x{x["orig"]:08X}')
        else:
            print(f'  [ok] {x["name"]} 槽已是原值')
    kernel32.CloseHandle(h)


if __name__ == '__main__':
    main()
