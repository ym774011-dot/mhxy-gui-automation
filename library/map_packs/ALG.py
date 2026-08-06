# -*- coding: utf-8 -*-
"""
ALG - 傲来国 地图坐标点击函数
================================
功能: 输入游戏逻辑坐标 → 自动计算地图像素位置 → 后台点击
校准数据已内置（基于 2026-07-30 实测校准），无需重新校准

校准来源（终端 #842-884）:
  - 地图原点 (0,0) = 客户区像素 (293, 199)
  - 缩放比例: x=1.852 px/unit, y=1.870 px/unit
  - 验证: 像素(519,300) → 游戏坐标(122.0, 54.0) ✓
  - 像素(460,269) → 游戏坐标(90.2, 37.4) ✓

依赖: 无（纯 ctypes + Win32 API）

使用方式:
  1. 作为模块导入:
     from ALG import ALG
     result = ALG((122, 54))                      # 点击游戏坐标(122,54)
     result = ALG((122, 54), pid=28024)           # 指定PID
     result = ALG((122, 54), click=False)         # 只算坐标不点击
     result = ALG((122, 54), background=False)    # 前台点击（移动鼠标）

  2. 命令行:
     python ALG.py 122,54                         # 点击
     python ALG.py 122,54 -p 28024                # 指定PID
     python ALG.py 122,54 -n                      # 只算坐标不点击
     python ALG.py 122,54 -f                      # 前台点击（默认后台）
"""
# ============================================================
# 函数中文元信息（GUI 下拉框显示用）
# 字段：title -> 一行中文说明；args -> {参数名: 中文说明}
# 增加新函数时同步补全，否则 GUI 仍按原签名显示。
# ============================================================
__function_meta__ = {
    "ALG": {
        "title": "傲来国: 走到游戏坐标并点击",
        "args": {
            "target_coord": "(gx, gy) 游戏逻辑坐标，如 (65, 112)",
            "pid": "游戏进程 PID（默认 28024；找不到窗口时自动枚举游戏进程兜底）",
            "click": "True=实际点击，False=只返回坐标",
            "background": "True=后台点击（不抢焦点），False=前台移动鼠标",
            "verbose": "是否打印过程日志",
        },
    },
    "pixel_to_game": {
        "title": "地图像素 → 游戏逻辑坐标",
        "args": {
            "px": "地图像素 X（客户区）",
            "py": "地图像素 Y（客户区）",
        },
    },
    "game_to_pixel": {
        "title": "游戏逻辑 → 地图像素坐标",
        "args": {
            "gx": "游戏逻辑 X",
            "gy": "游戏逻辑 Y",
        },
    },
    "main": {
        "title": "命令行测试入口",
        "args": {},
    },
}
import sys
import ctypes
import time
from ctypes import wintypes

# ============================================================
# Win32 API
# ============================================================
user32 = ctypes.WinDLL('user32', use_last_error=True)

HWND = wintypes.HWND
LPARAM = wintypes.LPARAM
BOOL = wintypes.BOOL
DWORD = wintypes.DWORD

class POINT(ctypes.Structure):
    _fields_ = [('x', ctypes.c_long), ('y', ctypes.c_long)]

WNDENUMPROC = ctypes.WINFUNCTYPE(BOOL, HWND, LPARAM)

# Windows 消息常量
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_MOUSEMOVE = 0x0200
MK_LBUTTON = 0x0001
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
MK_RBUTTON = 0x0002

# 鼠标事件常量（前台点击用）
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
# Tab键常量（调用地图函数前按Tab切换状态）
VK_TAB = 0x09
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
KEYEVENTF_KEYUP = 0x0002

# ============================================================
# 内置校准数据（2026-07-30 实测，终端 #842-884）
# ============================================================
MAP_ORIGIN_PIXEL = (293, 199)      # 地图(0,0)在客户区的像素坐标
MAP_SCALE = (1.852, 1.870)         # 每游戏单位对应像素数 (x, y)
# 大地图有效点击范围上限（用户实测，与 data/map_ui_blocks.json max_game_coord 一致；None=暂无数据不限制）
MAP_MAX_GAME_COORD = None




DEFAULT_PID = 28024                # 默认游戏进程PID

# ============================================================
# 窗口查找
# ============================================================
def _find_game_window(pid):
    """通过 PID 找游戏窗口句柄，返回 (hwnd, title) 或 (None, None)"""
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
    for kw in ('鲜衣', '一梦', '梦幻', '十年'):
        for hwnd, title in found:
            if kw in title:
                return hwnd, title
    return (found[0] if found else (None, None))


def _find_game_pids():
    """枚举所有'十年一梦.exe'进程 PID（纯 ctypes，不依赖 pymem / tasklist）。

    用于窗口查找的 fallback：当写死的 DEFAULT_PID 失效（重启/切图后 PID 变化）
    时自动找真实进程。与 JHRW._find_game_pids 逻辑一致，但此处自包含不串依赖。
    """
    try:
        psapi = ctypes.WinDLL('psapi.dll', use_last_error=True)
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    except Exception:
        return []

    DWORD = ctypes.c_uint32
    pids_arr = (DWORD * 2048)()
    bytes_returned = DWORD(0)
    if not psapi.EnumProcesses(pids_arr, ctypes.sizeof(pids_arr), ctypes.byref(bytes_returned)):
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
        h = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
        if not h:
            continue
        try:
            name_buf = ctypes.create_unicode_buffer(260)
            got = psapi.GetModuleBaseNameW(h, None, name_buf, 260)
            name = name_buf.value if got else ''
            if not name:
                buf = ctypes.create_unicode_buffer(260)
                size = DWORD(260)
                if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                    name = buf.value
            name_lower = name.lower()
            for t in target_names:
                if t.lower() in name_lower:
                    result.append(int(pid))
                    break
        finally:
            kernel32.CloseHandle(h)
    return result


_GAME_TITLE_KEYWORDS = ('鲜衣', '一梦', '梦幻', '十年')


def _locate_game_window(preferred_pid=None, verbose=False):
    """定位游戏主窗口句柄。

    优先用 preferred_pid 找；若该 PID 找不到窗口（写死/重启后变化），
    自动枚举所有游戏进程 PID 兜底，返回第一个能定位到主窗口的。
    仅接受标题含游戏特征字（鲜衣/一梦/梦幻/十年）的窗口，避免误选
    _find_game_pids 按 exe 名子串误匹配的无关进程窗口。
    返回 (hwnd, title)，找不到 (None, None)。
    """
    candidates = []
    if preferred_pid:
        candidates.append(preferred_pid)
    try:
        candidates.extend(_find_game_pids())
    except Exception:
        pass

    seen = set()
    for pid in candidates:
        if pid in seen:
            continue
        seen.add(pid)
        hwnd, title = _find_game_window(pid)
        if hwnd and any(kw in (title or '') for kw in _GAME_TITLE_KEYWORDS):
            if preferred_pid and pid != preferred_pid and verbose:
                print(f"兜底: 用枚举到的 PID={pid} 定位窗口 (原 PID={preferred_pid} 失效)")
            return hwnd, title
    return None, None

def _client_to_screen(hwnd, cx, cy):
    """客户区坐标 → 屏幕绝对坐标"""
    pt = POINT(int(cx), int(cy))
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    return (pt.x, pt.y)

# ============================================================
# 坐标转换核心
# ============================================================
def game_to_pixel(gx, gy):
    """游戏逻辑坐标 → 地图像素坐标（客户区相对）
    公式: pixel = origin + game * scale
    """
    ox, oy = MAP_ORIGIN_PIXEL
    sx, sy = MAP_SCALE
    return (ox + gx * sx, oy + gy * sy)

def pixel_to_game(px, py):
    """地图像素坐标 → 游戏逻辑坐标
    公式: game = (pixel - origin) / scale
    """
    ox, oy = MAP_ORIGIN_PIXEL
    sx, sy = MAP_SCALE
    return ((px - ox) / sx, (py - oy) / sy)

# ============================================================
# 点击实现
# ============================================================
def _click_background(hwnd, cx, cy):
    # 后台点击（含抖动重试，用户方案 2026-08-06）: PostMessage 完整流程
    # 序列：左键(原坐标) -> 2s -> 左键(抖动+10~50) -> 2s -> 左键(点回原坐标) -> 右键(交互)
    # 抖动 = 游戏坐标 + random(10~50)；超出大地图范围 max_game_coord 反向 -10~50
    import random
    # 原坐标像素 -> 游戏坐标
    gx0, gy0 = pixel_to_game(float(cx), float(cy))
    # 抖动（游戏坐标级 +10~50）
    _jx = gx0 + random.uniform(10.0, 50.0)
    _jy = gy0 + random.uniform(10.0, 50.0)
    # 超大地图范围 -> 反向 -10~50
    _mc = MAP_MAX_GAME_COORD
    if _mc is not None and (_jx > _mc[0] or _jy > _mc[1]):
        _jx = gx0 - random.uniform(10.0, 50.0)
        _jy = gy0 - random.uniform(10.0, 50.0)
    _jpx, _jpy = game_to_pixel(_jx, _jy)

    def _lp(x, y):
        return (int(y) << 16) | (int(x) & 0xFFFF)

    # 1) 第一次左键（原坐标，寻路）
    user32.PostMessageW(hwnd, WM_MOUSEMOVE, 0, _lp(cx, cy))
    time.sleep(0.08)
    user32.PostMessageW(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, _lp(cx, cy))
    time.sleep(0.10)
    user32.PostMessageW(hwnd, WM_LBUTTONUP, 0, _lp(cx, cy))
    # 等待角色寻路
    time.sleep(2.0)
    # 2) 第二次左键（抖动坐标）
    user32.PostMessageW(hwnd, WM_MOUSEMOVE, 0, _lp(_jpx, _jpy))
    time.sleep(0.08)
    user32.PostMessageW(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, _lp(_jpx, _jpy))
    time.sleep(0.10)
    user32.PostMessageW(hwnd, WM_LBUTTONUP, 0, _lp(_jpx, _jpy))
    # 等待到达
    time.sleep(2.0)
    # 3) 左键点回原坐标（任务正确坐标）
    user32.PostMessageW(hwnd, WM_MOUSEMOVE, 0, _lp(cx, cy))
    time.sleep(0.08)
    user32.PostMessageW(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, _lp(cx, cy))
    time.sleep(0.10)
    user32.PostMessageW(hwnd, WM_LBUTTONUP, 0, _lp(cx, cy))
    time.sleep(0.5)
    # 4) 右键交互（NPC 对话）
    user32.PostMessageW(hwnd, WM_RBUTTONDOWN, MK_RBUTTON, _lp(cx, cy))
    time.sleep(0.10)
    user32.PostMessageW(hwnd, WM_RBUTTONUP, 0, _lp(cx, cy))
def _click_foreground(hwnd, cx, cy):
    """前台点击: 移动鼠标到位置后按指定流程点击（会抢焦点）

    流程：
      1. 移动鼠标到坐标
      2. 延迟 0.3s
      3. 左键点击 1 次
      4. 延迟 2.0s
      5. 左键点击 1 次
      6. 延迟 2.0s
      7. 右键点击 1 次
    """
    sx, sy = _client_to_screen(hwnd, cx, cy)
    # 1) 移动鼠标到目标坐标
    user32.SetCursorPos(sx, sy)
    time.sleep(0.3)
    # 2) 第一次左键点击
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.05)
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    # 3) 等待 2 秒
    time.sleep(2.0)
    # 4) 第二次左键点击
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.05)
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    # 5) 等待 2 秒
    time.sleep(2.0)
    # 6) 右键点击
    user32.mouse_event(MOUSEEVENTF_RIGHTDOWN, 0, 0, 0, 0)
    time.sleep(0.05)
    user32.mouse_event(MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)


def _press_tab(hwnd, background=False):
    """按一次Tab键（用于调用地图函数前切换地图状态）

    前台模式使用keybd_event，后台模式使用PostMessage。
    """
    if background:
        # 后台按键
        user32.PostMessageW(hwnd, WM_KEYDOWN, VK_TAB, 0)
        time.sleep(0.05)
        user32.PostMessageW(hwnd, WM_KEYUP, VK_TAB, 0)
    else:
        # 前台按键
        user32.keybd_event(VK_TAB, 0, 0, 0)
        time.sleep(0.05)
        user32.keybd_event(VK_TAB, 0, KEYEVENTF_KEYUP, 0)
    time.sleep(0.3)  # 等待Tab键生效

# ============================================================
# 主函数 ALG
# ============================================================
def ALG(target_coord, *more, pid=DEFAULT_PID, click=True, background=False, verbose=False):
    """
    傲来国 地图坐标点击函数

    参数:
        target_coord : (gx, gy) 目标游戏坐标，例如 (122, 54)
        pid          : 游戏进程PID（默认 28024）
        click        : 是否发送点击（True=点击，False=只返回坐标）
        background   : True=后台点击(不抢焦点)，False=前台点击(移动鼠标，默认）
        verbose      : 是否打印详细信息

    返回:
        dict: {
            'ok'           : True/False,
            'target_game'  : (gx, gy),
            'target_pixel' : (px, py),       # 客户区像素
            'screen_pixel' : (sx, sy),       # 屏幕绝对像素（仅前台点击时有效）
            'hwnd'         : 窗口句柄,
            'message'      : 描述信息
        }

    示例:
        result = ALG((122, 54))
        if result['ok']:
            print(f"已点击 {result['target_game']}")
    """
    if more:
        target_coord = (target_coord, *more)

    # 防御：字符串坐标（GUI 模板解析可能带引号）也能算
    try:
        gx, gy = (float(target_coord[0]), float(target_coord[1]))
    except (TypeError, ValueError, IndexError):
        raise TypeError(
            f"target_coord 必须是 (gx, gy) 二元组，收到: {target_coord!r}"
        )
    px, py = game_to_pixel(gx, gy)

    result = {
        'ok': False,
        'target_game': (gx, gy),
        'target_pixel': (px, py),
        'screen_pixel': None,
        'hwnd': None,
        'message': ''
    }

    # 1. 找窗口（优先用给定 pid，失效则自动枚举游戏进程兜底）
    hwnd, title = _locate_game_window(pid, verbose=verbose)
    if not hwnd:
        result['message'] = f'❌ 未找到游戏窗口 (PID={pid}, 且枚举游戏进程也无果)'
        if verbose:
            print(result['message'])
        return result

    result['hwnd'] = hwnd
    result['pid'] = pid
    result['ok'] = True

    if verbose:
        print(f"窗口: PID={pid}  HWND=0x{hwnd:X}")
        print(f"标题: {title}")
        print(f"目标游戏坐标: ({gx}, {gy})")
        print(f"客户区像素: ({px:.1f}, {py:.1f})")

    # 2. 点击
    if click:
        # 先按Tab键切换地图状态
        _press_tab(hwnd, background)
        if background:
            _click_background(hwnd, px, py)
            result['message'] = f'✓ 后台点击 ({gx},{gy}) → 像素({px:.1f},{py:.1f})'
        else:
            sx, sy = _client_to_screen(hwnd, px, py)
            result['screen_pixel'] = (sx, sy)
            _click_foreground(hwnd, px, py)
            result['message'] = f'✓ 前台点击 ({gx},{gy}) → 屏幕({sx},{sy})'
        if verbose:
            print(result['message'])
    else:
        result['message'] = f'目标({gx},{gy}) → 像素({px:.1f},{py:.1f}) [未点击]'
        if verbose:
            print(result['message'])

    return result

# ============================================================
# 命令行入口
# ============================================================
def main():
    if len(sys.argv) < 2:
        print("ALG - 地图坐标点击函数")
        print("用法:")
        print("  python ALG.py 122,54                  # 后台点击游戏坐标(122,54)")
        print("  python ALG.py 122,54 -p 28024         # 指定PID")
        print("  python ALG.py 122,54 -n               # 只算坐标不点击")
        print("  python ALG.py 122,54 -f               # 前台点击(移动鼠标)")
        print()
        print("内置校准:")
        print(f"  地图原点(0,0) = 客户区像素 {MAP_ORIGIN_PIXEL}")
        print(f"  缩放比例 = {MAP_SCALE} px/unit")
        return

    # 解析坐标
    coord_str = sys.argv[1]
    if ',' not in coord_str:
        print("坐标格式错误，需要 x,y 格式，例如 122,54")
        return
    try:
        gx, gy = float(coord_str.split(',')[0]), float(coord_str.split(',')[1])
    except ValueError:
        print("坐标格式错误，必须是数字")
        return

    # 解析可选参数
    pid = DEFAULT_PID
    click = True
    background = True
    verbose = True

    i = 2
    while i < len(sys.argv):
        arg = sys.argv[i]
        if arg == '-p' and i + 1 < len(sys.argv):
            pid = int(sys.argv[i + 1])
            i += 2
        elif arg == '-n':
            click = False
            i += 1
        elif arg == '-f':
            background = False
            i += 1
        elif arg == '-q':
            verbose = False
            i += 1
        else:
            i += 1

    result = ALG((gx, gy), pid=pid, click=click, background=background, verbose=verbose)
    if not result['ok']:
        print(result['message'])


if __name__ == '__main__':
    main()
