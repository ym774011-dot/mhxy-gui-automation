# -*- coding: utf-8 -*-
"""
win_utils - 游戏窗口查找 / 坐标转换公共模块
=============================================
从 9 个地图函数包（ALG/BXG/CAC/CSC/DHW/JNYW/JYC/XLNR/ZZG）中抽取的
重复代码，统一收口到这里，消除 36 份复制粘贴。

原重复函数（每个地图包 4 份 × 9 包）：
  - _find_game_window(pid)      : 按 PID 找游戏窗口句柄
  - _find_game_pids()           : 枚举所有'十年一梦.exe'进程 PID
  - _locate_game_window(pid)    : 定位游戏主窗口（PID 失效时自动兜底枚举）
  - _client_to_screen(hwnd, x, y) : 客户区坐标 → 屏幕绝对坐标

差异说明：
  - 原各包仅打印日志前缀不同（[DHW] / [JNYW]），逻辑 100% 相同
  - 公共版用 tag 参数模拟该差异（默认空 = 原 7 包行为）

依赖：纯 ctypes，无第三方库。地图函数包通过
  from library.common.win_utils import find_game_window, ...
直接使用。
"""
import ctypes
from ctypes import wintypes

# ============================================================
# Win32 API（与地图包顶部定义保持一致）
# ============================================================
user32 = ctypes.WinDLL('user32', use_last_error=True)

HWND = wintypes.HWND
LPARAM = wintypes.LPARAM
BOOL = wintypes.BOOL
DWORD = wintypes.DWORD


class POINT(ctypes.Structure):
    _fields_ = [('x', ctypes.c_long), ('y', ctypes.c_long)]


WNDENUMPROC = ctypes.WINFUNCTYPE(BOOL, HWND, LPARAM)

# 游戏主窗口标题特征字（与 JHRW 一致）
GAME_TITLE_KEYWORDS = ('鲜衣', '一梦', '梦幻', '十年')


def find_game_window(pid):
    """通过 PID 找游戏窗口句柄，返回 (hwnd, title) 或 (None, None)。

    优先匹配标题含游戏特征字（鲜衣/一梦/梦幻/十年）的窗口，
    全部不匹配时退回第一个可见窗口。
    """
    found = []

    def cb(hwnd, _lp):
        out = DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(out))
        if out.value == pid and user32.IsWindowVisible(hwnd):
            tlen = user32.GetWindowTextLengthW(hwnd)
            if tlen > 0:
                buf = ctypes.create_unicode_buffer(tlen + 1)
                user32.GetWindowTextW(hwnd, buf, tlen + 1)
                found.append((hwnd, buf.value))
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    # 优先匹配游戏主窗口标题
    for kw in GAME_TITLE_KEYWORDS:
        for hwnd, title in found:
            if kw in title:
                return hwnd, title
    return (found[0] if found else (None, None))


def find_game_pids():
    """枚举所有'十年一梦.exe'进程 PID（纯 ctypes，不依赖 pymem / tasklist）。

    用于窗口查找的 fallback：当写死的 DEFAULT_PID 失效（重启/切图后 PID 变化）
    时自动找真实进程。与 JHRW 逻辑一致，此处自包含不串依赖。
    """
    try:
        psapi = ctypes.WinDLL('psapi.dll', use_last_error=True)
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    except Exception:
        return []

    pids_arr = (DWORD * 2048)()
    bytes_returned = DWORD(0)
    if not psapi.EnumProcesses(pids_arr, ctypes.sizeof(pids_arr),
                               ctypes.byref(bytes_returned)):
        return []
    count = bytes_returned.value // ctypes.sizeof(DWORD)

    PROCESS_QUERY_INFORMATION = 0x0400
    PROCESS_VM_READ = 0x0010
    target_names = ['十年一梦', 'yimeng']
    result = []
    for i in range(count):
        pid = pids_arr[i]
        if pid == 0:
            continue
        h = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ,
                                 False, pid)
        if not h:
            continue
        try:
            name_buf = ctypes.create_unicode_buffer(260)
            got = psapi.GetModuleBaseNameW(h, None, name_buf, 260)
            name = name_buf.value if got else ''
            if not name:
                buf = ctypes.create_unicode_buffer(260)
                size = DWORD(260)
                if kernel32.QueryFullProcessImageNameW(
                        h, 0, buf, ctypes.byref(size)):
                    name = buf.value
            name_lower = name.lower()
            for t in target_names:
                if t.lower() in name_lower:
                    result.append(int(pid))
                    break
        finally:
            kernel32.CloseHandle(h)
    return result


def locate_game_window(preferred_pid=None, verbose=False, tag=""):
    """定位游戏主窗口句柄。

    优先用 preferred_pid 找；若该 PID 找不到窗口（写死/重启后变化），
    自动枚举所有游戏进程 PID 兜底，返回第一个能定位到主窗口的。
    仅接受标题含游戏特征字（鲜衣/一梦/梦幻/十年）的窗口，避免误选
    find_game_pids 按 exe 名子串误匹配的无关进程窗口。

    :param preferred_pid: 优先尝试的 PID（可 None）
    :param verbose: 兜底时打印日志
    :param tag: 日志前缀（原各包差异：如 "[DHW]" / "[JNYW]"）
    :return: (hwnd, title)，找不到 (None, None)
    """
    candidates = []
    if preferred_pid:
        candidates.append(preferred_pid)
    try:
        candidates.extend(find_game_pids())
    except Exception:
        pass

    seen = set()
    for pid in candidates:
        if pid in seen:
            continue
        seen.add(pid)
        hwnd, title = find_game_window(pid)
        if hwnd and any(kw in (title or '') for kw in GAME_TITLE_KEYWORDS):
            if preferred_pid and pid != preferred_pid and verbose:
                print(f"{tag}兜底: 用枚举到的 PID={pid} 定位窗口 "
                      f"(原 PID={preferred_pid} 失效)")
            return hwnd, title
    return None, None


def client_to_screen(hwnd, cx, cy):
    """客户区坐标 → 屏幕绝对坐标"""
    pt = POINT(int(cx), int(cy))
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    return (pt.x, pt.y)
