# -*- coding: utf-8 -*-
# 侦察：游戏模块里谁导入了 GetCursorPos（找 IAT 槽）
import ctypes
import ctypes.wintypes as wt
import sys
import os
import pefile

kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
psapi = ctypes.WinDLL('psapi', use_last_error=True)
PROCESS_ALL_ACCESS = 0x1F0FFF


def find_module_base(pid, name_b):
    h = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
    if not h:
        return 0, 0
    needed = wt.DWORD(0)
    psapi.EnumProcessModulesEx(h, None, 0, ctypes.byref(needed), 3)
    count = needed.value // ctypes.sizeof(wt.HMODULE)
    hmods = (wt.HMODULE * count)()
    psapi.EnumProcessModulesEx(h, hmods, needed.value, ctypes.byref(needed), 3)
    psapi.GetModuleBaseNameA.argtypes = [wt.HANDLE, wt.HMODULE, ctypes.c_char_p, wt.DWORD]
    psapi.GetModuleFileNameExA.argtypes = [wt.HANDLE, wt.HMODULE, ctypes.c_char_p, wt.DWORD]
    base = 0
    path = b''
    for i in range(count):
        buf = ctypes.create_string_buffer(64)
        psapi.GetModuleBaseNameA(h, hmods[i], buf, 64)
        pbuf = ctypes.create_string_buffer(512)
        psapi.GetModuleFileNameExA(h, hmods[i], pbuf, 512)
        if buf.value.lower() == name_b:
            base = int(hmods[i]) & 0xFFFFFFFF
            path = pbuf.value
            break
    kernel32.CloseHandle(h)
    return base, path


def scan_imports(path, func):
    if not os.path.exists(path):
        return []
    pe = pefile.PE(path, fast_load=True)
    pe.parse_data_directories()
    out = []
    image_base = pe.OPTIONAL_HEADER.ImageBase
    for entry in getattr(pe, 'DIRECTORY_ENTRY_IMPORT', []):
        for imp in entry.imports:
            if imp.name == func.encode():
                rva = (imp.address - image_base) & 0xFFFFFFFF
                out.append((entry.dll.decode('latin1'), rva))
    pe.close()
    return out


def main():
    pid = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    if not pid:
        print('用法: python _scan_cursor_iat.py PID')
        return
    for mod in [b'newjc.dll', b'galaxy2d.dll', b'g2d.dll', b'ExuiKrnln.dll', '十年一梦.exe'.encode('gbk')]:
        base, path = find_module_base(pid, mod)
        if not base:
            print('[-] {0}: 未加载'.format(mod.decode()))
            continue
        print('[+] {0}: base=0x{1:08X} path={2}'.format(mod.decode(), base, path))
        if not path:
            continue
        # 进程内的模块路径 = 磁盘路径，直接用磁盘文件扫 IAT
        disk = path.decode('utf-8', 'ignore').replace('\\\\', '/')
        hits = scan_imports(disk, 'GetCursorPos')
        if hits:
            for dll, rva in hits:
                print('    GetCursorPos IAT 槽 RVA=0x{0:08X} (来自 {1}) → 绝对=0x{2:08X}'.format(
                    rva, dll, (base + rva) & 0xFFFFFFFF))
        else:
            print('    未导入 GetCursorPos')


if __name__ == '__main__':
    main()
