# -*- coding: utf-8 -*-
"""
CSC - 长寿村 地图坐标点击函数
================================
功能: 输入游戏逻辑坐标 → 自动计算地图像素位置 → 后台点击
校准数据已内置（基于 2026-07-30 实测校准），无需重新校准

校准来源（终端 #608-645）:
  - 地图原点 (0,0) = 客户区像素 (393, 200)
  - 缩放比例: x=1.340 px/unit, y=1.335 px/unit
  - 验证: 像素(535,411) → 游戏坐标(106.0, 158.0) ✓
  - 像素(475,284) → 游戏坐标(61.2, 62.9) ✓

依赖: 无（纯 ctypes + Win32 API）

使用方式:
  1. 作为模块导入:
     from CSC import CSC
     result = CSC((106, 158))                    # 点击游戏坐标(106,158)
     result = CSC((106, 158), pid=28024)         # 指定PID
     result = CSC((106, 158), click=False)       # 只算坐标不点击
     result = CSC((106, 158), background=False)  # 前台点击（移动鼠标）

  2. 命令行:
     python CSC.py 106,158                       # 点击
     python CSC.py 106,158 -p 28024              # 指定PID
     python CSC.py 106,158 -n                    # 只算坐标不点击
     python CSC.py 106,158 -f                    # 前台点击（默认后台）
"""
# ============================================================
# 函数中文元信息（GUI 下拉框显示用）
# 字段：title -> 一行中文说明；args -> {参数名: 中文说明}
# 增加新函数时同步补全，否则 GUI 仍按原签名显示。
# ============================================================
__function_meta__ = {
    "CSC": {
        "title": "长寿村: 走到游戏坐标并点击",
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
from library.common.win_utils import (
    find_game_window as _find_game_window,
    find_game_pids as _find_game_pids,
    locate_game_window as _locate_game_window,
    client_to_screen as _client_to_screen,
)

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
# 内置校准数据（2026-07-30 实测，终端 #608-645）
# ============================================================
MAP_ORIGIN_PIXEL = (393, 200)      # 地图(0,0)在客户区的像素坐标
MAP_SCALE = (1.340, 1.335)         # 每游戏单位对应像素数 (x, y)
# 大地图有效点击范围上限（用户实测，与 data/map_ui_blocks.json max_game_coord 一致；None=暂无数据不限制）
MAP_MAX_GAME_COORD = None




DEFAULT_PID = 28024                # 默认游戏进程PID

# ============================================================
# 窗口查找
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
# ============================================================# 抖动模式标志：False=第一次点击(原坐标不随机)；引擎到达失败后置 True(下次抖动)
_JITTER_MODE = False
# 光标同步开关（2026-08-16）：默认 False = 纯 PostMessage（光标完全不动）。
# True = SetCursorPos 瞬移（方案 A，点击可靠但光标闪入游戏——用户已否决）。
_CURSOR_SYNC = False


def _click_background(hwnd, cx, cy):
    # 后台点击（用户方案 2026-08-06）: PostMessage 完整流程
    # 第一次点击不随机；引擎判定到达失败后置 _JITTER_MODE=True，
    # 下次调用走抖动序列：左键(原)->2s->左键(抖动+1~6)->2s->左键(点回原)->右键
    # 2026-08-16 光标同步：默认 **纯 PostMessage（光标完全不动）**。
    #   仅当 _CURSOR_SYNC=True（模块级）时才 SetCursorPos 瞬移光标到目标点，
    #   解决 Galaxy2D 自绘引擎 GetCursorPos 命中检测失效——但光标会闪入游戏，
    #   用户已否决此方案（要求光标绝不出现在游戏里），故默认关闭。
    import random

    def _lp(x, y):
        return (int(y) << 16) | (int(x) & 0xFFFF)

    def _sync_cursor(px, py):
        # 2026-08-16 光标同步：默认纯 PostMessage（光标不动）。
        # _CURSOR_SYNC=True 时 SetCursorPos 瞬移（方案 A，点击可靠但光标闪入
        # 游戏——用户已否决，默认 False）。
        # 废弃 GetCursorPos IAT hook（真后台）方案：实测导致游戏全部闪退——
        # galaxy2d.dll 的 GetCursorPos 是运行时 GetProcAddress 动态解析，
        # 无 IAT 可 hook，内存扫描误改 DATA 节指针破坏游戏内存。
        if not globals().get('_CURSOR_SYNC', False):
            return
        try:
            sx, sy = _client_to_screen(hwnd, px, py)
            user32.SetCursorPos(sx, sy)
            time.sleep(0.02)
        except Exception:
            pass


    def _lp(x, y):
        return (int(y) << 16) | (int(x) & 0xFFFF)

    # 计算抖动坐标（仅 _JITTER_MODE 时使用）
    _jpx = _jpy = None
    if _JITTER_MODE:
        gx0, gy0 = pixel_to_game(float(cx), float(cy))
        _jx = gx0 + random.uniform(1.0, 6.0)
        _jy = gy0 + random.uniform(1.0, 6.0)
        _mc = MAP_MAX_GAME_COORD
        if _mc is not None and (_jx > _mc[0] or _jy > _mc[1]):
            _jx = gx0 - random.uniform(1.0, 6.0)
            _jy = gy0 - random.uniform(1.0, 6.0)
        _jpx, _jpy = game_to_pixel(_jx, _jy)

    # 1) 第一次左键（原坐标，寻路）
    _sync_cursor(cx, cy)
    user32.PostMessageW(hwnd, WM_MOUSEMOVE, 0, _lp(cx, cy))
    time.sleep(0.08)
    user32.PostMessageW(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, _lp(cx, cy))
    time.sleep(0.10)
    user32.PostMessageW(hwnd, WM_LBUTTONUP, 0, _lp(cx, cy))
    # 等待角色寻路
    time.sleep(2.0)
    # 2) 第二次左键：_JITTER_MODE 用抖动坐标，否则原坐标
    if _jpx is not None:
        _sync_cursor(_jpx, _jpy)
        user32.PostMessageW(hwnd, WM_MOUSEMOVE, 0, _lp(_jpx, _jpy))
        time.sleep(0.08)
        user32.PostMessageW(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, _lp(_jpx, _jpy))
        time.sleep(0.10)
        user32.PostMessageW(hwnd, WM_LBUTTONUP, 0, _lp(_jpx, _jpy))
    else:
        _sync_cursor(cx, cy)
        user32.PostMessageW(hwnd, WM_MOUSEMOVE, 0, _lp(cx, cy))
        time.sleep(0.08)
        user32.PostMessageW(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, _lp(cx, cy))
        time.sleep(0.10)
        user32.PostMessageW(hwnd, WM_LBUTTONUP, 0, _lp(cx, cy))
    # 等待到达
    time.sleep(2.0)
    # 3) 左键点回原坐标（任务正确坐标）
    _sync_cursor(cx, cy)
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
# 主函数 CSC
# ============================================================
def CSC(target_coord, *more, pid=DEFAULT_PID, click=True, background=False, verbose=False):
    """
    长寿村 地图坐标点击函数

    参数:
        target_coord : (gx, gy) 目标游戏坐标，例如 (106, 158)
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
        result = CSC((106, 158))
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
        print("CSC - 地图坐标点击函数")
        print("用法:")
        print("  python CSC.py 106,158               # 后台点击游戏坐标(106,158)")
        print("  python CSC.py 106,158 -p 28024      # 指定PID")
        print("  python CSC.py 106,158 -n            # 只算坐标不点击")
        print("  python CSC.py 106,158 -f            # 前台点击(移动鼠标)")
        print()
        print("内置校准:")
        print(f"  地图原点(0,0) = 客户区像素 {MAP_ORIGIN_PIXEL}")
        print(f"  缩放比例 = {MAP_SCALE} px/unit")
        return

    # 解析坐标
    coord_str = sys.argv[1]
    if ',' not in coord_str:
        print("坐标格式错误，需要 x,y 格式，例如 106,158")
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

    result = CSC((gx, gy), pid=pid, click=click, background=background, verbose=verbose)
    if not result['ok']:
        print(result['message'])


if __name__ == '__main__':
    main()
