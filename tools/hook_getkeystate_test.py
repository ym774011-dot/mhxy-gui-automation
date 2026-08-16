# -*- coding: utf-8 -*-
"""GetKeyState IAT hook 测试：伪造 ALT/E 按键状态（不抢前台正解验证）

原理：游戏按键用 GetKeyState（线程键盘状态表）轮询，newjc.dll 导入该函数。
  把 newjc.dll IAT 里的 GetKeyState 槽改指向注入的伪造函数：
    vKey==VK_MENU(0x12) 或 VK_E(0x45) → 返回 0x8000（按下）
    其它键 → jmp 原 GetKeyState
  游戏轮询时读到 ALT/E 按下 → 触发。全程不依赖窗口焦点。

用法:
    python hook_getkeystate_test.py 2116            # 注入（伪造 ALT/E）
    python hook_getkeystate_test.py 2116 --unhook   # 恢复 IAT 槽
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

VK_MENU = 0x12
VK_E = 0x45
DLL_FILE = r'G:/00/newjc.dll'
MODULE_NAME = 'newjc.dll'


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


def find_iat_slot(dll_path, func_name):
    """返回 (IAT槽RVA, 导入dll名) 或 None。imp.address 是 VA（含 ImageBase），必须减回"""
    pe = pefile.PE(dll_path, fast_load=True)
    pe.parse_data_directories()
    image_base = pe.OPTIONAL_HEADER.ImageBase
    for entry in getattr(pe, 'DIRECTORY_ENTRY_IMPORT', []):
        for imp in entry.imports:
            if imp.name == func_name.encode():
                rva = (imp.address - image_base) & 0xFFFFFFFF
                dll = entry.dll.decode('latin1')
                pe.close()
                return rva, dll
    pe.close()
    return None, None


def wpm(h, addr, data):
    """WriteProcessMemory + 严格写入与校验（防地址计算错误时假象）"""
    rd = ctypes.c_size_t(0)
    ok = kernel32.WriteProcessMemory(h, ctypes.c_void_p(addr), data, len(data), ctypes.byref(rd))
    if not ok or rd.value != len(data):
        raise RuntimeError(f'WriteProcessMemory 失败 @0x{addr:08X} err={ctypes.get_last_error()}')
    chk = ctypes.create_string_buffer(len(data))
    r2 = ctypes.c_size_t(0)
    kernel32.ReadProcessMemory(h, ctypes.c_void_p(addr), chk, len(data), ctypes.byref(r2))
    if chk.raw != data:
        raise RuntimeError(f'写入校验失败 @0x{addr:08X}: 写{data.hex()} 读{chk.raw.hex()}')
    return True


def get_module_export(pid, module_name, func_name):
    """找进程内模块基址 + SysWOW64 解析导出函数地址"""
    mod_base = find_module_base(pid, module_name.lower().encode())
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
    return mod_base, (mod_base + rva) & 0xFFFFFFFF


def build_fake(orig_addr_slot_abs):
    """伪造 GetKeyState：vKey==ALT/E → 0x8000；否则 jmp [orig_addr_slot]"""
    c = b''
    c += b'\x55'                                          # push ebp
    c += b'\x8B\xEC'                                      # mov ebp, esp
    c += b'\x8B\x45\x08'                                  # mov eax, [ebp+8]  (vKey)
    c += b'\x83\xF8\x12'                                  # cmp eax, 0x12 (VK_MENU)
    c += b'\x74\x0C'                                      # je +12 → pressed(23)
    c += b'\x83\xF8\x45'                                  # cmp eax, 0x45 (VK_E)
    c += b'\x74\x07'                                      # je +7 → pressed(23)
    c += b'\x5D'                                          # pop ebp
    c += b'\xFF\x25' + struct.pack('<I', orig_addr_slot_abs)  # jmp [orig_addr_slot]
    c += b'\x5D'                                          # pressed: pop ebp
    c += b'\xB8\x00\x80\x00\x00'                          # mov eax, 0x8000
    c += b'\xC2\x04\x00'                                  # ret 4
    return c


def main():
    pid = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    mode = 'inject'
    for a in sys.argv[2:]:
        if a == '--unhook':
            mode = 'unhook'
    if not pid:
        print('用法: python hook_getkeystate_test.py PID [--unhook]')
        return

    mod_base = find_module_base(pid, MODULE_NAME.encode())
    if not mod_base:
        print(f'[err] 进程内未找到 {MODULE_NAME}')
        return
    print(f'[ok] {MODULE_NAME} base=0x{mod_base:08X}')

    iat_rva, dll = find_iat_slot(DLL_FILE, 'GetKeyState')
    if iat_rva is None:
        print('[err] newjc.dll 未导入 GetKeyState')
        return
    slot_abs = (mod_base + iat_rva) & 0xFFFFFFFF
    print(f'[info] GetKeyState IAT 槽 = 0x{slot_abs:08X} (来自 {dll})')

    h = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
    if not h:
        print(f'[err] OpenProcess: {ctypes.get_last_error()}')
        return
    rd = ctypes.c_size_t(0)
    orig_val = ctypes.create_string_buffer(4)
    kernel32.ReadProcessMemory(h, ctypes.c_void_p(slot_abs), orig_val, 4, ctypes.byref(rd))
    orig_addr = struct.unpack('<I', orig_val.raw)[0]
    print(f'[info] 槽当前值(原 GetKeyState) = 0x{orig_addr:08X}')

    if mode == 'unhook':
        # 真值 = user32!GetKeyState（newjc 槽原始指向）；不能读当前值（注入后是伪造地址！）
        cur_v = struct.unpack('<I', orig_val.raw)[0]
        try:
            _, orig_true = get_module_export(pid, 'user32.dll', 'GetKeyState')
        except Exception:
            orig_true = cur_v
        if cur_v != orig_true:
            kernel32.VirtualProtectEx(h, ctypes.c_void_p(slot_abs), 4, PAGE_READWRITE, ctypes.byref(wt.DWORD()))
            wpm(h, slot_abs, struct.pack('<I', orig_true))
            kernel32.VirtualProtectEx(h, ctypes.c_void_p(slot_abs), 4, PAGE_READWRITE, ctypes.byref(wt.DWORD()))
            print(f'[ok] IAT 槽已恢复为真值: 0x{orig_true:08X}')
        else:
            print('[ok] 槽已是原值，无需恢复')
        kernel32.CloseHandle(h)
        return

    # 分配注入区：data(16) + code(64)
    base = kernel32.VirtualAllocEx(h, None, 16 + 64, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE)
    if not base:
        print(f'[err] VirtualAllocEx: {ctypes.get_last_error()}')
        kernel32.CloseHandle(h)
        return
    base = int(base) & 0xFFFFFFFF
    orig_slot_abs = base                      # 存原 GetKeyState 地址
    code_addr = base + 16

    wpm(h, orig_slot_abs, struct.pack('<I', orig_addr))
    fake = build_fake(orig_slot_abs)
    assert len(fake) <= 64, f'伪造函数超长 {len(fake)}'
    wpm(h, code_addr, fake)
    print(f'[ok] 伪造函数 @ 0x{code_addr:08X} ({len(fake)}B): {fake.hex(" ")}')

    # 改 IAT 槽 → 伪造函数（严格校验）
    kernel32.VirtualProtectEx(h, ctypes.c_void_p(slot_abs), 4, PAGE_READWRITE, ctypes.byref(wt.DWORD()))
    wpm(h, slot_abs, struct.pack('<I', code_addr))
    kernel32.VirtualProtectEx(h, ctypes.c_void_p(slot_abs), 4, PAGE_READWRITE, ctypes.byref(wt.DWORD()))
    print(f'[ok] IAT 槽已重定向: 0x{orig_addr:08X} → 0x{code_addr:08X}')

    # 校验
    chk = ctypes.create_string_buffer(4)
    kernel32.ReadProcessMemory(h, ctypes.c_void_p(slot_abs), chk, 4, ctypes.byref(rd))
    print(f'[ok] 校验槽值 = 0x{struct.unpack("<I", chk.raw)[0]:08X}')
    print('[action] 请观察背包！游戏【前后台均可】，ALT/E 已被伪造为按下')
    time.sleep(3)
    print('[note] 如背包已开=正解达成；测完请 --unhook 恢复')
    kernel32.CloseHandle(h)


if __name__ == '__main__':
    main()
