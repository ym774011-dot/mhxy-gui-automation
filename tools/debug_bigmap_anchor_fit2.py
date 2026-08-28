# -*- coding: utf-8 -*-
"""大图锚定 v2：运动对应法。

每图 2 个远距安全点 → 各截大图 → 检测所有"实心红圆盘"候选 →
按 |Δ候选 − 0.841×Δgame| 最小配对 = 角色标记（装饰不动，会被排除）。
"""
import json
import sys
import time
import urllib.request

sys.path.insert(0, r'E:\DS\mhxy-gui-automation')
sys.path.insert(0, r'E:\DS\mhxy-gui-automation\tools')
from core.window_manager import WindowManager  # noqa: E402
import debug_bigmap_shot as d  # noqa: E402
from PIL import Image  # noqa: E402

GW = "http://127.0.0.1:18082"
SCALE0 = 0.841
# 大图面板内部裁剪（排除右侧传送勾选列、左侧聊天、顶部静态红图标）
CROP = (225, 195, 688, 470)

PLAN = [
    # (地图, 跨图链, [p1, p2]) 坐标均避开已知热点
    ("江南野外", ["建邺城传送江南野外"], [(30, 30), (120, 100)]),
    ("建邺城", ["江南野外传送建邺城"], [(100, 100), (200, 40)]),
    ("大唐国境", ["长安传送大唐国境"], [(150, 120), (210, 160)]),
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


def red_discs(png):
    """裁剪区域内找实心红圆盘候选。返回 [(cx,cy,area,bw,bh)]"""
    img = Image.open(png).convert("RGB")
    x0, y0, x1, y1 = CROP
    w, h = img.size
    px = img.load()
    mask = {}
    for j in range(max(0, y0), min(h, y1)):
        for i in range(max(0, x0), min(w, x1)):
            r, g, b = px[i, j]
            if r > 180 and g < 90 and b < 90:
                mask[(i, j)] = True
    seen = set()
    out = []
    for (si, sj) in list(mask):
        if (si, sj) in seen:
            continue
        stack = [(si, sj)]
        seen.add((si, sj))
        pts = []
        while stack:
            x, y = stack.pop()
            pts.append((x, y))
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                n = (x + dx, y + dy)
                if n in mask and n not in seen:
                    seen.add(n)
                    stack.append(n)
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        bw, bh = max(xs) - min(xs) + 1, max(ys) - min(ys) + 1
        density = len(pts) / (bw * bh)
        # 实心圆盘：8~14px 方形、密度>0.7
        if 8 <= bw <= 14 and 8 <= bh <= 14 and density > 0.7:
            out.append((sum(xs) / len(xs), sum(ys) / len(ys), len(pts)))
    return out


def shoot_with_map(wm, tag):
    """开大图截图；失败重试一次。"""
    for attempt in range(2):
        path = rf'E:\DS\mhxy-gui-automation\anchor2_{tag}.png'
        d.press_tab(wm.hwnd)
        time.sleep(1.2)
        d.bitblt_window(wm.hwnd, path)
        d.press_tab(wm.hwnd)
        time.sleep(0.6)
        discs = red_discs(path)
        if discs:
            return path, discs
        time.sleep(0.5)
    return path, discs


def main():
    wm = WindowManager()
    wm.bind(pid=4172)
    report = {}
    for map_name, chain, (p1, p2) in PLAN:
        for desc in chain:
            wait_battle()
            r = post("/api/act/cross_map", {"desc": desc, "x": p1[0], "y": p1[1]})
            if not r.get("ok"):
                print(f"!! {map_name} cross_map {desc} 失败: {r}")
                break
            time.sleep(1.5)
        wait_battle()
        samples = []
        prev_discs = None
        prev_g = None
        for k, (x, y) in enumerate((p1, p2)):
            wait_battle()
            post("/api/act/teleport", {"x": x, "y": y})
            time.sleep(1.0)
            gx, gy = d.role_grid()
            path, discs = shoot_with_map(wm, f"{map_name}_{k}")
            print(f"[{map_name}] p{k} 目标({x},{y}) 实读({gx:.0f},{gy:.0f}) "
                  f"候选={[(round(a,1), round(b,1), c) for a,b,c in discs]}")
            if prev_discs is None:
                prev_discs, prev_g = discs, (gx, gy)
                samples.append((gx, gy, discs))
                continue
            # 运动配对
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
                print(f"    配对: {a[:2]} -> {b[:2]} 误差{best[0]:.1f}px")
                samples.append((gx, gy, [b]))
            else:
                print(f"    配对失败 best={best and best[0]:.1f}")
        # 用两个点解 origin（scale 锁 0.841，只解原点，取两点平均）
        pts = []
        if len(samples) == 2 and samples[0][2] and samples[1][2]:
            a = samples[0][2][0]
            b = samples[1][2][0]
            oxa = a[0] - SCALE0 * samples[0][0]
            oya = a[1] - SCALE0 * samples[0][1]
            oxb = b[0] - SCALE0 * samples[1][0]
            oyb = b[1] - SCALE0 * samples[1][1]
            ox, oy = (oxa + oxb) / 2, (oya + oyb) / 2
            spread = ((oxa - oxb) ** 2 + (oya - oyb) ** 2) ** 0.5
            print(f"[{map_name}] origin=({ox:.1f},{oy:.1f}) "
                  f"两点一致性偏差={spread:.1f}px "
                  f"({'固定原点 ✓' if spread < 8 else '原点漂移? ✗'})")
            report[map_name] = {"origin": [ox, oy], "scale": SCALE0,
                                "spread": spread}
        else:
            report[map_name] = {"error": "样本不足"}
    with open(r'E:\DS\mhxy-gui-automation\debug_anchor_fit2.json', 'w',
              encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
