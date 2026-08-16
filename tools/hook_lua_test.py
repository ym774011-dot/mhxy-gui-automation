# -*- coding: utf-8 -*-
"""lua_pcall Hook 验证（机器码注入）

hook lua51.dll!lua_pcall（游戏任何模式都高频执行 Lua）：
    code_new: pushad / call tick / popad / 原5字节 / jmp 回
    tick: counter 递增，每 256 次调 OutputDebugStringA("MHXY_LUA_OK")

用法:
    python hook_lua_test.py PID            # 注入 + 3 秒验证
    python hook_lua_test.py PID --unhook   # 恢复
"""
import ctypes
import ctypes.wintypes as wt
import struct
import sys
import time
import os

import pefile
from find_main_thread import get_modules, read_mem

kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
psapi = ctypes.WinDLL('psapi', use_last_error=True)

PROCESS_ALL_ACCESS = 0x1F0FFF
MEM_COMMIT = 0x1000
MEM_RESERVE = 0x2000
PAGE_EXECUTE_READWRITE = 0x40
LUA_PCALL_RVA = 0x4570
MSG = b'MHXY_LUA_OK\x00'
TICK_EVERY = 256


def get_ods_address(pid):
    """游戏进程内 kernel32!OutputDebugStringA 地址"""
    h = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
    if not h:
        raise RuntimeError(f'OpenProcess: {ctypes.get_last_error()}')
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
    k32_base = None
    for i in range(count):
        name = ctypes.create_string_buffer(64)
        psapi.GetModuleBaseNameA(h, hmods[i], name, 64)
        if name.value.lower() == b'kernel32.dll':
            mi = MODULEINFO()
            psapi.GetModuleInformation(h, hmods[i], ctypes.byref(mi), ctypes.sizeof(mi))
            k32_base = mi.lpBaseOfDll
            break
    kernel32.CloseHandle(h)
    if not k32_base:
        raise RuntimeError('未找到 kernel32.dll')
    syswow = os.path.join(os.environ.get('WINDIR', r'C:\Windows'), 'SysWOW64', 'kernel32.dll')
    pe = pefile.PE(syswow, fast_load=True)
    pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_EXPORT']])
    ods_rva = None
    for exp in pe.DIRECTORY_ENTRY_EXPORT.symbols:
        if exp.name == b'OutputDebugStringA':
            ods_rva = exp.address
            break
    pe.close()
    return (int(k32_base) + ods_rva) & 0xFFFFFFFF


def main():
    pid = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    unhook = '--unhook' in sys.argv
    if not pid:
        print('用法: python hook_lua_test.py PID [--unhook]')
        return

    # 动态定位 lua51.dll + lua_pcall
    lua_base = None
    for base, size, name, _ in get_modules(pid):
        if 'lua51' in name.lower():
            lua_base = int(base)
            break
    if not lua_base:
        print('[err] 未找到 lua51.dll')
        return
    hook_va = (lua_base + LUA_PCALL_RVA) & 0xFFFFFFFF
    print(f'[info] lua51=0x{lua_base:08X} lua_pcall=0x{hook_va:08X}')

    h = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
    if not h:
        print(f'[err] OpenProcess: {ctypes.get_last_error()}')
        return

    # 读当前字节
    cur = ctypes.create_string_buffer(5)
    read = ctypes.c_size_t(0)
    kernel32.ReadProcessMemory(h, ctypes.c_void_p(hook_va), cur, 5, ctypes.byref(read))
    print(f'[info] 当前字节: {cur.raw.hex(" ")}')

    if unhook:
        restore = bytes.fromhex('55 8b ec 83 ec') if cur.raw[0] == 0xE9 else cur.raw
        kernel32.VirtualProtectEx(h, ctypes.c_void_p(hook_va), 5, PAGE_EXECUTE_READWRITE, ctypes.byref(wt.DWORD()))
        kernel32.WriteProcessMemory(h, ctypes.c_void_p(hook_va), restore, 5, ctypes.byref(read))
        kernel32.VirtualProtectEx(h, ctypes.c_void_p(hook_va), 5, PAGE_EXECUTE_READWRITE, ctypes.byref(wt.DWORD()))
        print(f'[ok] 已恢复: {restore.hex(" ")}')
        return

    ods_addr = get_ods_address(pid)
    print(f'[info] OutputDebugStringA=0x{ods_addr:08X}')

    # 注入区
    data_size = 16 + len(MSG)
    base = int(kernel32.VirtualAllocEx(h, None, data_size + 300, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE)) & 0xFFFFFFFF
    if not base:
        print(f'[err] VirtualAllocEx: {ctypes.get_last_error()}')
        return
    print(f'[ok] 注入区 base=0x{base:08X}')
    counter_addr = base
    ods_slot = base + 4
    msg_addr = base + 8
    tick_off = data_size
    code_off = tick_off + 128

    # 数据区
    blob = struct.pack('<II', 0, ods_addr) + MSG + b'\x00' * 8
    kernel32.WriteProcessMemory(h, ctypes.c_void_p(base), blob, len(blob), ctypes.byref(read))

    # tick: counter++ / 每256次 OutputDebugStringA
    tick = b''
    tick += b'\xA1' + struct.pack('<I', counter_addr)   # mov eax,[counter]
    tick += b'\x40'                                     # inc eax
    tick += b'\xA3' + struct.pack('<I', counter_addr)   # mov [counter],eax
    tick += b'\xA9' + struct.pack('<I', TICK_EVERY)     # test eax,256
    tick += b'\x75\x10'                                 # jnz +16
    tick += b'\x68' + struct.pack('<I', msg_addr)       # push msg
    tick += b'\xA1' + struct.pack('<I', ods_slot)       # mov eax,[ods]
    tick += b'\xFF\xD0'                                 # call eax
    tick += b'\x83\xC4\x04'                             # add esp,4
    tick += b'\xC3'                                     # ret
    kernel32.WriteProcessMemory(h, ctypes.c_void_p(base + tick_off), tick, len(tick), ctypes.byref(read))

    # code_new: pushad / call tick / popad / 原字节 / jmp 回
    orig = bytes.fromhex('55 8b ec 83 ec')  # lua_pcall 序言（从磁盘 PE 确认）
    code = b'\x60' + b'\xE8' + struct.pack('<i', (base + tick_off) - (base + code_off + 1) - 5)
    code += b'\x61' + orig
    code += b'\xE9' + struct.pack('<i', (hook_va + 5) - (base + code_off + len(code)) - 5)
    kernel32.WriteProcessMemory(h, ctypes.c_void_p(base + code_off), code, len(code), ctypes.byref(read))
    print(f'[ok] code_new @ 0x{base+code_off:08X}: {code.hex(" ")}')

    # hook
    jmp = b'\xE9' + struct.pack('<i', (base + code_off) - hook_va - 5)
    kernel32.VirtualProtectEx(h, ctypes.c_void_p(hook_va), 5, PAGE_EXECUTE_READWRITE, ctypes.byref(wt.DWORD()))
    kernel32.WriteProcessMemory(h, ctypes.c_void_p(hook_va), jmp, 5, ctypes.byref(read))
    kernel32.VirtualProtectEx(h, ctypes.c_void_p(hook_va), 5, PAGE_EXECUTE_READWRITE, ctypes.byref(wt.DWORD()))
    print(f'[ok] 已 Hook lua_pcall: {jmp.hex(" ")}')

    # 验证
    def rc():
        b = ctypes.create_string_buffer(4)
        kernel32.ReadProcessMemory(h, ctypes.c_void_p(counter_addr), b, 4, ctypes.byref(read))
        return struct.unpack('<I', b.raw)[0]

    c0 = rc()
    print(f'[info] counter 初始 = {c0}')
    time.sleep(3)
    c1 = rc()
    print(f'[info] 3 秒后 counter = {c1}（增长 {c1-c0} 次 Lua 调用）')
    if c1 > c0:
        print('[✓✓] HOOK 生效！lua_pcall 高频触发（DebugView++ 可见 MHXY_LUA_OK）')
    else:
        print('[✗] counter 未增长')
    kernel32.CloseHandle(h)


if __name__ == '__main__':
    main()
