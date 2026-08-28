# -*- coding: utf-8 -*-
"""大图锚定 v4：勾"全部"显示标记 + 宽松红块 + 双假设配对。

H1 固定原点：标记 Δpixel = +0.841*Δgame（装饰不动）
H2 视角平移：标记 Δpixel ≈ 0，装饰 Δ = -0.841*Δgame
"""
import ctypes
import json
import sys
import time
import urllib.request

sys.path.insert(0, r'E:\DS\mhxy-gui-automation')
sys.path.insert(0, r'E:\DS\mhxy-gui-automation\tools')
from core.window_manager import WindowManager  # noqa: E402
from core.glyph_coord_reader import glyph_coord_reader  # noqa: E402
import debug_bigmap_shot as d  # noqa: E402
from PIL import Image  # noqa: E402

GW = "http://127.0.0.1:18082"
S = 0.841
# 大图面板内部（截图为 1000x620 客户区）
CROP = (352, 200, 648, 478)
CHK_ALL = (663, 225)   # "全部" 复选框
WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP = 0x0200, 0x0201, 0x0202

PLAN = [
    ("江南野外", "江南野外", ["长安传送江南野外"], [(30, 30), (120, 100)]),
    ("建邺城", "建邺城", ["江南野外传送建邺城"], [(100, 100), (200, 40)]),
    ("大唐国境", None, ["长安传送大唐国境"], [(150, 120), (210, 160)]),
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


def bg_click(hwnd, x, y):
    lp = (y << 16) | (x & 0xFFFF)
    for _ in range(3):
        ctypes.windll.user32.PostMessageW(hwnd, WM_MOUSEMOVE, 0, lp)
        time.sleep(0.02)
    ctypes.windll.user32.PostMessageW(hwnd, WM_LBUTTONDOWN, 1, lp)
    time.sleep(0.03)
    ctypes.windll.user32.PostMessageW(hwnd, WM_LBUTTONUP, 0, lp)


def blobs(png):
    img = Image.open(png).convert("RGB")
    x0, y0, x1, y1 = CROP
    w, h = img.size
    px = img.load()
    m = {}
    for j in range(max(0, y0), min(h, y1)):
        for i in range(max(0, x0), min(w, x1)):
            r, g, b = px[i, j]
            if r > 170 and g < 100 and b < 100:
                m[(i, j)] = True
    seen, out = set(), []
    for s in list(m):
        if s in seen:
            continue
        st, pts = [s], []
        seen.add(s)
        while st:
            x, y = st.pop()
            pts.append((x, y))
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                n = (x + dx, y + dy)
                if n in m and n not in seen:
                    seen.add(n)
                    st.append(n)
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        bw, bh = max(xs) - min(xs) + 1, max(ys) - min(ys) + 1
        den = len(pts) / (bw * bh)
        if 4 <= bw <= 30 and 4 <= bh <= 30 and den > 0.35 and len(pts) >= 12:
            out.append((sum(xs) / len(xs), sum(ys) / len(ys), len(pts)))
    return out


def open_and_shot(wm, tag, check_all=False):
    for attempt in range(3):
        path = rf'E:\DS\mhxy-gui-automation\anchor4_{tag}.png'
        d.press_tab(wm.hwnd)
        time.sleep(1.2)
        if check_all and attempt == 0:
            bg_click(wm.hwnd, *CHK_ALL)
            time.sleep(0.8)
        d.bitblt_window(wm.hwnd, path)
        d.press_tab(wm.hwnd)
        time.sleep(0.6)
        bl = blobs(path)
        if bl:
            return path, bl
        time.sleep(0.8)
    return path, bl


def pair(prev_bl, prev_g, bl, g):
    dgx, dgy = g[0] - prev_g[0], g[1] - prev_g[1]
    cands = []
    for a in prev_bl:
        for b in bl:
            dx, dy = b[0] - a[0], b[1] - a[1]
            e1 = ((dx - S * dgx) ** 2 + (dy - S * dgy) ** 2) ** 0.5   # H1 标记
            e2 = (dx * dx + dy * dy) ** 0.5                            # H2 不动
            e3 = ((dx + S * dgx) ** 2 + (dy + S * dgy) ** 2) ** 0.5   # 装饰(视角平移)
            cands.append((e1, e2, e3, a, b))
    return cands, (S * dgx, S * dgy)


def main():
    wm = WindowManager()
    wm.bind(pid=4172)
    report = {}
    for map_name, check, chain, (p1, p2) in PLAN:
        # 跨图
        okmap = False
        for t in range(2):
            for desc in chain:
                wait_battle()
                post("/api/act/cross_map", {"desc": desc, "x": 100, "y": 100})
                time.sleep(1.5)
            time.sleep(1.0)
            loc = hud_loc = glyph_coord_reader.read_location(timeout=3.0)
            print(f"  HUD after cross: {loc}")
            if loc and (check is None or check in str(loc.get("map", ""))):
                okmap = True
                break
        if not okmap:
            print(f"!! [{map_name}] 跨图确认失败")
            report[map_name] = {"error": "跨图失败"}
            continue
        shots = []
        for k, (x, y) in enumerate((p1, p2)):
            wait_battle()
            post("/api/act/teleport", {"x": x, "y": y})
            time.sleep(1.0)
            loc = glyph_coord_reader.read_location(timeout=3.0)
            gx, gy = (float(loc["x"]), float(loc["y"])) if loc else (float(x), float(y))
            path, bl = open_and_shot(wm, f"{map_name}_{k}", check_all=(k == 0))
            print(f"[{map_name}] p{k} game=({gx:.0f},{gy:.0f}) 红块="
                  f"{[(round(a), round(b), c) for a, b, c in bl]}")
            shots.append((gx, gy, bl))
        (g1, y1g, b1), (g2, y2g, b2) = shots
        if not b1 or not b2:
            report[map_name] = {"error": "无红块"}
            continue
        cands, expect = pair(b1, (g1, y1g), b2, (g2, y2g))
        h1 = min(cands, key=lambda c: c[0])
        print(f"[{map_name}] 期望标记位移={expect} | "
              f"H1最佳 err={h1[0]:.1f} {h1[3][:2]}->{h1[4][:2]}")
        if h1[0] < 20:
            a, b = h1[3], h1[4]
            oxa, oya = a[0] - S * g1, a[1] - S * y1g
            oxb, oyb = b[0] - S * g2, b[1] - S * y2g
            ox, oy = (oxa + oxb) / 2, (oya + oyb) / 2
            spread = ((oxa - oxb) ** 2 + (oya - oyb) ** 2) ** 0.5
            print(f"[{map_name}] origin=({ox:.1f},{oy:.1f}) 两点偏差={spread:.1f}px")
            report[map_name] = {"origin": [ox, oy], "spread": spread}
        else:
            report[map_name] = {"error": f"H1配对失败 err={h1[0]:.1f}",
                                "expect": list(expect)}
    with open(r'E:\DS\mhxy-gui-automation\debug_anchor_fit4.json', 'w',
              encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
