# -*- coding: utf-8 -*-
# GetCursorPos IAT hook：伪造鼠标位置（真后台鼠标，物理光标不动）
# 原理：游戏 newjc.dll 导入 user32!GetCursorPos 做命中检测。把 IAT 槽改指向
#   注入的伪造函数：flag!=0 → 返回伪造坐标(fx,fy)；flag==0 → jmp 原函数透传。
#   游戏读到伪造光标位置 → 命中检测通过；物理光标从未移动。
# 用法:
#   python hook_cursor_pos.py PID [--unhook]      # 注入/恢复（newjc.dll）
#   python hook_cursor_pos.py PID MODULE --unhook # 指定模块（如 ExuiKrnln.dll）
# 数据区地址会写入共享内存 MHXY_CURSOR_HOOK（客户端 hook_cursor_client.py 读取）
import ctypes
import ctypes.wintypes as wt
import struct
import sys
import os

import pefile

kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
psapi = ctypes.WinDLL('psapi', use_last_error=True)

PROCESS_ALL_ACCESS = 0x1F0FFF
MEM_COMMIT = 0x1000
MEM_RESERVE = 0x2000
PAGE_EXECUTE_READWRITE = 0x40
PAGE_READWRITE = 0x04

DLL_FILE = r'G:/00/newjc.dll'
MODULE_NAME = 'newjc.dll'
SHM_NAME = 'MHXY_CURSOR_HOOK'
SHM_SIZE = 64            # 存目标进程数据区地址 (u32) + magic

LAYOUT = {
    'flag': 0,           # data+0:  u32 flag（0=透传, 1=伪造）
    'fx': 4,             # data+4:  i32 伪造X
    'fy': 8,             # data+8:  i32 伪造Y
    'orig': 12,          # data+12: u32 原 GetCursorPos 地址
    'code': 16,          # data+16: 机器码（伪造函数）
}
DATA_SIZE = 16
CODE_CAP = 128


def shm_write(addr):
    """把目标进程数据区地址写入命名共享内存（客户端读取）"""
    try:
        h = kernel32.CreateFileMappingW(
            ctypes.c_void_p(-1), None, 0x04, 0, SHM_SIZE, SHM_NAME)
        if not h:
            return False
        p = kernel32.MapViewOfFile(h, 0x0006, 0, 0, SHM_SIZE)
        if not p:
            return False
        ctypes.memmove(p, struct.pack('<I', addr), 4)
        kernel32.UnmapViewOfFile(p)
        kernel32.CloseHandle(h)
        return True
    except Exception:
        return False


def shm_clear():
    try:
        h = kernel32.OpenFileMappingW(0x0002, False, SHM_NAME)
        if not h:
            return
        p = kernel32.MapViewOfFile(h, 0x0006, 0, 0, SHM_SIZE)
        if p:
            ctypes.memmove(p, struct.pack('<I', 0), 4)
            kernel32.UnmapViewOfFile(p)
        kernel32.CloseHandle(h)
    except Exception:
        pass


def find_module_base(pid, name_b):
    h = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
    if not h:
        raise RuntimeError('OpenProcess: {0}'.format(ctypes.get_last_error()))
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


def get_module_export(pid, module_name, func_name):
    mod_base = find_module_base(pid, module_name.lower().encode())
    if not mod_base:
        raise RuntimeError('未找到 {0}'.format(module_name))
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
        raise RuntimeError('未找到导出 {0}'.format(func_name))
    return mod_base, (mod_base + rva) & 0xFFFFFFFF


def wpm(h, addr, data):
    rd = ctypes.c_size_t(0)
    ok = kernel32.WriteProcessMemory(h, ctypes.c_void_p(addr), data, len(data), ctypes.byref(rd))
    if not ok or rd.value != len(data):
        raise RuntimeError('WriteProcessMemory 失败 @0x{0:08X} err={1}'.format(addr, ctypes.get_last_error()))
    chk = ctypes.create_string_buffer(len(data))
    r2 = ctypes.c_size_t(0)
    kernel32.ReadProcessMemory(h, ctypes.c_void_p(addr), chk, len(data), ctypes.byref(r2))
    if chk.raw != data:
        raise RuntimeError('写入校验失败 @0x{0:08X}'.format(addr))
    return True


def build_fake(data_addr):
    """伪造 GetCursorPos(OUT LPPOINT pt)->BOOL：
    if flag: pt->x=fx; pt->y=fy; return 1
    else:    jmp [orig]
    """
    flag = (data_addr + LAYOUT['flag']) & 0xFFFFFFFF
    fx = (data_addr + LAYOUT['fx']) & 0xFFFFFFFF
    fy = (data_addr + LAYOUT['fy']) & 0xFFFFFFFF
    orig_slot = (data_addr + LAYOUT['orig']) & 0xFFFFFFFF

    c = b''
    c += b'\x55'                                   # push ebp
    c += b'\x8B\xEC'                               # mov ebp, esp
    c += b'\xA1' + struct.pack('<I', flag)         # mov eax, [flag]
    c += b'\x85\xC0'                               # test eax, eax
    c += b'\x74\x23'                               # je +35 -> passthru
    c += b'\x8B\x4D\x08'                           # mov ecx, [ebp+8] (pt)
    c += b'\xA1' + struct.pack('<I', fx)           # mov eax, [fx]
    c += b'\x89\x01'                               # mov [ecx], eax
    c += b'\xA1' + struct.pack('<I', fy)           # mov eax, [fy]
    c += b'\x89\x41\x04'                           # mov [ecx+4], eax
    c += b'\x5D'                                   # pop ebp
    c += b'\xB8\x01\x00\x00\x00'                   # mov eax, 1
    c += b'\xC2\x04\x00'                           # ret 4
    # passthru:
    c += b'\x5D'                                   # pop ebp
    c += b'\xFF\x25' + struct.pack('<I', orig_slot)  # jmp [orig]
    c += b'\xC2\x04\x00'                           # ret 4 (unreachable)
    return c


def main():
    args = sys.argv[1:]
    if not args:
        print('用法: python hook_cursor_pos.py PID [MODULE] [--unhook]')
        return
    pid = int(args[0])
    module = MODULE_NAME
    mode = 'inject'
    for a in args[1:]:
        if a == '--unhook':
            mode = 'unhook'
        elif a.lower().endswith('.dll') or a.lower().endswith('.exe'):
            module = a

    mod_base = find_module_base(pid, module.lower().encode())
    if not mod_base:
        print('[err] 进程内未找到 {0}'.format(module))
        return
    print('[ok] {0} base=0x{1:08X}'.format(module, mod_base))

    iat_rva, dll = find_iat_slot(DLL_FILE if module == 'newjc.dll' else module, 'GetCursorPos')
    if iat_rva is None:
        print('[err] {0} 未导入 GetCursorPos'.format(module))
        return
    slot_abs = (mod_base + iat_rva) & 0xFFFFFFFF
    print('[info] GetCursorPos IAT 槽 = 0x{0:08X} (来自 {1})'.format(slot_abs, dll))

    h = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
    if not h:
        print('[err] OpenProcess: {0}'.format(ctypes.get_last_error()))
        return
    rd = ctypes.c_size_t(0)
    orig_val = ctypes.create_string_buffer(4)
    kernel32.ReadProcessMemory(h, ctypes.c_void_p(slot_abs), orig_val, 4, ctypes.byref(rd))
    orig_addr = struct.unpack('<I', orig_val.raw)[0]

    if mode == 'unhook':
        try:
            _, orig_true = get_module_export(pid, 'user32.dll', 'GetCursorPos')
        except Exception:
            orig_true = orig_addr
        if orig_addr != orig_true:
            kernel32.VirtualProtectEx(h, ctypes.c_void_p(slot_abs), 4, PAGE_READWRITE, ctypes.byref(wt.DWORD()))
            wpm(h, slot_abs, struct.pack('<I', orig_true))
            kernel32.VirtualProtectEx(h, ctypes.c_void_p(slot_abs), 4, PAGE_READWRITE, ctypes.byref(wt.DWORD()))
            print('[ok] IAT 槽已恢复: 0x{0:08X}'.format(orig_true))
        else:
            print('[ok] 槽已是原值')
        shm_clear()
        kernel32.CloseHandle(h)
        return

    print('[info] 槽当前值 = 0x{0:08X}'.format(orig_addr))

    # 分配目标进程数据区: DATA_SIZE + CODE_CAP（RWX）
    total = DATA_SIZE + CODE_CAP
    base = kernel32.VirtualAllocEx(h, None, total, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE)
    if not base:
        print('[err] VirtualAllocEx: {0}'.format(ctypes.get_last_error()))
        kernel32.CloseHandle(h)
        return
    base = int(base) & 0xFFFFFFFF
    data_addr = base
    code_addr = base + DATA_SIZE
    print('[info] 数据区 @ 0x{0:08X}, code @ 0x{1:08X}'.format(data_addr, code_addr))

    # 初始化数据区: flag=0, fx=0, fy=0, orig=原地址
    wpm(h, data_addr, struct.pack('<IiiI', 0, 0, 0, orig_addr))
    # 写机器码
    fake = build_fake(data_addr)
    assert len(fake) <= CODE_CAP, '伪造函数超长 {0}'.format(len(fake))
    wpm(h, code_addr, fake)
    print('[ok] 伪造函数 {0}B: {1}'.format(len(fake), fake.hex(' ')))

    # 重定向 IAT 槽
    kernel32.VirtualProtectEx(h, ctypes.c_void_p(slot_abs), 4, PAGE_READWRITE, ctypes.byref(wt.DWORD()))
    wpm(h, slot_abs, struct.pack('<I', code_addr))
    kernel32.VirtualProtectEx(h, ctypes.c_void_p(slot_abs), 4, PAGE_READWRITE, ctypes.byref(wt.DWORD()))
    chk = ctypes.create_string_buffer(4)
    kernel32.ReadProcessMemory(h, ctypes.c_void_p(slot_abs), chk, 4, ctypes.byref(rd))
    print('[ok] IAT 槽重定向: 0x{0:08X} → 0x{1:08X} (校验 0x{2:08X})'.format(
        orig_addr, code_addr, struct.unpack('<I', chk.raw)[0]))

    # 数据区地址写入共享内存（客户端读取）
    if shm_write(data_addr):
        print('[ok] 数据区地址已写入共享内存 {0} = 0x{1:08X}'.format(SHM_NAME, data_addr))
    else:
        print('[warn] 共享内存写入失败（客户端将无法联动）')

    print('[action] hook 生效！flag@{0:08X} fx@{1:08X} fy@{2:08X}'.format(
        data_addr, data_addr + 4, data_addr + 8))
    print('[note] 客户端写 flag=1,fx,fy → 游戏读到伪造光标（物理光标不动）')
    print('[note] 测完: python hook_cursor_pos.py {0} --unhook'.format(pid))
    kernel32.CloseHandle(h)


if __name__ == '__main__':
    main()
