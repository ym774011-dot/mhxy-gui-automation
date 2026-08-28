# -*- coding: utf-8 -*-
"""大图锚定 v3：有效全局 desc + HUD 权威校验 + 运动对应配对。"""
import json
import sys
import time
import urllib.request

sys.path.insert(0, r'E:\DS\mhxy-gui-automation')
sys.path.insert(0, r'E:\DS\mhxy-gui-automation\tools')
from core.window_manager import WindowManager  # noqa: E402
from core.glyph_coord_reader import glyph_coord_reader  # noqa: E402
import debug_bigmap_shot as d  # noqa: E402
from tools.debug_bigmap_anchor_fit2 import red_discs, CROP  # noqa: E402

GW = "http://127.0.0.1:18082"
SCALE0 = 0.841

PLAN = [
    # (目标图, HUD 校验子串, 跨图链, [p1, p2])
    ("江南野外", "江南野外", ["长安传送江南野外"], [(30, 30), (120, 100)]),
    ("建邺城", "建邺城", ["江南野外传送建邺城"], [(100, 100), (200, 40)]),
    ("大唐国境", "大唐国境", ["长安传送大唐国境"], [(150, 120), (210, 160)]),
]


def post(path, body):
    req = urllib.request.Request(
        GW + path, json.dumps(body).encode("utf-8"),
        {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def wait_battle(max_s=60):
    t0 = time.time()
    while time.time() - t0 < max_s:
        if d.expr("tostring(tp.战斗中)") != "true":
            return True
        time.sleep(1.5)
    return False


def hud_loc():
    return glyph_coord_reader.read_location(timeout=3.0)


def goto_map(name, chain, tries=2):
    for t in range(tries):
        for desc in chain:
            wait_battle()
            post("/api/act/cross_map", {"desc": desc, "x": 100, "y": 100})
            time.sleep(1.5)
        time.sleep(1.0)
        loc = hud_loc()
        print(f"  HUD: {loc}")
        if loc and name in str(loc.get("map", "")):
            return True
    return False


def main():
    wm = WindowManager()
    wm.bind(pid=4172)
    report = {}
    for map_name, check, chain, (p1, p2) in PLAN:
        if not goto_map(map_name, chain):
            print(f"!! [{map_name}] 跨图校验失败，跳过")
            report[map_name] = {"error": "跨图失败"}
            continue
        samples = []
        prev_discs, prev_g = None, None
        for k, (x, y) in enumerate((p1, p2)):
            wait_battle()
            post("/api/act/teleport", {"x": x, "y": y})
            time.sleep(1.0)
            loc = hud_loc()
            if not loc or abs(loc["x"] - x) > 3 or abs(loc["y"] - y) > 3:
                print(f"  [{map_name}] p{k} 传送脱同步 目标({x},{y}) HUD={loc}")
            gx, gy = float(loc["x"]), float(loc["y"]) if loc else (x, y)
            # 开大图截屏（失败重试一次开图）
            discs = []
            for attempt in range(2):
                path = rf'E:\DS\mhxy-gui-automation\anchor3_{map_name}_{k}.png'
                d.press_tab(wm.hwnd)
                time.sleep(1.2)
                d.bitblt_window(wm.hwnd, path)
                d.press_tab(wm.hwnd)
                time.sleep(0.6)
                discs = red_discs(path)
                if discs:
                    break
                time.sleep(0.5)
            print(f"[{map_name}] p{k} HUD({gx:.0f},{gy:.0f}) "
                  f"候选={[(round(a,1), round(b,1), c) for a, b, c in discs]}")
            if prev_discs is None:
                prev_discs, prev_g = discs, (gx, gy)
                continue
            best = None
            for a in prev_discs:
                for b in discs:
                    dx = b[0] - a[0]
                    dy = b[1] - a[1]
                    ex = dx - SCALE0 * (gx - prev_g[0])
                    ey = dy - SCALE0 * (gy - prev_g[1])
                    err = (ex * ex + ey * ey) ** 0.5
                    if best is None or err < best[0]:
                        best = (err, a, b)
            if best and best[0] < 25:
                _, a, b = best
                print(f"    配对: ({a[0]:.1f},{a[1]:.1f})->({b[0]:.1f},{b[1]:.1f}) "
                      f"误差{best[0]:.1f}px")
                oxa = a[0] - SCALE0 * prev_g[0]
                oya = a[1] - SCALE0 * prev_g[1]
                oxb = b[0] - SCALE0 * gx
                oyb = b[1] - SCALE0 * gy
                ox, oy = (oxa + oxb) / 2, (oya + oyb) / 2
                spread = ((oxa - oxb) ** 2 + (oya - oyb) ** 2) ** 0.5
                verdict = "固定原点 OK" if spread < 8 else "原点漂移?!"
                print(f"[{map_name}] origin=({ox:.1f},{oy:.1f}) "
                      f"两点偏差={spread:.1f}px ({verdict})")
                report[map_name] = {"origin": [ox, oy], "scale": SCALE0,
                                    "spread": spread}
            else:
                e = best[0] if best else -1
                print(f"    配对失败 err={e:.1f}")
                report[map_name] = {"error": f"配对失败 err={e}"}
    with open(r'E:\DS\mhxy-gui-automation\debug_anchor_fit3.json', 'w',
              encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
