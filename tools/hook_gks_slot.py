# -*- coding: utf-8 -*-
"""终极正解：改写 galaxy2d 的 GetKeyState 函数指针槽（0x10184280）

Input_IsKeyPress(vk) = call [0x10184280]（= user32!GetKeyState）→ 游戏开背包走此路径。
把槽指向注入的伪造函数：vk==ALT/E → 返回 0x8000（按下），其它键跳原 GetKeyState。
游戏内部间接调用，天然支持替换 —— 不依赖前台、不 hook 系统 DLL、不碰窗口。

用法:
    python hook_gks_slot.py PID            # 注入（ALT/E 永久按下）
    python hook_gks_slot.py PID --unhook   # 恢复槽
    python hook_gks_slot.py PID --pulse    # 脉冲：写触发标志触发一次 0→1→0
"""
import ctypes
import ctypes.wintypes as wt
import struct
import sys
import time

kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

PROCESS_ALL_ACCESS = 0x1F0FFF
MEM_COMMIT = 0x1000
MEM_RESERVE = 0x2000
PAGE_EXECUTE_READWRITE = 0x40
PAGE_READWRITE = 0x04

SLOT = 0x10184280        # galaxy2d GetKeyState 函数指针槽
VK_MENU, VK_E = 0x12, 0x45


def wpm(h, addr, data):
    rd = ctypes.c_size_t(0)
    ok = kernel32.WriteProcessMemory(h, ctypes.c_void_p(addr), data, len(data), ctypes.byref(rd))
    if not ok or rd.value != len(data):
        raise RuntimeError(f'WPM @0x{addr:08X} err={kernel32.GetLastError()}')
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


def build_fake(orig_slot, pulse):
    """伪造 GetKeyState：ALT/E → 0x8000；其它键跳原函数。pulse 模式读触发标志。"""
    c = b''
    c += b'\x55\x8B\xEC'                                  # push ebp; mov ebp,esp
    c += b'\x8B\x45\x08'                                  # mov eax,[ebp+8] (vk)
    if pulse:
        # 先查触发标志 [orig_slot+4]；=1 才伪造按下
        c += b'\xA0' + struct.pack('<I', orig_slot + 4)   # mov al,[flag]
        c += b'\x84\xC0'                                  # test al,al
        c += b'\x74\x03'                                  # jz 走原函数
        c += b'\xB8\x00\x80\x00\x00'                      # mov eax,0x8000
        c += b'\xC9\xC2\x04\x00'                          # leave; ret 4
    c += b'\x83\xF8\x12'                                  # cmp eax,0x12 (ALT)
    c += b'\x74\x0C'                                      # je pressed
    c += b'\x83\xF8\x45'                                  # cmp eax,0x45 (E)
    c += b'\x74\x07'                                      # je pressed
    c += b'\x5D'                                          # pop ebp
    c += b'\xFF\x25' + struct.pack('<I', orig_slot)       # jmp [orig_slot] 原函数
    c += b'\x5D'                                          # pressed: pop ebp
    c += b'\xB8\x00\x80\x00\x00'                          # mov eax,0x8000
    c += b'\xC2\x04\x00'                                  # ret 4
    return c


def main():
    pid = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    mode = 'inject'
    pulse = False
    for a in sys.argv[2:]:
        if a == '--unhook':
            mode = 'unhook'
        elif a == '--pulse':
            pulse = True
    if not pid:
        print('用法: python hook_gks_slot.py PID [--unhook|--pulse]')
        return

    h = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
    if not h:
        print(f'[err] OpenProcess: {kernel32.GetLastError()}'); return
    orig = rd32(h, SLOT)
    print(f'[ok] 槽 0x{SLOT:08X} 原值 = 0x{orig:08X}')

    if mode == 'unhook':
        if orig != 0x77824B20:
            wpm(h, SLOT, struct.pack('<I', 0x77824B20))
            print('[ok] 槽已恢复为 user32!GetKeyState')
        else:
            print('[ok] 槽已是原值')
        kernel32.CloseHandle(h); return

    base = int(kernel32.VirtualAllocEx(h, None, 32, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE)) & 0xFFFFFFFF
    wpm(h, base, struct.pack('<I', orig))            # data: 原函数地址
    if pulse:
        wpm(h, base + 4, struct.pack('<I', 0))       # data: 触发标志
    code = build_fake(base, pulse)
    wpm(h, base + 16, code)
    print(f'[ok] 伪造函数 @0x{base+16:08X} ({len(code)}B)')

    # 改槽（数据段，先保护再写）
    old_prot = wt.DWORD()
    kernel32.VirtualProtectEx(h, ctypes.c_void_p(SLOT), 4, PAGE_READWRITE, ctypes.byref(old_prot))
    wpm(h, SLOT, struct.pack('<I', base + 16))
    kernel32.VirtualProtectEx(h, ctypes.c_void_p(SLOT), 4, old_prot, ctypes.byref(wt.DWORD()))
    print(f'[ok] 槽已重定向: 0x{orig:08X} → 0x{base+16:08X} 校验=0x{rd32(h, SLOT):08X}')

    if pulse:
        print('[pulse] 触发 ALT+E：写 flag=1 → 0.3s → flag=0')
        wpm(h, base + 4, struct.pack('<I', 1))
        time.sleep(0.3)
        wpm(h, base + 4, struct.pack('<I', 0))
    else:
        print('[action] ALT/E 已伪造为永久按下，观察背包！')
        time.sleep(3)
    print('[note] 测完请 --unhook 恢复')
    kernel32.CloseHandle(h)


if __name__ == '__main__':
    main()
