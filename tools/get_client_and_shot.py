# -*- coding: utf-8 -*-
"""获取窗口客户区矩形 + 截整个客户区图，用于定位背包按钮"""
import ctypes, sys, os, time
from ctypes import wintypes
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from library.map_packs import MPCG as M
GW="http://127.0.0.1:18083"
pid=M._gateway_pid(GW)
hwnd=M._bind_hwnd(GW, pid)
print("hwnd:", hex(hwnd), "pid:", pid)
user32=ctypes.windll.user32
rect=wintypes.RECT()
user32.GetClientRect(hwnd, ctypes.byref(rect))
cwidth=rect.right-rect.left; cheight=rect.bottom-rect.top
print("client:", cwidth, "x", cheight)
# 客户区在屏幕上的位置
cpt=wintypes.POINT(); cpt.x=0; cpt.y=0
user32.ClientToScreen(hwnd, ctypes.byref(cpt))
print("client screen left/top:", cpt.x, cpt.y)
# 截图
from PIL import ImageGrab
img=ImageGrab.grab(bbox=(cpt.x, cpt.y, cpt.x+cwidth, cpt.y+cheight))
out=os.path.join(os.path.dirname(os.path.abspath(__file__)),"bag_shot.png")
img.save(out)
print("saved:", out)