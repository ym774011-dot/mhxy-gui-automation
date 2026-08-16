# -*- coding: utf-8 -*-
"""梦幻私服主线程 Hook 验证（机器码注入版，等效测试 DLL）

原理：CodeHook 模式 —— 覆盖 0x1BFF30 头部 5 字节为 E9 跳转到注入代码：
    code_new: pushad / call tick / popad / 原5字节 / jmp 回 0x1BFF30+5
    tick: 计数器递增，每 256 帧调 OutputDebugStringA("MHXY_HOOK_OK")（DebugView++ 可见）

用法:
    python hook_main_loop_test.py 25820            # 注入并验证 5 秒
    python hook_main_loop_test.py 25820 --unhook   # 恢复原字节
    python hook_main_loop_test.py 25820 --watch 30 # 注入并持续观察
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
MEM_RELEASE = 0x8000
PAGE_EXECUTE_READWRITE = 0x40
PAGE_READWRITE = 0x04

HOOK_VA = 0x1B3310        # galaxy2d 引擎每帧回调 exe 的函数（Lua 桥接）
HOOK_LEN = 6              # mov esi,[0x1f7434] 完整 6 字节（指令边界安全）
ORIG_HEX = '55 8b ec 83 e4 c0'
MSG = b'MHXY_HOOK_OK\x00'
TICK_EVERY = 256          # 每 256 帧输出一次（约 4 秒 @60fps）


def get_kernel32_and_ods(pid):
    """拿游戏进程内 kernel32.dll 基址 + OutputDebugStringA 地址"""
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
        if name.value.lower() in (b'kernel32.dll', b'kernelbase.dll'):
            mi = MODULEINFO()
            psapi.GetModuleInformation(h, hmods[i], ctypes.byref(mi), ctypes.sizeof(mi))
            if name.value.lower() == b'kernel32.dll':
                k32_base = mi.lpBaseOfDll
                break
    kernel32.CloseHandle(h)
    if not k32_base:
        raise RuntimeError('未找到 kernel32.dll')

    # 用 SysWOW64 的 kernel32.dll 解析导出表（32 位游戏加载的版本）
    syswow = os.path.join(os.environ.get('WINDIR', r'C:\Windows'), 'SysWOW64', 'kernel32.dll')
    pe = pefile.PE(syswow, fast_load=True)
    pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_EXPORT']])
    ods_rva = None
    for exp in pe.DIRECTORY_ENTRY_EXPORT.symbols:
        if exp.name == b'OutputDebugStringA':
            ods_rva = exp.address
            break
    pe.close()
    if ods_rva is None:
        raise RuntimeError('未找到 OutputDebugStringA 导出')
    return int(k32_base), (int(k32_base) + ods_rva) & 0xFFFFFFFF


def build_shellcode(counter_addr, ods_addr, msg_addr):
    """构造 tick 函数 + code_new（32 位机器码）"""
    # tick: 计数器++，每 TICK_EVERY 帧调 OutputDebugStringA
    tick = b''
    tick += b'\xA1' + struct.pack('<I', counter_addr)        # mov eax, [counter]
    tick += b'\x40'                                          # inc eax
    tick += b'\xA3' + struct.pack('<I', counter_addr)        # mov [counter], eax
    tick += b'\xA9' + struct.pack('<I', TICK_EVERY)          # test eax, TICK_EVERY
    tick += b'\x75\x10'                                      # jnz skip (16字节: push+mov+call+add+ret)
    tick += b'\x68' + struct.pack('<I', msg_addr)            # push msg
    tick += b'\xB8' + struct.pack('<I', ods_addr)            # mov eax, ods_addr（立即数=函数地址）
    tick += b'\xFF\xD0'                                      # call eax
    tick += b'\x83\xC4\x04'                                  # add esp, 4
    tick += b'\xC3'                                          # ret (skip 也落到这里)
    return tick


def main():
    pid = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    mode = 'inject'
    counter_addr = 0
    lua_mode = '--lua' in sys.argv[2:]
    for a in sys.argv[2:]:
        if a == '--unhook':
            mode = 'unhook'
        elif a.startswith('--monitor='):
            mode = 'monitor'
            counter_addr = int(a.split('=', 1)[1], 16)
    if not pid:
        print('用法: python hook_main_loop_test.py PID [--unhook|--monitor=0xADDR]')
        return

    h = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
    if not h:
        print(f'[err] OpenProcess: {ctypes.get_last_error()}（需要管理员权限）')
        return
    print(f'[ok] 已打开进程 {pid}')

    if mode == 'monitor':
        print(f'[monitor] 观察 counter 0x{counter_addr:08X}（每 2 秒）')
        try:
            while True:
                buf = ctypes.create_string_buffer(4)
                read = ctypes.c_size_t(0)
                kernel32.ReadProcessMemory(h, ctypes.c_void_p(counter_addr), buf, 4, ctypes.byref(read))
                v = struct.unpack('<I', buf.raw)[0]
                print(f'  counter = {v}')
                time.sleep(2)
        except KeyboardInterrupt:
            print('[monitor] 停止')
        return

    global HOOK_VA, HOOK_LEN, ORIG_HEX
    if lua_mode:
        # 动态找 lua51.dll 基址，hook luaV_execute 取指令核心 (RVA 0x3F684)
        lua_base = None
        for base, size, name, _ in get_modules(pid):
            if 'lua51' in name.lower():
                lua_base = int(base)
                break
        if not lua_base:
            print('[err] 未找到 lua51.dll')
            return
        HOOK_VA = (lua_base + 0x3F684) & 0xFFFFFFFF  # luaV_execute 取指令核心
        HOOK_LEN = 6
        ORIG_HEX = '0f b6 cc 0f b6 e8'  # movzx ecx,ah; movzx ebp,al
        print(f'[info] lua51 base=0x{lua_base:08X} -> luaV_execute=0x{HOOK_VA:08X}')
    k32_base, ods_addr = get_kernel32_and_ods(pid)
    print(f'[info] kernel32=0x{k32_base:08X} OutputDebugStringA=0x{ods_addr:08X}')

    # 读取当前字节（unhook 时写回）
    orig = ctypes.create_string_buffer(HOOK_LEN)
    read = ctypes.c_size_t(0)
    kernel32.ReadProcessMemory(h, ctypes.c_void_p(HOOK_VA), orig, HOOK_LEN, ctypes.byref(read))
    cur = orig.raw
    print(f'[info] 0x{HOOK_VA:08X} 当前字节: {cur.hex(" ")}')

    if mode == 'unhook':
        # 若当前是注入残留（E9 开头），恢复为原始字节
        restore = bytes.fromhex(ORIG_HEX) if cur[0] == 0xE9 else cur
        kernel32.VirtualProtectEx(h, ctypes.c_void_p(HOOK_VA), HOOK_LEN, PAGE_EXECUTE_READWRITE, ctypes.byref(wt.DWORD()))
        kernel32.WriteProcessMemory(h, ctypes.c_void_p(HOOK_VA), restore, HOOK_LEN, ctypes.byref(read))
        kernel32.VirtualProtectEx(h, ctypes.c_void_p(HOOK_VA), HOOK_LEN, PAGE_EXECUTE_READWRITE, ctypes.byref(wt.DWORD()))
        print(f'[ok] 已恢复: {restore.hex(" ")}')
        return

    # 分配注入区：data(16) + tick + code_new(32)
    code_new_size = 32
    data_size = 16 + len(MSG)
    total = data_size + HOOK_LEN + 256 + code_new_size
    base = kernel32.VirtualAllocEx(h, None, total, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE)
    if not base:
        print(f'[err] VirtualAllocEx: {ctypes.get_last_error()}')
        return
    base = int(base) & 0xFFFFFFFF
    print(f'[ok] 注入区 base=0x{base:08X}')

    data_off = 0
    tick_off = data_size
    tramp_off = tick_off + 256
    code_off = tramp_off + HOOK_LEN

    counter_addr = (base + data_off) & 0xFFFFFFFF
    ods_slot = (base + data_off + 4) & 0xFFFFFFFF
    msg_addr = (base + data_off + 8) & 0xFFFFFFFF

    # 1) 数据区：counter=0, ods_addr, msg
    data_blob = struct.pack('<II', 0, ods_addr) + MSG + b'\x00' * (data_size - 8 - len(MSG))
    kernel32.WriteProcessMemory(h, ctypes.c_void_p(base + data_off), data_blob, len(data_blob), ctypes.byref(read))

    # 2) tick 函数
    tick = build_shellcode(counter_addr, ods_addr, msg_addr)
    kernel32.WriteProcessMemory(h, ctypes.c_void_p(base + tick_off), tick, len(tick), ctypes.byref(read))

    # 3) trampoline（备用，本方案未用）
    # 4) code_new：pushad/call tick/popad/原字节/jmp 回
    orig_bytes = bytes.fromhex(ORIG_HEX)  # 备份的原始指令
    code = b''
    code += b'\x60'                                        # pushad
    rel = (base + tick_off) - (base + code_off + 1) - 5
    code += b'\xE8' + struct.pack('<i', rel)               # call tick
    code += b'\x61'                                        # popad
    code += orig_bytes                                     # 原 6 字节
    rel2 = (HOOK_VA + HOOK_LEN) - (base + code_off + len(code)) - 5
    code += b'\xE9' + struct.pack('<i', rel2)              # jmp 回 0x1C05F1
    kernel32.WriteProcessMemory(h, ctypes.c_void_p(base + code_off), code, len(code), ctypes.byref(read))
    print(f'[ok] code_new @ 0x{base+code_off:08X} ({len(code)}B): {code.hex(" ")}')

    # 5) 覆盖 0x1BFF30 头部
    jmp = b'\xE9' + struct.pack('<i', (base + code_off) - HOOK_VA - 5)
    old_prot = wt.DWORD()
    kernel32.VirtualProtectEx(h, ctypes.c_void_p(HOOK_VA), HOOK_LEN, PAGE_EXECUTE_READWRITE, ctypes.byref(old_prot))
    kernel32.WriteProcessMemory(h, ctypes.c_void_p(HOOK_VA), jmp, HOOK_LEN, ctypes.byref(read))
    kernel32.VirtualProtectEx(h, ctypes.c_void_p(HOOK_VA), HOOK_LEN, old_prot, ctypes.byref(wt.DWORD()))
    print(f'[ok] 已 Hook 0x{HOOK_VA:08X}: {jmp.hex(" ")}')

    # 6) 验证：读 counter 增长
    def read_counter():
        buf = ctypes.create_string_buffer(4)
        kernel32.ReadProcessMemory(h, ctypes.c_void_p(counter_addr), buf, 4, ctypes.byref(read))
        return struct.unpack('<I', buf.raw)[0]

    c0 = read_counter()
    print(f'[info] counter 初始 = {c0}')
    print(f'[monitor] 观察 counter: --monitor=0x{counter_addr:08X}')
    time.sleep(3)
    c1 = read_counter()
    print(f'[info] 3 秒后 counter = {c1}（增长 {c1-c0} 帧）')
    if c1 > c0:
        print('[✓✓] HOOK 生效！主循环每帧触发 tick（DebugView++ 应能看到 MHXY_HOOK_OK）')
    else:
        print('[✗] counter 未增长 —— 主循环可能未运行（窗口后台/待机），请把游戏切前台后重新 monitor')
    print('[note] Hook 保持挂载中，可随时 --unhook 恢复')

    kernel32.CloseHandle(h)


if __name__ == '__main__':
    main()
