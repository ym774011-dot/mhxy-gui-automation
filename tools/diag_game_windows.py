# -*- coding: utf-8 -*-
"""diag_game_windows.py — 诊断：游戏进程与窗口类名实际长什么样。只读。"""
import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

GAME_EXES = ("胖子西游", "快乐西游", "十年一梦")


def pid_exe(pid):
    """进程 exe 全路径的文件名（失败返回 ''）。"""
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(512)
        size = wintypes.DWORD(len(buf))
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            import os
            return os.path.basename(buf.value)
        return ""
    finally:
        kernel32.CloseHandle(h)


def main():
    rows = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, lp):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value:
            n = user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            cls = ctypes.create_unicode_buffer(64)
            user32.GetClassNameW(hwnd, cls, 64)
            rows.append((pid.value, hwnd, cls.value, buf.value,
                         bool(user32.IsWindowVisible(hwnd))))
        return True

    user32.EnumWindows(cb, 0)

    game_pids = {}
    for pid, hwnd, cls, title, vis in rows:
        exe = pid_exe(pid)
        if any(g in exe for g in GAME_EXES):
            game_pids.setdefault(pid, exe)

    print("游戏进程: %d 个" % len(game_pids))
    for pid, exe in sorted(game_pids.items()):
        print("  PID=%-6d exe=%s" % (pid, exe))
    if not game_pids:
        print("  （游戏没开，或 exe 名不含 %s —— 若都不符，把上面进程名告诉我）" % (GAME_EXES,))
        return 0

    print("\n这些进程的可见窗口（顶层 + 子窗口）:")
    game_rows = [r for r in rows if r[0] in game_pids and r[4]]
    for pid, hwnd, cls, title, vis in game_rows:
        print("  顶层 PID=%-6d hwnd=%-9d class=%-18s title=%r" % (pid, hwnd, cls, title[:44]))
        child_rows = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        def ccb(h, _):
            cpid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(h, ctypes.byref(cpid))
            ccls = ctypes.create_unicode_buffer(64)
            user32.GetClassNameW(h, ccls, 64)
            n = user32.GetWindowTextLengthW(h)
            cbuf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(h, cbuf, n + 1)
            child_rows.append((cpid.value, h, ccls.value, cbuf.value,
                               bool(user32.IsWindowVisible(h))))
            return True

        user32.EnumChildWindows(hwnd, ccb, None)
        for cpid, h, ccls, ctitle, cvis in child_rows:
            if cvis and (ccls == "Galaxy2DEngine" or ctitle):
                print("    子窗 PID=%-6d hwnd=%-9d class=%-18s title=%r"
                      % (cpid, h, ccls, ctitle[:44]))
    return 0


if __name__ == "__main__":
    main()
