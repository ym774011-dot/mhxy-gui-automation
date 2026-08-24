# -*- coding: utf-8 -*-
"""
⚠️⚠️⚠️ 已废弃（2026-08-16）⚠️⚠️⚠️
# newjc.dll 是易语言时代遗留的 UI 封装，运行时【不加载】——
# 游戏进程只加载 galaxy2d.dll + lua51.dll + luahp.dll。hook 它无效。
# 真后台方案最终结论：纯 PostMessage 是唯一可行方案。

# 历史实现（勿运行）:
newjc.dll IAT hook —— 真后台鼠标 + 键盘（2026-08-16 重构版）

背景：Ghidra 逆向确认 newjc.dll 是游戏 UI/输入层，静态导入 GetCursorPos /
GetKeyState / WindowFromPoint / DrawTextA。IAT 槽落在 .rdata（导入表区，可写），
是真正的可劫持目标（之前 galaxy2d 内存扫描误改 DATA 节指针导致闪退的教训）。

原理：
  - 把 newjc.dll 的 GetCursorPos IAT 槽改指向注入的伪造函数
  - 伪造函数读共享内存 flag/fx/fy：flag!=0 → 返回伪造坐标（物理光标不动）
  - flag==0 → jmp 原函数透传（日常零干扰）
  - GetKeyState 同理（fake_keystate：flag!=0 → 返回伪造按键状态）

用法：
  python tools/hook_newjc.py <PID>              # 注入
  python tools/hook_newjc.py <PID> --unhook     # 恢复
  python tools/hook_newjc.py <PID> --status     # 查看状态

客户端联动：tools/hook_newjc_client.py（input_controller 通过它写伪造坐标/按键）
"""
import ctypes
import ctypes.wintypes as wt
import struct
import sys
import time
import os

import pefile

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
psapi = ctypes.WinDLL("psapi", use_last_error=True)

PROCESS_ALL_ACCESS = 0x1F0FFF
MEM_COMMIT = 0x1000
MEM_RESERVE = 0x2000
PAGE_EXECUTE_READWRITE = 0x40
PAGE_READWRITE = 0x04

# newjc.dll 的 IAT 槽 RVA（Ghidra + pefile 静态解析确认，全部落在 .rdata）
IAT_RVAS = {
    "GetCursorPos": 0x0007F394,
    "GetKeyState": 0x0007F4CC,
    "WindowFromPoint": 0x0007F470,
    "DrawTextA": 0x0007F510,
}
DLL_NAME = "newjc.dll"
GAME_EXE = b"\xca\xae\xc4\xea\xd2\xbb\xc3\xce"  # 十年一梦 (GBK)

# 数据区布局（注入进程内 VirtualAlloc）:
# +0x00 flag_cursor (u32)  +0x04 fx (i32)  +0x08 fy (i32)
# +0x0C flag_key (u32)     +0x10 vk (i32)  +0x14 key_state (i32)
# +0x18 orig_GetCursorPos (u32)  +0x1C orig_GetKeyState (u32)
DATA_SIZE = 0x20
CODE_OFFSET = 0x100   # 代码区在数据区之后


def find_game_pids():
    """枚举所有游戏进程 PID（十年一梦.exe，GBK 名）"""
    out = []
    for pid in range(0, 65536):
        h = kernel32.OpenProcess(0x0400 | 0x0010, False, pid)  # QUERY|VM_READ
        if not h:
            continue
        buf = ctypes.create_string_buffer(256)
        ok = psapi.GetModuleBaseNameA(h, None, buf, 256)
        if ok and GAME_EXE in buf.value:
            out.append(pid)
        kernel32.CloseHandle(h)
    return out


def find_module_base(pid, name_b):
    """进程内模块基址"""
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
    """进程内 user32!func 真实地址"""
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


def build_fake_cursor(data_addr, code_addr):
    """
    伪造 GetCursorPos(LPPOINT pt) -> BOOL, stdcall 1 arg, ret 4
    flag_cursor != 0 -> *pt = (fx, fy); eax=1
    否则 jmp [data+0x18] (orig GetCursorPos)
    """
    c = b""
    c += b"\x55"                                        # push ebp
    c += b"\x8B\xEC"                                    # mov ebp, esp
    c += b"\xA1" + struct.pack("<I", data_addr)         # mov eax, [flag_cursor]
    c += b"\x85\xC0"                                    # test eax, eax
    c += b"\x74\x2A"                                    # je +42 (pass-through)
    c += b"\x8B\x4D\x08"                                # mov ecx, [ebp+8] (pt)
    c += b"\xA1" + struct.pack("<I", data_addr + 4)     # mov eax, [fx]
    c += b"\x89\x01"                                    # mov [ecx], eax
    c += b"\xA1" + struct.pack("<I", data_addr + 8)     # mov eax, [fy]
    c += b"\x89\x41\x04"                                # mov [ecx+4], eax
    c += b"\x5D"                                        # pop ebp
    c += b"\xB8\x01\x00\x00\x00"                        # mov eax, 1 (TRUE)
    c += b"\xC2\x04\x00"                                # ret 4
    # pass-through
    c += b"\x5D"                                        # pop ebp
    c += b"\xFF\x25" + struct.pack("<I", data_addr + 0x18)  # jmp [orig_GetCursorPos]
    c += b"\xC2\x04\x00"                                # ret 4 (fallback)
    return c


def build_fake_keystate(data_addr, code_addr):
    """
    伪造 GetKeyState(int vk) -> SHORT, stdcall 1 arg, ret 4
    flag_key != 0 && vk == fake_vk -> return key_state
    否则 jmp [data+0x1C] (orig GetKeyState)
    """
    c = b""
    c += b"\x55"                                        # push ebp
    c += b"\x8B\xEC"                                    # mov ebp, esp
    c += b"\xA1" + struct.pack("<I", data_addr + 0x0C)  # mov eax, [flag_key]
    c += b"\x85\xC0"                                    # test eax, eax
    c += b"\x74\x1E"                                    # je +30 (pass-through)
    c += b"\x8B\x45\x08"                                # mov eax, [ebp+8] (vk)
    c += b"\x3B\x05" + struct.pack("<I", data_addr + 0x10)  # cmp eax, [fake_vk]
    c += b"\x75\x12"                                    # jne +18 (pass-through)
    c += b"\x66\xA1" + struct.pack("<I", data_addr + 0x14)  # mov ax, [key_state]
    c += b"\x5D"                                        # pop ebp
    c += b"\xC2\x04\x00"                                # ret 4
    # pass-through
    c += b"\x5D"                                        # pop ebp
    c += b"\xFF\x25" + struct.pack("<I", data_addr + 0x1C)  # jmp [orig_GetKeyState]
    c += b"\xC2\x04\x00"                                # ret 4
    return c


def inject(pid):
    h = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
    if not h:
        print("[err] OpenProcess 失败, 请以管理员身份运行")
        return False

    nbase = find_module_base(pid, b"newjc.dll")
    if not nbase:
        print("[err] 进程内未找到 newjc.dll（游戏没开？或版本不同）")
        kernel32.CloseHandle(h)
        return False
    print(f"[ok] newjc.dll base=0x{nbase:08X}")

    # 校验 IAT 槽当前值 = user32! 真实地址（防误改 DATA）
    orig_gc = get_user32_export(pid, b"GetCursorPos")
    orig_ks = get_user32_export(pid, b"GetKeyState")
    gc_slot = (nbase + IAT_RVAS["GetCursorPos"]) & 0xFFFFFFFF
    ks_slot = (nbase + IAT_RVAS["GetKeyState"]) & 0xFFFFFFFF
    cur_gc = read32(h, gc_slot)
    cur_ks = read32(h, ks_slot)
    print(f"[info] GetCursorPos 槽=0x{gc_slot:08X} 当前=0x{cur_gc:08X} 期望=0x{orig_gc:08X} {'OK' if cur_gc==orig_gc else 'MISMATCH!'}")
    print(f"[info] GetKeyState  槽=0x{ks_slot:08X} 当前=0x{cur_ks:08X} 期望=0x{orig_ks:08X} {'OK' if cur_ks==orig_ks else 'MISMATCH!'}")
    if cur_gc != orig_gc or cur_ks != orig_ks:
        print("[err] IAT 槽值不匹配期望（可能已被 hook 或版本变化），中止")
        kernel32.CloseHandle(h)
        return False

    # 分配内存：数据区 + 代码区
    total = CODE_OFFSET + 0x200
    base = kernel32.VirtualAllocEx(h, None, total, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE)
    if not base:
        print(f"[err] VirtualAllocEx 失败 err={ctypes.get_last_error()}")
        kernel32.CloseHandle(h)
        return False
    base = int(base) & 0xFFFFFFFF
    data_addr = base
    code_addr = base + CODE_OFFSET
    print(f"[ok] 注入区 base=0x{base:08X} data=0x{data_addr:08X} code=0x{code_addr:08X}")

    # 初始化数据区：flag=0, fx/fy=0, flag_key=0, vk=0, key_state=0, orig 地址
    data = struct.pack("<IiiIiiII", 0, 0, 0, 0, 0, 0, orig_gc, orig_ks)
    rd = ctypes.c_size_t(0)
    kernel32.WriteProcessMemory(h, ctypes.c_void_p(data_addr), data, len(data), ctypes.byref(rd))

    # 写入伪造函数
    fake_gc = build_fake_cursor(data_addr, code_addr)
    fake_ks = build_fake_keystate(data_addr, code_addr)
    kernel32.WriteProcessMemory(h, ctypes.c_void_p(code_addr), fake_gc, len(fake_gc), ctypes.byref(rd))
    kernel32.WriteProcessMemory(h, ctypes.c_void_p(code_addr + 0x100), fake_ks, len(fake_ks), ctypes.byref(rd))
    print(f"[ok] 伪造 GetCursorPos ({len(fake_gc)}B) @0x{code_addr:08X}")
    print(f"[ok] 伪造 GetKeyState  ({len(fake_ks)}B) @0x{code_addr+0x100:08X}")

    # 重定向 IAT 槽
    if not write32(h, gc_slot, code_addr):
        print("[err] 写 GetCursorPos 槽失败")
        kernel32.CloseHandle(h)
        return False
    if not write32(h, ks_slot, code_addr + 0x100):
        print("[err] 写 GetKeyState 槽失败")
        kernel32.CloseHandle(h)
        return False
    # 校验
    if read32(h, gc_slot) != code_addr or read32(h, ks_slot) != code_addr + 0x100:
        print("[err] IAT 重定向校验失败！")
        kernel32.CloseHandle(h)
        return False

    # 把数据区地址写进共享内存（客户端读取）
    try:
        kernel32.CreateFileMappingW.restype = ctypes.c_void_p
        kernel32.MapViewOfFile.restype = ctypes.c_void_p
        shm = kernel32.CreateFileMappingW(
            ctypes.c_void_p(0xFFFFFFFFFFFFFFFF), None, 0x04, 0, 64, "MHXY_NEWJC_HOOK")
        if shm:
            p = kernel32.MapViewOfFile(shm, 0x0006, 0, 0, 64)
            if p:
                ctypes.memmove(p, struct.pack("<I", data_addr), 4)
                kernel32.UnmapViewOfFile(p)
                print(f"[ok] 数据区地址已写入共享内存 MHXY_NEWJC_HOOK")
            kernel32.CloseHandle(shm)
    except Exception as e:
        print(f"[warn] 共享内存写入失败（不影响 hook 本体，客户端需手动传地址）: {e}")

    print(f"[ok] hook 生效！数据区 flag_cursor@{data_addr:08X} fx@{data_addr+4:08X} fy@{data_addr+8:08X} | flag_key@{data_addr+0x0C:08X} vk@{data_addr+0x10:08X} state@{data_addr+0x14:08X}")
    print(f"[note] 测完恢复: python tools/hook_newjc.py {pid} --unhook")
    kernel32.CloseHandle(h)
    return True


def unhook(pid):
    h = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
    if not h:
        print("[err] OpenProcess 失败")
        return
    nbase = find_module_base(pid, b"newjc.dll")
    if not nbase:
        print("[err] 未找到 newjc.dll")
        kernel32.CloseHandle(h)
        return
    orig_gc = get_user32_export(pid, b"GetCursorPos")
    orig_ks = get_user32_export(pid, b"GetKeyState")
    gc_slot = (nbase + IAT_RVAS["GetCursorPos"]) & 0xFFFFFFFF
    ks_slot = (nbase + IAT_RVAS["GetKeyState"]) & 0xFFFFFFFF
    cur_gc = read32(h, gc_slot)
    cur_ks = read32(h, ks_slot)
    restored = 0
    if cur_gc != orig_gc:
        write32(h, gc_slot, orig_gc)
        restored += 1
        print(f"[ok] GetCursorPos 槽恢复 0x{orig_gc:08X}")
    if cur_ks != orig_ks:
        write32(h, ks_slot, orig_ks)
        restored += 1
        print(f"[ok] GetKeyState 槽恢复 0x{orig_ks:08X}")
    if restored == 0:
        print("[ok] 槽已是原值，无需恢复")
    kernel32.CloseHandle(h)


def status(pid):
    h = kernel32.OpenProcess(0x0400 | 0x0010, False, pid)
    if not h:
        print("进程不可访问")
        return
    nbase = find_module_base(pid, b"newjc.dll")
    if not nbase:
        print("未找到 newjc.dll")
        kernel32.CloseHandle(h)
        return
    gc_slot = (nbase + IAT_RVAS["GetCursorPos"]) & 0xFFFFFFFF
    ks_slot = (nbase + IAT_RVAS["GetKeyState"]) & 0xFFFFFFFF
    orig_gc = get_user32_export(pid, b"GetCursorPos")
    orig_ks = get_user32_export(pid, b"GetKeyState")
    cur_gc = read32(h, gc_slot)
    cur_ks = read32(h, ks_slot)
    print(f"GetCursorPos 槽: {'HOOKED' if cur_gc != orig_gc else '正常'}")
    print(f"GetKeyState  槽: {'HOOKED' if cur_ks != orig_ks else '正常'}")
    kernel32.CloseHandle(h)


def main():
    args = sys.argv[1:]
    if not args:
        print("用法: python hook_newjc.py <PID> [--unhook|--status]")
        print("      python hook_newjc.py --auto [--unhook]  # 自动找游戏")
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
            # 遍历所有游戏进程，挑加载了 newjc.dll 的
            picked = None
            for p in pids:
                if find_module_base(p, b"newjc.dll"):
                    picked = p
                    break
            if picked is None:
                print(f"找到 {len(pids)} 个游戏进程，但都没有加载 newjc.dll")
                print("（多开结构：UI 层只在特定进程加载，请确认游戏已进入游戏画面）")
                return
            pid = picked
            print(f"[auto] 找到 {len(pids)} 个游戏进程，选择加载 newjc.dll 的 PID={pid}")
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
