# -*- coding: utf-8 -*-
"""PostMessage 后台按键测试：直接向游戏窗口消息队列投递 WM_KEYDOWN/UP。

原理：游戏输入走标准窗口消息循环（newjc.dll GetMessageA/PeekMessageA），
PostMessage 不经过前台焦点，后台窗口也能收到 —— 真正"不抢前台"。

用法:
    python postmsg_key_test.py 2116            # 对 PID 发一次 ALT+E
    python postmsg_key_test.py 2116 --loop 3   # 每 2 秒循环 3 次
"""
import ctypes
import ctypes.wintypes as wt
import sys
import time

user32 = ctypes.WinDLL('user32', use_last_error=True)
k32 = ctypes.WinDLL('kernel32', use_last_error=True)

WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
VK_MENU = 0x12      # ALT
VK_E = 0x45

# 扫描码：ALT=0x38, E=0x12
SC_ALT, SC_E = 0x38, 0x12

def find_hwnd(pid):
    """枚举顶层窗口，按 PID 匹配"""
    found = []
    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    user32.GetWindowThreadProcessId.restype = wt.DWORD

    def cb(hwnd, lparam):
        tid = user32.GetWindowThreadProcessId(hwnd, ctypes.byref(ctypes.c_ulong()))
        pid_ = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid_))
        if pid_.value == pid:
            buf = ctypes.create_string_buffer(256)
            user32.GetWindowTextA(hwnd, buf, 256)
            title = buf.value.decode('gbk', 'ignore')
            vis = user32.IsWindowVisible(hwnd)
            found.append((int(hwnd), title, bool(vis)))
        return True
    user32.EnumWindows(EnumWindowsProc(cb), 0)
    return found


def send_key(hwnd, vk, scan, down, sync=False, syskey=False):
    """发送键盘消息。ALT 组合键必须用 WM_SYSKEYDOWN/UP（0x104/0x105）——真实系统消息！

    关键（2026-08-10 实测教训）：ALT 按下时按键消息全部变 SYSKEY 系列，
    游戏快捷键（ALT+E）只处理 SYSKEY，WM_KEYDOWN 会被忽略。
    """
    if down:
        lparam = (scan << 16) | 1          # repeat=1, prev=0, trans=0
        msg = WM_SYSKEYDOWN if syskey else WM_KEYDOWN
    else:
        lparam = (scan << 16) | 0xC0000001  # prev=1, trans=1
        msg = WM_SYSKEYUP if syskey else WM_KEYUP
    if sync:
        user32.SendMessageA(wt.HWND(hwnd), msg, vk, lparam)
    else:
        user32.PostMessageA(wt.HWND(hwnd), msg, vk, lparam)


def press_alt_e(hwnd, hold_ms=80, sync=False):
    """ALT down → (hold) → E down → (hold) → E up → ALT up（全走 WM_SYSKEY 系列）"""
    send_key(hwnd, VK_MENU, SC_ALT, True, sync, syskey=True)     # ALT down (SYSKEY)
    time.sleep(hold_ms / 1000.0)
    send_key(hwnd, VK_E, SC_E, True, sync, syskey=True)          # E down (SYSKEY)
    time.sleep(hold_ms / 1000.0)
    send_key(hwnd, VK_E, SC_E, False, sync, syskey=True)         # E up (SYSKEY)
    time.sleep(hold_ms / 1000.0)
    send_key(hwnd, VK_MENU, SC_ALT, False, sync, syskey=True)    # ALT up (SYSKEY)


def main():
    pid = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    loop = 1
    sync = False
    args = sys.argv[2:]
    for i, a in enumerate(args):
        if a == '--loop' and i + 1 < len(args):
            loop = int(args[i + 1])
        elif a.startswith('--loop='):
            loop = int(a.split('=', 1)[1])
        elif a == '--sync':
            sync = True
    if not pid:
        print('用法: python postmsg_key_test.py PID [--loop=N] [--sync]')
        return

    wins = find_hwnd(pid)
    if not wins:
        print(f'[err] PID {pid} 没有顶层窗口')
        return
    print(f'[ok] PID {pid} 窗口:')
    for hwnd, title, vis in wins:
        print(f'  hwnd=0x{hwnd:08X} visible={vis} title=[{title}]')
    # 选可见的主窗口（标题含"鲜衣怒马"或面积最大的）
    main = None
    for hwnd, title, vis in wins:
        if '鲜衣怒马' in title:
            main = hwnd
            break
    if main is None:
        main = wins[0][0]
    mode_txt = 'SendMessage(同步,直接调WndProc)' if sync else 'PostMessage(异步,进队列)'
    print(f'[action] 向 0x{main:08X} 注入 ALT+E（共 {loop} 次，{mode_txt}，不抢前台）')
    for i in range(loop):
        press_alt_e(main, sync=sync)
        print(f'  [{i+1}/{loop}] ALT+E 已投递（hold=80ms）')
        if i < loop - 1:
            time.sleep(2)


if __name__ == '__main__':
    main()
