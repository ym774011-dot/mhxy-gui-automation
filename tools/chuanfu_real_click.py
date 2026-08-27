# -*- coding: utf-8 -*-
"""船夫传送最终方案：Lua开对话 → PostMessage点选项热区。"""
import sys
import time

sys.path.insert(0, r'E:\DS\mhxy-gui-automation')
import win32gui
import win32process
import win32con

from tools.probe_routes import lua, cur_map

PID = 13924  # 组1 然学（网关 /api/status 实时获取）


def find_hwnd_by_pid(pid):
    result = []

    def cb(h, _):
        if win32gui.IsWindowVisible(h) or True:
            _, wpid = win32process.GetWindowThreadProcessId(h)
            if wpid == pid:
                result.append(h)
        return True
    win32gui.EnumWindows(cb, None)
    return result[0] if result else None


CLICK = r'''
local d = tp.窗口.对话栏
if not d or not d.可视 or not d.选项 then _G.__out = "no_dialog" return end
for i=1,#d.选项 do
  local o = d.选项[i]
  if tostring(o.基本内容 or ""):find("我要去") then
    local sj = o.选中判断
    if sj then
      _G.__out = string.format("%d,%d,%d,%d", sj.x, sj.y, sj.w or sj.x2-sj.x, sj.h or sj.y2-sj.y)
    else
      _G.__out = "no_hitbox"
    end
    return
  end
end
_G.__out = "no_go_option"
'''

if __name__ == '__main__':
    hwnd = find_hwnd_by_pid(PID)
    print('hwnd:', hwnd)
    assert hwnd, '未找到游戏窗口'

    # 关旧对话 → CALL 船夫 → 轮询就绪
    lua(r'pcall(function() if tp.窗口.对话栏 and tp.窗口.对话栏.关闭 then tp.窗口.对话栏:关闭() end end)')
    time.sleep(0.5)
    from tools.chuanfu_full import CALL, POLL
    print('call:', lua(CALL))
    s = ''
    for i in range(12):
        time.sleep(0.3)
        s = lua(POLL)
        if s.startswith('ready'):
            break
    print('poll:', s)

    hit = lua(CLICK)
    print('hitbox:', hit)
    if ',' in hit:
        x, y, w, h = [int(v) for v in hit.split(',')]
        cx, cy = x + w // 2, y + h // 2
        lparam = (cy << 16) | (cx & 0xFFFF)
        win32gui.PostMessage(hwnd, win32con.WM_MOUSEMOVE, 0, lparam)
        time.sleep(0.1)
        r1 = win32gui.PostMessage(hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lparam)
        time.sleep(0.08)
        r2 = win32gui.PostMessage(hwnd, win32con.WM_LBUTTONUP, 0, lparam)
        print(f'click({cx},{cy}) r1={r1} r2={r2}')
        for i in range(6):
            time.sleep(1.0)
            print(f'{i+1}s:', cur_map())
    else:
        print('热区读取失败')
