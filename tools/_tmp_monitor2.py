# -*- coding: utf-8 -*-
"""后台监控 luaV_execute counter（每 1 秒，最多 60 秒）"""
import ctypes, ctypes.wintypes as wt, struct, sys, time
pid = 8716
COUNTER = 0x00AE0000
k = ctypes.WinDLL('kernel32', use_last_error=True)
h = k.OpenProcess(0x1F0FFF, False, pid)
def rc():
    b = ctypes.create_string_buffer(4); r = ctypes.c_size_t(0)
    k.ReadProcessMemory(h, ctypes.c_void_p(COUNTER), b, 4, ctypes.byref(r))
    return struct.unpack('<I', b.raw)[0]
c0 = rc()
print(f'[monitor] 初始={c0}，60 秒监控（每 1 秒）')
last = c0
t0 = time.time()
while time.time() - t0 < 60:
    time.sleep(1)
    c = rc()
    if c != last:
        print(f'  +{int(time.time()-t0)}s counter={c} (+{c-last}) ← Lua 活跃!')
        last = c
    if c > c0 + 1000:
        print(f'[✓✓] luaV_execute hook 生效！{c-c0} 次触发')
        break
else:
    print('[✗] 60 秒未增长')
