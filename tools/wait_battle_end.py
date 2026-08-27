# -*- coding: utf-8 -*-
"""等待战斗结束，结束后读取护法弹窗确认下一关，并打印状态。
用法: python wait_battle_end.py [--timeout 300] [--close]
  --close  结束后自动右键关闭确认弹窗
"""
import json, urllib.request, time, argparse, os, sys, ctypes
GW = "http://127.0.0.1:18083"
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(ROOT))
def lua(code):
    d = json.loads(urllib.request.urlopen(urllib.request.Request(
        GW + "/api/lua", data=json.dumps({"code": code}).encode("utf-8"),
        headers={"Content-Type": "application/json"}), timeout=20).read().decode("utf-8", "replace"))
    if d.get("ok") is False:
        return f"<ERR:{d.get('error')}>"
    return d.get("result", {}).get("value")
def state():
    v = lua(r'''
local out={}
out[1]="战斗="..tostring(tp.战斗中 and true or false)
out[2]="地图="..tostring(tp.当前地图 or '')
local d=tp.窗口.对话栏
out[3]="对话可视="..tostring(d and d.可视 or false)
out[4]="对话名="..tostring(d and d.名称 or '')
out[5]="对话文="..tostring(d and d.文本内容 or '')
_G.__out=table.concat(out,"\n")''') or ""
    r = {}
    for line in v.splitlines():
        if "=" in line:
            k, _, val = line.partition("=")
            r[k] = val
    return r
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--close", action="store_true")
    args = ap.parse_args()
    t0 = time.time()
    while time.time() - t0 < args.timeout:
        s = state()
        if s.get("战斗") != "true" and s.get("对话可视") == "true":
            print("战斗结束，弹窗已出现：")
            print("  名称:", s.get("对话名"))
            print("  文本:", s.get("对话文"))
            print("  地图:", s.get("地图"))
            if args.close:
                # 右键关闭确认弹窗
                from core.window_manager import window_manager
                pid = int(s.get("地图") or (json.loads(urllib.request.urlopen(
                    GW + "/api/status", timeout=10).read().decode("utf-8", "replace")).get("result") or {}).get("pid") or 0)
                if pid > 0:
                    window_manager.bind(pid=pid)
                    hwnd = getattr(window_manager, "hwnd", None)
                    u = ctypes.windll.user32
                    lp = (320 << 16) | 150
                    u.PostMessageW(hwnd, 0x0200, 0, lp); time.sleep(0.1)
                    u.PostMessageW(hwnd, 0x0204, 0x0002, lp); time.sleep(0.1)
                    u.PostMessageW(hwnd, 0x0205, 0, lp)
                    time.sleep(0.8)
                    print("已右键关闭确认弹窗，可视=", state().get("对话可视"))
            return
        if s.get("战斗") == "true":
            print(f"[{int(time.time()-t0)}s] 战斗进行中...", flush=True)
        time.sleep(3)
    print("超时未等到战斗结束/弹窗")

if __name__ == "__main__":
    main()