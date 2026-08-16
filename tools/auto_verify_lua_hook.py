# -*- coding: utf-8 -*-
"""一体化验证：自动找大号 PID → hook luaV_execute → 监控 90 秒

用法: python auto_verify_lua_hook.py
运行后立即去游戏里走动/操作 30-60 秒，脚本自动输出结果。
"""
import ctypes
import ctypes.wintypes as wt
import struct
import subprocess
import csv
import io
import sys
import time
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from find_main_thread import get_modules, read_mem

kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
psapi = ctypes.WinDLL('psapi', use_last_error=True)
PROCESS_ALL_ACCESS = 0x1F0FFF
MEM_COMMIT = 0x1000
MEM_RESERVE = 0x2000
PAGE_EXECUTE_READWRITE = 0x40
LUA_VM_RVA = 0x3F684
ORIG = bytes.fromhex('0f b6 cc 0f b6 e8')
MSG = b'MHXY_LUA_VM_OK\x00'
TICK_EVERY = 256


def find_game_pid():
    r = subprocess.run(['tasklist', '/V', '/FO', 'CSV'], capture_output=True,
                       text=True, encoding='gbk', errors='ignore')
    for row in csv.reader(io.StringIO(r.stdout)):
        if len(row) >= 9 and '十年一梦.exe' in row[0] and '鲜衣' in row[8]:
            return int(row[1])
    # 兜底：任何十年一梦
    for row in csv.reader(io.StringIO(r.stdout)):
        if len(row) >= 9 and '十年一梦.exe' in row[0]:
            return int(row[1])
    return None


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
    if not k32:
        raise RuntimeError('kernel32 未找到')
    import pefile
    syswow = os.path.join(os.environ.get('WINDIR', r'C:\Windows'), 'SysWOW64', 'kernel32.dll')
    pe = pefile.PE(syswow, fast_load=True)
    pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_EXPORT']])
    for exp in pe.DIRECTORY_ENTRY_EXPORT.symbols:
        if exp.name == b'OutputDebugStringA':
            return (int(k32) + exp.address) & 0xFFFFFFFF
    raise RuntimeError('ODS 未找到')


def main():
    lua_call_mode = '--lua-call' in sys.argv
    pid = int(sys.argv[sys.argv.index('--pid')+1]) if '--pid' in sys.argv else find_game_pid()
    if not pid:
        print('[✗] 未找到游戏进程')
        return
    print(f'[info] 大号 PID = {pid}')

    lua_base = None
    for base, size, name, _ in get_modules(pid):
        if 'lua51' in name.lower():
            lua_base = int(base)
            break
    if not lua_base:
        print('[✗] lua51.dll 未找到')
        return
    if lua_call_mode:
        hook_va = (lua_base + 0x4540) & 0xFFFFFFFF   # lua_call 导出入口
        hook_len = 8
        orig = bytes.fromhex('8b 44 24 0c 8b 4c 24 08')
        print(f'[info] lua51=0x{lua_base:08X} lua_call=0x{hook_va:08X} (8字节覆盖)')
    else:
        hook_va = (lua_base + LUA_VM_RVA) & 0xFFFFFFFF
        hook_len = 6
        orig = ORIG
        print(f'[info] lua51=0x{lua_base:08X} luaV_execute=0x{hook_va:08X}')

    h = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
    if not h:
        print(f'[✗] OpenProcess: {ctypes.get_last_error()}')
        return

    # 当前字节确认
    cur = ctypes.create_string_buffer(8)
    read = ctypes.c_size_t(0)
    kernel32.ReadProcessMemory(h, ctypes.c_void_p(hook_va), cur, 8, ctypes.byref(read))
    if cur.raw[0] == 0xE9:
        print('[!] 该点已被 hook（残留），先不重复注入')
    else:
        ods = get_ods(pid)
        data_size = 16 + len(MSG)
        base = int(kernel32.VirtualAllocEx(h, None, data_size + 300, MEM_COMMIT | MEM_RESERVE,
                                           PAGE_EXECUTE_READWRITE)) & 0xFFFFFFFF
        print(f'[ok] 注入区 base=0x{base:08X}')
        counter = base
        ods_slot = base + 4
        msg_addr = base + 8
        tick_off = data_size
        code_off = tick_off + 128

        blob = struct.pack('<II', 0, ods) + MSG + b'\x00' * 8
        kernel32.WriteProcessMemory(h, ctypes.c_void_p(base), blob, len(blob), ctypes.byref(read))

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
        kernel32.WriteProcessMemory(h, ctypes.c_void_p(base + tick_off), tick, len(tick), ctypes.byref(read))

        code = b'\x60' + b'\xE8' + struct.pack('<i', (base + tick_off) - (base + code_off + 1) - 5)
        code += b'\x61' + ORIG
        code += b'\xE9' + struct.pack('<i', (hook_va + 6) - (base + code_off + len(code)) - 5)
        kernel32.WriteProcessMemory(h, ctypes.c_void_p(base + code_off), code, len(code), ctypes.byref(read))

        jmp = b'\xE9' + struct.pack('<i', (base + code_off) - hook_va - 5)
        kernel32.VirtualProtectEx(h, ctypes.c_void_p(hook_va), 6, PAGE_EXECUTE_READWRITE, ctypes.byref(wt.DWORD()))
        kernel32.WriteProcessMemory(h, ctypes.c_void_p(hook_va), jmp, 6, ctypes.byref(read))
        kernel32.VirtualProtectEx(h, ctypes.c_void_p(hook_va), 6, PAGE_EXECUTE_READWRITE, ctypes.byref(wt.DWORD()))
        print(f'[ok] 已 Hook luaV_execute: {jmp.hex(" ")}')
        print(f'[info] counter = 0x{counter:08X}')

        # 验证 hook 保持
        time.sleep(1)
        chk = read_mem(pid, hook_va, hook_len)
        kept = '保持 OK' if chk and chk[0] == 0xE9 else '被恢复 FAIL'
        hex_str = chk.hex(' ') if chk else '读取失败'
        print(f'[info] 1 秒后 hook 字节: {hex_str}（{kept}）')

        # 监控 90 秒
        def rc():
            b = ctypes.create_string_buffer(4)
            kernel32.ReadProcessMemory(h, ctypes.c_void_p(counter), b, 4, ctypes.byref(read))
            return struct.unpack('<I', b.raw)[0]

        c0 = rc()
        print(f'\n[monitor] 初始={c0}，监控 90 秒（每 2 秒）—— 请现在操作游戏走动！')
        last = c0
        t0 = time.time()
        while time.time() - t0 < 90:
            time.sleep(2)
            c = rc()
            if c != last:
                print(f'  +{int(time.time()-t0)}s counter={c} (+{c-last})')
                last = c
            if c > c0 + 500:
                print(f'[✓✓✓] HOOK 生效！luaV_execute 触发 {c-c0} 次，DebugView++ 可见 MHXY_LUA_VM_OK')
                break
        else:
            print('[✗] 90 秒未增长（hook 点未被执行）')
    kernel32.CloseHandle(h)


if __name__ == '__main__':
    main()
