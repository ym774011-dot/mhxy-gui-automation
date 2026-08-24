# -*- coding: utf-8 -*-
"""
⚠️⚠️⚠️ 已废弃（2026-08-16 实测两次均导致游戏崩溃）⚠️⚠️⚠️
# 背景：galaxy2d.dll DATA 段 0x10184224-0x101842BC 是 user32 函数指针表，
# 槽值逐一验证 = user32 真实地址（MATCH），但改指针即导致该进程组崩溃退出
# （两次实测：2904 守护进程 + 6476 主进程）。疑似游戏对指针表有校验/并发读写。
# 结论：galaxy2d 函数指针表不可 hook。真后台鼠标/键盘在该游戏不可行，
# 纯 PostMessage 是唯一可行方案（实测有效）。保留代码仅供逆向研究参考。

# 历史实现（勿运行）:
galaxy2d.dll 函数指针 hook —— 真后台鼠标 + 键盘（2026-08-16 v2）

背景（Ghidra + 运行时验证）：
  galaxy2d.dll 运行时用 GetProcAddress 动态解析 user32 函数，把指针存入
  DATA 段函数指针表（0x10184224-0x101842BC，连续表）。已逐一验证每个槽
  值 = 对应 user32 导出真实地址 —— 这是纯函数指针表，改某项只影响该 API
  的调用，语义安全（区别于上次误改普通数据的闪退事故）。

目标槽（RVA，base=0x10000000 运行时通常不变，但脚本动态获取）：
  +0x184280 GetKeyState    （键盘状态 → 伪造按下）
  +0x184294 GetCursorPos   （鼠标位置 → 伪造坐标，物理光标不动）
  +0x184278 PtInRect       （可选用：让 hover 检测通过）
  +0x18427C WindowFromPoint（可选用）

原理：
  - VirtualAllocEx 分配 RWX 区：伪造函数 + 数据区
  - 数据区 flag/fx/fy 由客户端（hook_galaxy_client.py）通过共享内存写入
  - 把目标槽指针改为伪造函数地址
  - flag=0 时 jmp 原函数透传（零干扰）

用法：
  python tools/hook_galaxy.py --auto                # 自动找游戏并注入
  python tools/hook_galaxy.py --auto --unhook       # 恢复
  python tools/hook_galaxy.py --auto --status       # 查看状态
  python tools/hook_galaxy.py <PID>                 # 指定进程注入
"""
import ctypes
import ctypes.wintypes as wt
import struct
import sys

import pefile

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
psapi = ctypes.WinDLL("psapi", use_last_error=True)

PROCESS_ALL_ACCESS = 0x1F0FFF
MEM_COMMIT = 0x1000
MEM_RESERVE = 0x2000
PAGE_EXECUTE_READWRITE = 0x40
PAGE_READWRITE = 0x04

GALAXY_DLL = b"galaxy2d.dll"
GAME_EXE = b"\xca\xae\xc4\xea\xd2\xbb\xc3\xce"  # 十年一梦 (GBK)

# galaxy2d DATA 函数指针表槽 RVA（已验证 = user32 真实地址）
SLOTS = {
    "GetKeyState":    0x184280,
    "PtInRect":       0x184278,
    "WindowFromPoint": 0x18427C,
    "GetCursorPos":   0x184294,
}

# 数据区布局（注入进程 VirtualAlloc）:
# +0x00 flag_cursor u32   +0x04 fx i32  +0x08 fy i32
# +0x0C flag_key u32      +0x10 vk i32  +0x14 key_state i32
# +0x18 orig_GetCursorPos +0x1C orig_GetKeyState
CODE_OFFSET = 0x100


def find_game_pids():
    out = []
    for pid in range(0, 65536):
        h = kernel32.OpenProcess(0x0400 | 0x0010, False, pid)
        if not h:
            continue
        buf = ctypes.create_string_buffer(256)
        ok = psapi.GetModuleBaseNameA(h, None, buf, 256)
        if ok and GAME_EXE in buf.value:
            out.append(pid)
        kernel32.CloseHandle(h)
    return out


def find_module_base(pid, name_b):
    h = kernel32.OpenProcess(0x0400 | 0x0010, False, pid)
    if not h:
        return 0
    needed = wt.DWORD(0)
    psapi.EnumProcessModulesEx(h, None, 0, ctypes.byref(needed), 3)
    count = needed.value // ctypes.sizeof(wt.HMODULE)
    if count == 0:
        kernel32.CloseHandle(h)
        return 0
    hmods = (wt.HMODULE * count)()
    psapi.EnumProcessModulesEx(h, hmods, needed.value, ctypes.byref(needed), 3)
    psapi.GetModuleBaseNameA.argtypes = [wt.HANDLE, wt.HMODULE, ctypes.c_char_p, wt.DWORD]
    base = 0
    for i in range(count):
        b = ctypes.create_string_buffer(64)
        psapi.GetModuleBaseNameA(h, hmods[i], b, 64)
        if b.value.lower() == name_b:
            base = int(hmods[i]) & 0xFFFFFFFF
            break
    kernel32.CloseHandle(h)
    return base


def get_user32_export(pid, func_name):
    u32 = find_module_base(pid, b"user32.dll")
    if not u32:
        return 0
    try:
        pe = pefile.PE(r"C:/Windows/SysWOW64/user32.dll", fast_load=True)
        pe.parse_data_directories(
            directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_EXPORT"]])
        rva = None
        for exp in pe.DIRECTORY_ENTRY_EXPORT.symbols:
            if exp.name == func_name:
                rva = exp.address
                break
        pe.close()
        if rva is None:
            return 0
        return (u32 + rva) & 0xFFFFFFFF
    except Exception:
        return 0


def read32(h, addr):
    buf = ctypes.create_string_buffer(4)
    rd = ctypes.c_size_t(0)
    if kernel32.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, 4, ctypes.byref(rd)) and rd.value == 4:
        return struct.unpack("<I", buf.raw)[0]
    return None


def write32(h, addr, val):
    rd = ctypes.c_size_t(0)
    old = wt.DWORD()
    kernel32.VirtualProtectEx(h, ctypes.c_void_p(addr), 4, PAGE_READWRITE, ctypes.byref(old))
    ok = kernel32.WriteProcessMemory(h, ctypes.c_void_p(addr), struct.pack("<I", val), 4, ctypes.byref(rd))
    kernel32.VirtualProtectEx(h, ctypes.c_void_p(addr), 4, old.value, ctypes.byref(wt.DWORD()))
    return ok and rd.value == 4


def build_fake_cursor(data_addr):
    """伪造 GetCursorPos(LPPOINT)->BOOL: flag!=0 -> (fx,fy), else jmp orig"""
    c = b""
    c += b"\x55"                                        # push ebp
    c += b"\x8B\xEC"                                    # mov ebp, esp
    c += b"\xA1" + struct.pack("<I", data_addr)         # mov eax, [flag_cursor]
    c += b"\x85\xC0"                                    # test eax, eax
    c += b"\x74\x2A"                                    # je +42
    c += b"\x8B\x4D\x08"                                # mov ecx, [ebp+8]
    c += b"\xA1" + struct.pack("<I", data_addr + 4)     # mov eax, [fx]
    c += b"\x89\x01"                                    # mov [ecx], eax
    c += b"\xA1" + struct.pack("<I", data_addr + 8)     # mov eax, [fy]
    c += b"\x89\x41\x04"                                # mov [ecx+4], eax
    c += b"\x5D"                                        # pop ebp
    c += b"\xB8\x01\x00\x00\x00"                        # mov eax, 1
    c += b"\xC2\x04\x00"                                # ret 4
    c += b"\x5D"                                        # pop ebp
    c += b"\xFF\x25" + struct.pack("<I", data_addr + 0x18)  # jmp [orig]
    c += b"\xC2\x04\x00"
    return c


def build_fake_keystate(data_addr):
    """伪造 GetKeyState(int vk)->SHORT: flag_key && vk==fake_vk -> state, else jmp orig"""
    c = b""
    c += b"\x55"                                        # push ebp
    c += b"\x8B\xEC"                                    # mov ebp, esp
    c += b"\xA1" + struct.pack("<I", data_addr + 0x0C)  # mov eax, [flag_key]
    c += b"\x85\xC0"                                    # test eax, eax
    c += b"\x74\x1E"                                    # je +30
    c += b"\x8B\x45\x08"                                # mov eax, [ebp+8] (vk)
    c += b"\x3B\x05" + struct.pack("<I", data_addr + 0x10)  # cmp eax, [fake_vk]
    c += b"\x75\x12"                                    # jne +18
    c += b"\x66\xA1" + struct.pack("<I", data_addr + 0x14)  # mov ax, [key_state]
    c += b"\x5D"                                        # pop ebp
    c += b"\xC2\x04\x00"                                # ret 4
    c += b"\x5D"                                        # pop ebp
    c += b"\xFF\x25" + struct.pack("<I", data_addr + 0x1C)  # jmp [orig]
    c += b"\xC2\x04\x00"
    return c


def inject(pid):
    h = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
    if not h:
        print("[err] OpenProcess 失败，请以管理员身份运行")
        return False

    gbase = find_module_base(pid, GALAXY_DLL)
    if not gbase:
        print("[err] 进程内未找到 galaxy2d.dll")
        kernel32.CloseHandle(h)
        return False
    print(f"[ok] galaxy2d.dll base=0x{gbase:08X}")

    # 校验槽值
    orig_gc = get_user32_export(pid, b"GetCursorPos")
    orig_ks = get_user32_export(pid, b"GetKeyState")
    gc_slot = (gbase + SLOTS["GetCursorPos"]) & 0xFFFFFFFF
    ks_slot = (gbase + SLOTS["GetKeyState"]) & 0xFFFFFFFF
    cur_gc = read32(h, gc_slot)
    cur_ks = read32(h, ks_slot)
    ok_gc = (cur_gc == orig_gc)
    ok_ks = (cur_ks == orig_ks)
    print(f"[校验] GetCursorPos 槽=0x{gc_slot:08X} 值=0x{cur_gc:08X} 期望=0x{orig_gc:08X} {'OK' if ok_gc else 'MISMATCH!'}")
    print(f"[校验] GetKeyState  槽=0x{ks_slot:08X} 值=0x{cur_ks:08X} 期望=0x{orig_ks:08X} {'OK' if ok_ks else 'MISMATCH!'}")
    if not (ok_gc and ok_ks):
        print("[err] 槽值校验失败（可能已 hook 或游戏版本变化），中止避免破坏")
        kernel32.CloseHandle(h)
        return False

    # 分配内存
    total = CODE_OFFSET + 0x200
    base = kernel32.VirtualAllocEx(h, None, total, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE)
    if not base:
        print(f"[err] VirtualAllocEx 失败 err={ctypes.get_last_error()}")
        kernel32.CloseHandle(h)
        return False
    base = int(base) & 0xFFFFFFFF
    data_addr = base
    code_gc = base + CODE_OFFSET
    code_ks = base + CODE_OFFSET + 0x100
    print(f"[ok] 注入区 base=0x{base:08X} data=0x{data_addr:08X}")

    # 数据区: flag_cursor, fx, fy, flag_key, vk, key_state, orig_gc, orig_ks
    data = struct.pack("<IiiIiiII", 0, 0, 0, 0, 0, 0, orig_gc, orig_ks)
    rd = ctypes.c_size_t(0)
    kernel32.WriteProcessMemory(h, ctypes.c_void_p(data_addr), data, len(data), ctypes.byref(rd))

    # 伪造函数
    fake_gc = build_fake_cursor(data_addr)
    fake_ks = build_fake_keystate(data_addr)
    kernel32.WriteProcessMemory(h, ctypes.c_void_p(code_gc), fake_gc, len(fake_gc), ctypes.byref(rd))
    kernel32.WriteProcessMemory(h, ctypes.c_void_p(code_ks), fake_ks, len(fake_ks), ctypes.byref(rd))
    print(f"[ok] 伪造 GetCursorPos ({len(fake_gc)}B) @0x{code_gc:08X}")
    print(f"[ok] 伪造 GetKeyState  ({len(fake_ks)}B) @0x{code_ks:08X}")

    # 改指针
    if not (write32(h, gc_slot, code_gc) and write32(h, ks_slot, code_ks)):
        print("[err] 写指针失败")
        kernel32.CloseHandle(h)
        return False
    if read32(h, gc_slot) != code_gc or read32(h, ks_slot) != code_ks:
        print("[err] 指针重定向校验失败")
        kernel32.CloseHandle(h)
        return False

    # 共享内存（客户端联动）
    try:
        kernel32.CreateFileMappingW.restype = ctypes.c_void_p
        kernel32.MapViewOfFile.restype = ctypes.c_void_p
        shm = kernel32.CreateFileMappingW(
            ctypes.c_void_p(0xFFFFFFFFFFFFFFFF), None, 0x04, 0, 64, "MHXY_GALAXY_HOOK")
        if shm:
            p = kernel32.MapViewOfFile(shm, 0x0006, 0, 0, 64)
            if p:
                ctypes.memmove(p, struct.pack("<I", data_addr), 4)
                kernel32.UnmapViewOfFile(p)
                print("[ok] 数据区地址已写入共享内存 MHXY_GALAXY_HOOK")
            kernel32.CloseHandle(shm)
    except Exception as e:
        print(f"[warn] 共享内存写入失败: {e}")

    print(f"[ok] hook 生效！")
    print(f"[ok]   cursor: flag@{data_addr:08X} fx@{data_addr+4:08X} fy@{data_addr+8:08X}")
    print(f"[ok]   keystate: flag@{data_addr+0x0C:08X} vk@{data_addr+0x10:08X} state@{data_addr+0x14:08X}")
    print(f"[note] 恢复: python tools/hook_galaxy.py {pid} --unhook")
    kernel32.CloseHandle(h)
    return True


def unhook(pid):
    h = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
    if not h:
        print("[err] OpenProcess 失败")
        return
    gbase = find_module_base(pid, GALAXY_DLL)
    if not gbase:
        print("[err] 未找到 galaxy2d.dll")
        kernel32.CloseHandle(h)
        return
    orig_gc = get_user32_export(pid, b"GetCursorPos")
    orig_ks = get_user32_export(pid, b"GetKeyState")
    gc_slot = (gbase + SLOTS["GetCursorPos"]) & 0xFFFFFFFF
    ks_slot = (gbase + SLOTS["GetKeyState"]) & 0xFFFFFFFF
    n = 0
    if read32(h, gc_slot) != orig_gc:
        write32(h, gc_slot, orig_gc)
        print(f"[ok] GetCursorPos 恢复 0x{orig_gc:08X}")
        n += 1
    if read32(h, ks_slot) != orig_ks:
        write32(h, ks_slot, orig_ks)
        print(f"[ok] GetKeyState 恢复 0x{orig_ks:08X}")
        n += 1
    if n == 0:
        print("[ok] 槽已是原值")
    kernel32.CloseHandle(h)


def status(pid):
    h = kernel32.OpenProcess(0x0400 | 0x0010, False, pid)
    if not h:
        print("进程不可访问")
        return
    gbase = find_module_base(pid, GALAXY_DLL)
    if not gbase:
        print("未找到 galaxy2d.dll")
        kernel32.CloseHandle(h)
        return
    orig_gc = get_user32_export(pid, b"GetCursorPos")
    orig_ks = get_user32_export(pid, b"GetKeyState")
    gc = read32(h, (gbase + SLOTS["GetCursorPos"]) & 0xFFFFFFFF)
    ks = read32(h, (gbase + SLOTS["GetKeyState"]) & 0xFFFFFFFF)
    print(f"GetCursorPos: {'HOOKED' if gc != orig_gc else '正常'}")
    print(f"GetKeyState : {'HOOKED' if ks != orig_ks else '正常'}")
    kernel32.CloseHandle(h)


def main():
    args = sys.argv[1:]
    if not args:
        print("用法: python hook_galaxy.py --auto [--unhook|--status]")
        print("      python hook_galaxy.py <PID> [--unhook|--status]")
        return
    mode = "inject"
    pid = None
    for a in args:
        if a == "--unhook":
            mode = "unhook"
        elif a == "--status":
            mode = "status"
        elif a == "--auto":
            pids = find_game_pids()
            if not pids:
                print("未找到运行中的游戏进程")
                return
            # 只匹配加载 galaxy2d.dll 的主程序（排除多开器/守护进程）
            picked = None
            for p in pids:
                if find_module_base(p, GALAXY_DLL):
                    # 确认 exe 是主程序（含 galaxy2d 且不是多开器）
                    hh = kernel32.OpenProcess(0x0400 | 0x0010, False, p)
                    if hh:
                        buf = ctypes.create_string_buffer(512)
                        psapi.GetModuleFileNameExA(hh, None, buf, 512)
                        kernel32.CloseHandle(hh)
                        pth = buf.value.decode('utf-8', 'ignore').lower()
                        if 'galaxy' in pth or ('game.exe' in pth) or ('\\' not in pth and pth):
                            picked = p
                            break
            if picked is None:
                # 兜底：取第一个加载 galaxy2d 的
                for p in pids:
                    if find_module_base(p, GALAXY_DLL):
                        picked = p
                        break
            if picked is None:
                print(f"找到 {len(pids)} 个游戏进程，均未加载 galaxy2d.dll（请确认进入游戏画面）")
                return
            pid = picked
            print(f"[auto] 选择 PID={pid}（加载 galaxy2d 的主进程）")
        elif a.isdigit():
            pid = int(a)
    if pid is None:
        print("需要 PID 或 --auto")
        return
    if mode == "inject":
        inject(pid)
    elif mode == "unhook":
        unhook(pid)
    elif mode == "status":
        status(pid)


if __name__ == "__main__":
    main()
