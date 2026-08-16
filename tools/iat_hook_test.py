# -*- coding: utf-8 -*-
"""IAT 劫持验证：0x1de294 槽（每帧 call 的 galaxy2d 引擎帧函数）

原理：exe 主循环 0x1C05E3 `call [0x1de294]` 每帧调引擎帧函数。
把 IAT 槽 0x1de294 改为指向注入的 code_new：
    code_new: pushad / call tick / popad / jmp [原槽值]
    tick: counter++，每 256 次 OutputDebugStringA("MHXY_IAT_OK")

用法:
    python iat_hook_test.py PID
    python iat_hook_test.py PID --unhook
"""
import ctypes
import ctypes.wintypes as wt
import struct
import sys
import time
import os

import pefile
from find_main_thread import get_modules

kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
psapi = ctypes.WinDLL('psapi', use_last_error=True)

PROCESS_ALL_ACCESS = 0x1F0FFF
MEM_COMMIT = 0x1000
MEM_RESERVE = 0x2000
PAGE_EXECUTE_READWRITE = 0x40
IAT_SLOT = 0x1DE294          # exe 的 IAT 槽（call [0x1de294] 每帧）
MSG = b'MHXY_IAT_OK\x00'
TICK_EVERY = 256


def get_ods(pid):
    h = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
    needed = wt.DWORD(0)
    psapi.EnumProcessModulesEx(h, None, 0, ctypes.byref(needed), 3)
    count = needed.value // ctypes.sizeof(wt.HMODULE)
    hmods = (wt.HMODULE * count)()
    psapi.EnumProcessModulesEx(h, hmods, needed.value, ctypes.byref(needed), 3)

    class MODULEINFO(ctypes.Structure):
        _fields_ = [('lpBaseOfDll', ctypes.c_void_p), ('SizeOfImage', wt.DWORD),
                    ('EntryPoint', ctypes.c_void_p)]
    psapi.GetModuleInformation.argtypes = [wt.HANDLE, wt.HMODULE,
                                           ctypes.POINTER(MODULEINFO), wt.DWORD]
    psapi.GetModuleBaseNameA.argtypes = [wt.HANDLE, wt.HMODULE, ctypes.c_char_p, wt.DWORD]
    k32 = None
    for i in range(count):
        name = ctypes.create_string_buffer(64)
        psapi.GetModuleBaseNameA(h, hmods[i], name, 64)
        if name.value.lower() == b'kernel32.dll':
            mi = MODULEINFO()
            psapi.GetModuleInformation(h, hmods[i], ctypes.byref(mi), ctypes.sizeof(mi))
            k32 = mi.lpBaseOfDll
            break
    kernel32.CloseHandle(h)
    syswow = os.path.join(os.environ.get('WINDIR', r'C:\Windows'), 'SysWOW64', 'kernel32.dll')
    pe = pefile.PE(syswow, fast_load=True)
    pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_EXPORT']])
    for exp in pe.DIRECTORY_ENTRY_EXPORT.symbols:
        if exp.name == b'OutputDebugStringA':
            return (int(k32) + exp.address) & 0xFFFFFFFF
    raise RuntimeError('OutputDebugStringA 未找到')


def rd32(h, addr):
    b = ctypes.create_string_buffer(4)
    r = ctypes.c_size_t(0)
    kernel32.ReadProcessMemory(h, ctypes.c_void_p(addr), b, 4, ctypes.byref(r))
    return struct.unpack('<I', b.raw)[0] if r.value == 4 else None


def main():
    pid = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    unhook = '--unhook' in sys.argv
    if not pid:
        print('用法: python iat_hook_test.py PID [--unhook]')
        return
    h = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
    if not h:
        print(f'[err] OpenProcess: {ctypes.get_last_error()}')
        return
    orig_slot = rd32(h, IAT_SLOT)
    print(f'[info] IAT 0x{IAT_SLOT:08X} 原值 = 0x{orig_slot:08X}')

    if unhook:
        if orig_slot:
            kernel32.WriteProcessMemory(h, ctypes.c_void_p(IAT_SLOT), struct.pack('<I', orig_slot), 4, ctypes.byref(ctypes.c_size_t(0)))
            print(f'[ok] 已恢复 IAT 槽 = 0x{orig_slot:08X}')
        return

    ods = get_ods(pid)
    print(f'[info] OutputDebugStringA=0x{ods:08X}')

    data_size = 16 + len(MSG)
    base = int(kernel32.VirtualAllocEx(h, None, data_size + 300, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE)) & 0xFFFFFFFF
    if not base:
        print(f'[err] VirtualAllocEx: {ctypes.get_last_error()}')
        return
    print(f'[ok] 注入区 base=0x{base:08X}')
    counter = base
    ods_slot = base + 4
    msg_addr = base + 8
    tick_off = data_size
    code_off = tick_off + 128

    blob = struct.pack('<II', 0, ods) + MSG + b'\x00' * 8
    kernel32.WriteProcessMemory(h, ctypes.c_void_p(base), blob, len(blob), ctypes.byref(ctypes.c_size_t(0)))

    tick = b''
    tick += b'\xA1' + struct.pack('<I', counter)
    tick += b'\x40'
    tick += b'\xA3' + struct.pack('<I', counter)
    tick += b'\xA9' + struct.pack('<I', TICK_EVERY)
    tick += b'\x75\x10'
    tick += b'\x68' + struct.pack('<I', msg_addr)
    tick += b'\xA1' + struct.pack('<I', ods_slot)
    tick += b'\xFF\xD0'
    tick += b'\x83\xC4\x04'
    tick += b'\xC3'
    kernel32.WriteProcessMemory(h, ctypes.c_void_p(base + tick_off), tick, len(tick), ctypes.byref(ctypes.c_size_t(0)))

    # code_new: pushad / call tick / popad / jmp [原槽值]
    code = b'\x60' + b'\xE8' + struct.pack('<i', (base + tick_off) - (base + code_off + 1) - 5)
    code += b'\x61'
    code += b'\xE9' + struct.pack('<i', (orig_slot - (base + code_off + len(code))) - 5)
    kernel32.WriteProcessMemory(h, ctypes.c_void_p(base + code_off), code, len(code), ctypes.byref(ctypes.c_size_t(0)))
    print(f'[ok] code_new @ 0x{base+code_off:08X}: {code.hex(" ")}')

    # 改 IAT 槽
    new_slot = (base + code_off) & 0xFFFFFFFF
    kernel32.VirtualProtectEx(h, ctypes.c_void_p(IAT_SLOT), 4, PAGE_EXECUTE_READWRITE, ctypes.byref(wt.DWORD()))
    kernel32.WriteProcessMemory(h, ctypes.c_void_p(IAT_SLOT), struct.pack('<I', new_slot), 4, ctypes.byref(ctypes.c_size_t(0)))
    kernel32.VirtualProtectEx(h, ctypes.c_void_p(IAT_SLOT), 4, PAGE_EXECUTE_READWRITE, ctypes.byref(wt.DWORD()))
    print(f'[ok] 已劫持 IAT: 0x{IAT_SLOT:08X} -> 0x{new_slot:08X}')

    def rc():
        b = ctypes.create_string_buffer(4)
        kernel32.ReadProcessMemory(h, ctypes.c_void_p(counter), b, 4, ctypes.byref(ctypes.c_size_t(0)))
        return struct.unpack('<I', b.raw)[0]

    c0 = rc()
    print(f'[info] counter 初始 = {c0}')
    time.sleep(3)
    c1 = rc()
    print(f'[info] 3 秒后 counter = {c1}（增长 {c1-c0} 帧）')
    if c1 > c0:
        print('[✓✓] IAT 劫持生效！引擎帧函数每帧触发（DebugView++ 可见 MHXY_IAT_OK）')
    else:
        print('[✗] counter 未增长')
    kernel32.CloseHandle(h)


if __name__ == '__main__':
    main()
