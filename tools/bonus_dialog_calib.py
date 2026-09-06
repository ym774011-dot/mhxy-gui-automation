# -*- coding: utf-8 -*-
"""知了王对话标定监视器：等稀有怪出现 → CALL → 连拍+全屏文字行颜色扫描。"""
import importlib.util
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
spec = importlib.util.spec_from_file_location(
    "ZGUI", os.path.join(ROOT, "tasks", "library", "ZGUI.py"))
ZGUI = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ZGUI)
sys.path.insert(0, HERE)
import member_sell_loop as msl  # noqa: E402

gw = sys.argv[1] if len(sys.argv) > 1 else "file://pzxy_p17164"
pid = int(sys.argv[2]) if len(sys.argv) > 2 else 17164
hwnd = msl.find_hwnd_by_pid(pid)
ZGUI.set_target_hwnd(hwnd)
print("hwnd:", hwnd, flush=True)

UNIT_LUA = r"""
local t = tp.地图.地图单位
if type(t) ~= 'table' then __out = '' return end
for _, v in pairs(t) do
  if type(v) == 'table' then
    local name = tostring(v.名称 or '')
    if v.标识 and (name:find('知了王') or name:find('星宿') or name:find('远古')) then
      __out = name .. '|' .. tostring(v.标识)
      return
    end
  end
end
__out = ''
"""

deadline = time.time() + 12 * 60
hit = None
while time.time() < deadline and not hit:
    r = ZGUI._lua_call(gw, UNIT_LUA) or ""
    if "|" in r:
        hit = r
        break
    time.sleep(2)
if not hit:
    print("12分钟内未遇稀有怪，退出", flush=True)
    sys.exit(0)
name, gid = hit.split("|", 1)
print("发现:", name, "标识:", gid, flush=True)
if not gid.isdigit():
    print("标识非数字", flush=True)
    sys.exit(0)
time.sleep(0.3)
ZGUI._lua_call(gw, "客户端:发送数据(0,3,6," + gid + ",1)")
print("已CALL", flush=True)

# 连拍 + 文字行扫描（红/白/黄三色）
out = {"hit": hit, "frames": []}
for i in range(14):
    ts = time.time()
    img, w, h = ZGUI.grab_client(hwnd)
    fn = os.path.join(ROOT, "test_data", "bonus_live_%d.png" % (ts % 100000))
    img.save(fn)
    px = img.load()
    bands = {}
    for y in range(180, 480):
        cr = cw = cy = 0
        for x in range(20, 560):
            R, G, B = px[x, y][:3]
            if R > 110 and (R - G) > 55 and (R - B) > 55:
                cr += 1
            elif R > 200 and G > 200 and B > 200:
                cw += 1
            elif R > 200 and G > 170 and B < 120:
                cy += 1
        if cr >= 8:
            bands.setdefault("red", []).append([y, cr])
        if cw >= 8:
            bands.setdefault("white", []).append([y, cw])
        if cy >= 8:
            bands.setdefault("yellow", []).append([y, cy])
    out["frames"].append({"t": round(ts - (time.time() - i * 0.5), 2), "file": fn,
                          "bands": {k: v[:6] for k, v in bands.items()}})
    # 合并相邻行成块打印
    time.sleep(0.5)

for fr in out["frames"][::4]:
    print(fr["file"], json.dumps(fr["bands"], ensure_ascii=False), flush=True)
with open(os.path.join(ROOT, "test_data", "bonus_live_report.json"), "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=1)
print("DONE", flush=True)
