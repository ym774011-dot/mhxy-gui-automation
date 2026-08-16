# -*- coding: utf-8 -*-
"""梦幻私服 组合键注入测试（机器码 CodeHook 版）

原理：CodeHook(0x1B3310, 6) —— exe 段每帧回调（galaxy2d -> Lua 桥）。
  tick 在 counter==2 帧时执行 keybd_event 序列（ALT down / E down / E up / ALT up），
  即从游戏进程内部触发 ALT+E 组合键（不 SetForegroundWindow，不抢前台）。

用法:
    python hook_key_test.py 2116            # 注入：第2帧按一次 ALT+E
    python hook_key_test.py 2116 --loop     # 每 300 帧重复按（观察背包反复开关）
    python hook_key_test.py 2116 --unhook   # 恢复原字节
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

HOOK_VA = 0x1B3310        # galaxy2d 每帧回调 exe 函数（Lua 桥接）
HOOK_LEN = 6
ORIG_HEX = '55 8b ec 83 e4 c0'
KEYEVENTF_KEYUP = 0x0002
VK_MENU = 0x12            # ALT
VK_E = 0x45               # E


def get_module_export(pid, module_name, func_name):
    """拿游戏进程内指定模块（kernel32/user32...）基址 + 导出函数地址"""
    module_name_b = module_name.lower().encode()
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

    mod_base = None
    for i in range(count):
        name = ctypes.create_string_buffer(64)
        psapi.GetModuleBaseNameA(h, hmods[i], name, 64)
        if name.value.lower() == module_name_b:
            mi = MODULEINFO()
            psapi.GetModuleInformation(h, hmods[i], ctypes.byref(mi), ctypes.sizeof(mi))
            mod_base = mi.lpBaseOfDll
            break
    kernel32.CloseHandle(h)
    if not mod_base:
        raise RuntimeError(f'未找到 {module_name}')

    syswow = os.path.join(os.environ.get('WINDIR', r'C:/Windows'), 'SysWOW64', module_name)
    pe = pefile.PE(syswow, fast_load=True)
    pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_EXPORT']])
    rva = None
    for exp in pe.DIRECTORY_ENTRY_EXPORT.symbols:
        if exp.name == func_name.encode():
            rva = exp.address
            break
    pe.close()
    if rva is None:
        raise RuntimeError(f'未找到导出 {func_name}')
    return int(mod_base), (int(mod_base) + rva) & 0xFFFFFFFF


def build_key_events(ke_addr, pairs):
    """按 (vk, flags) 序列调用 keybd_event，每个按键 18B。

    keybd_event 是 WINAPI(__stdcall) → callee 清理栈，call 后【不得】add esp！
    """
    seq = b''
    for vk, flags in pairs:
        seq += b'\x6A\x00'                                    # push 0  (dwExtraInfo)
        seq += b'\x68' + struct.pack('<I', flags)             # push flags
        seq += b'\x6A\x00'                                    # push 0  (bScan)
        seq += b'\x6A' + bytes([vk])                          # push vk (bVk)
        seq += b'\xB8' + struct.pack('<I', ke_addr)           # mov eax, keybd_event(立即数)
        seq += b'\xFF\xD0'                                    # call eax (stdcall: callee 清理)
    return seq


def build_tick(counter_addr, ke_addr, hold_frames=30):
    """tick 状态机：第 2 帧 ALT+E 按下 → 保持 hold_frames 帧 → 第 2+hold_frames 帧抬起

    关键：组合键按下状态必须跨越 ≥1 帧游戏快照，游戏才能读到"ALT+E 同时按下"。
    布局：cmp/je ×2 / ret / [down seq]+ret / [up seq]+ret
    """
    down_seq = build_key_events(ke_addr, [(VK_MENU, 0), (VK_E, 0)])
    up_seq = build_key_events(ke_addr, [(VK_E, KEYEVENTF_KEYUP), (VK_MENU, KEYEVENTF_KEYUP)])
    t = b''
    t += b'\xA1' + struct.pack('<I', counter_addr)            # mov eax, [counter]
    t += b'\x40'                                              # inc eax
    t += b'\xA3' + struct.pack('<I', counter_addr)            # mov [counter], eax
    # 布局偏移：前缀 11B + cmp(3)+je(2)+cmp(3)+je(2)+ret(1) = 22B 处 down 开始
    down_pos = 11 + 3 + 2 + 3 + 2 + 1                         # = 22
    up_pos = down_pos + len(down_seq) + 1                     # +down ret
    t += b'\x83\xF8\x02'                                      # cmp eax, 2
    t += b'\x74' + bytes([down_pos - 16])                     # je → down 序列
    t += b'\x83\xF8' + bytes([2 + hold_frames])               # cmp eax, 2+hold
    t += b'\x74' + bytes([up_pos - 21])                       # je → up 序列
    t += b'\xC3'                                              # ret（其它帧直接返回）
    t += down_seq
    t += b'\xC3'
    t += up_seq
    t += b'\xC3'
    return t


def main():
    pid = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    mode = 'inject'
    loop_every = 0
    for a in sys.argv[2:]:
        if a == '--unhook':
            mode = 'unhook'
        elif a == '--loop':
            loop_every = 300
    if not pid:
        print('用法: python hook_key_test.py PID [--loop|--unhook]')
        return

    h = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
    if not h:
        print(f'[err] OpenProcess: {ctypes.get_last_error()}（需管理员）')
        return
    print(f'[ok] 已打开进程 {pid}')

    # 验字节
    orig = ctypes.create_string_buffer(HOOK_LEN)
    rd = ctypes.c_size_t(0)
    kernel32.ReadProcessMemory(h, ctypes.c_void_p(HOOK_VA), orig, HOOK_LEN, ctypes.byref(rd))
    cur = orig.raw
    print(f'[info] 0x{HOOK_VA:08X} 当前字节: {cur.hex(" ")}')
    if mode == 'unhook':
        restore = bytes.fromhex(ORIG_HEX) if cur[0] == 0xE9 else cur
        kernel32.VirtualProtectEx(h, ctypes.c_void_p(HOOK_VA), HOOK_LEN,
                                  PAGE_EXECUTE_READWRITE, ctypes.byref(wt.DWORD()))
        kernel32.WriteProcessMemory(h, ctypes.c_void_p(HOOK_VA), restore, HOOK_LEN, ctypes.byref(rd))
        kernel32.VirtualProtectEx(h, ctypes.c_void_p(HOOK_VA), HOOK_LEN,
                                  PAGE_EXECUTE_READWRITE, ctypes.byref(wt.DWORD()))
        print(f'[ok] 已恢复: {restore.hex(" ")}')
        kernel32.CloseHandle(h)
        return
    if cur.hex(' ') != ORIG_HEX:
        print(f'[err] 字节不匹配，禁止 hook（可能已注入残留，先 --unhook）')
        kernel32.CloseHandle(h)
        return

    _, ke_addr = get_module_export(pid, 'user32.dll', 'keybd_event')
    print(f'[info] keybd_event = 0x{ke_addr:08X}')

    # 布局：data(16) + tick
    tick_max = 256
    total = 16 + tick_max
    base = kernel32.VirtualAllocEx(h, None, total, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE)
    if not base:
        print(f'[err] VirtualAllocEx: {ctypes.get_last_error()}')
        kernel32.CloseHandle(h)
        return
    base = int(base) & 0xFFFFFFFF
    print(f'[ok] 注入区 base=0x{base:08X}')

    counter_addr = base
    ke_slot = base + 4

    data_blob = struct.pack('<I', 0) + struct.pack('<I', ke_addr)
    kernel32.WriteProcessMemory(h, ctypes.c_void_p(base), data_blob, 8, ctypes.byref(rd))

    tick = build_tick(counter_addr, ke_addr)
    assert len(tick) < tick_max, f'tick 超长: {len(tick)}'
    kernel32.WriteProcessMemory(h, ctypes.c_void_p(base + 16), tick, len(tick), ctypes.byref(rd))
    print(f'[ok] tick @ 0x{base+16:08X} ({len(tick)}B): {tick.hex(" ")}')

    # code_new: pushad / call tick / popad / 原6字节 / jmp 回
    code_off = 16 + tick_max
    code = b''
    code += b'\x60'                                           # pushad
    rel = (base + 16) - (base + code_off + 1) - 5
    code += b'\xE8' + struct.pack('<i', rel)                  # call tick
    code += b'\x61'                                           # popad
    code += bytes.fromhex(ORIG_HEX)
    rel2 = (HOOK_VA + HOOK_LEN) - (base + code_off + len(code)) - 5
    code += b'\xE9' + struct.pack('<i', rel2)                 # jmp 回
    kernel32.WriteProcessMemory(h, ctypes.c_void_p(base + code_off), code, len(code), ctypes.byref(rd))
    print(f'[ok] code_new @ 0x{base+code_off:08X} ({len(code)}B)')

    # 覆盖 hook 点
    jmp = b'\xE9' + struct.pack('<i', (base + code_off) - HOOK_VA - 5)
    old_prot = wt.DWORD()
    kernel32.VirtualProtectEx(h, ctypes.c_void_p(HOOK_VA), HOOK_LEN,
                              PAGE_EXECUTE_READWRITE, ctypes.byref(old_prot))
    kernel32.WriteProcessMemory(h, ctypes.c_void_p(HOOK_VA), jmp, HOOK_LEN, ctypes.byref(rd))
    kernel32.VirtualProtectEx(h, ctypes.c_void_p(HOOK_VA), HOOK_LEN,
                              old_prot, ctypes.byref(wt.DWORD()))
    print(f'[ok] 已 Hook 0x{HOOK_VA:08X}: {jmp.hex(" ")}')

    def read_counter():
        buf = ctypes.create_string_buffer(4)
        kernel32.ReadProcessMemory(h, ctypes.c_void_p(counter_addr), buf, 4, ctypes.byref(rd))
        return struct.unpack('<I', buf.raw)[0]

    c0 = read_counter()
    print(f'[info] counter 初始 = {c0}')
    print(f'[info] 模式: 第 2 帧 ALT+E 按下并保持 30 帧（~0.5s），第 32 帧抬起')
    print(f'[action] 请观察游戏背包是否打开/切换！')
    for _ in range(6):
        time.sleep(1)
        c = read_counter()
        print(f'  counter = {c}')
        if c >= 32:
            print('[✓] 状态机已完成按下→抬起，ALT+E 已从游戏内部注入')
            break
    else:
        print('[✗] counter 未增长 —— 帧循环可能未运行，请确认游戏在前台活跃')
    print(f'[note] Hook 保持挂载，看效果后请 --unhook 恢复')
    kernel32.CloseHandle(h)


if __name__ == '__main__':
    main()
