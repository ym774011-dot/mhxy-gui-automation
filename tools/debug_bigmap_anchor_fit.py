# -*- coding: utf-8 -*-
"""大图锚定拟合器：同图多点瞬移 → Tab 截大图 → 自动检测红点标记 → 拟合
   pixel = origin + scale * game（每图一组参数）。

残差小 → 每图固定原点（校准只需按图存 origin/scale）。
残差大且系统性 → 视角随角色平移（需角色锚定模型）。
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

PLAN = {
    "建邺城": {
        "chain": ["江南野外传送建邺城"],
        "coords": [(40, 40), (200, 40), (60, 110), (180, 90), (270, 80)],
    },
    "江南野外": {
        "chain": ["建邺城传送江南野外"],
        "coords": [(30, 30), (120, 30), (30, 90), (120, 90)],
    },
}


def post(path, body):
    req = urllib.request.Request(
        GW + path, json.dumps(body).encode("utf-8"),
        {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def cross_map(desc, x, y):
    return post("/api/act/cross_map", {"desc": desc, "x": x, "y": y})


def wait_battle(max_s=60):
    t0 = time.time()
    while time.time() - t0 < max_s:
        if d.expr("tostring(tp.战斗中)") != "true":
            return True
        time.sleep(1.5)
    return False


def find_red_dots(png_path):
    """检测大图红点标记：纯红圆斑 d=5~16px，实心。返回 [(cx,cy)]（按面积降序）。"""
    img = Image.open(png_path).convert("RGB")
    w, h = img.size
    px = img.load()
    mask = [[False] * w for _ in range(h)]
    for j in range(h):
        for i in range(w):
            r, g, b = px[i, j]
            if r > 180 and g < 90 and b < 90:
                mask[j][i] = True
    seen = [[False] * w for _ in range(h)]
    dots = []
    for j in range(h):
        for i in range(w):
            if mask[j][i] and not seen[j][i]:
                stack = [(i, j)]
                seen[j][i] = True
                pts = []
                while stack:
                    x, y = stack.pop()
                    pts.append((x, y))
                    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        nx, ny = x + dx, y + dy
                        if 0 <= nx < w and 0 <= ny < h and mask[ny][nx] \
                                and not seen[ny][nx]:
                            seen[ny][nx] = True
                            stack.append((nx, ny))
                if len(pts) < 20:
                    continue
                xs = [p[0] for p in pts]
                ys = [p[1] for p in pts]
                bw, bh = max(xs) - min(xs) + 1, max(ys) - min(ys) + 1
                if not (5 <= bw <= 18 and 5 <= bh <= 18):
                    continue
                if not (0.7 <= bw / bh <= 1.4):
                    continue
                density = len(pts) / (bw * bh)
                if density < 0.55:
                    continue
                dots.append((sum(xs) / len(xs), sum(ys) / len(ys), len(pts)))
    dots.sort(key=lambda t: -t[2])
    return dots


def fit(samples):
    """最小二乘 px = ox + s*game（x/y 各自独立拟合）。samples=[(gx,gy,px,py)]"""
    n = len(samples)
    res = {}
    for gk, pk in ((0, 2), (1, 3)):
        gs = [s[gk] for s in samples]
        ps = [s[pk] for s in samples]
        mg = sum(gs) / n
        mp = sum(ps) / n
        s = sum((g - mg) * (p - mp) for g, p in zip(gs, ps)) / \
            sum((g - mg) ** 2 for g in gs)
        o = mp - s * mg
        resid = [abs(o + s * g - p) for g, p in zip(gs, ps)]
        res[gk] = (o, s, max(resid), sum(resid) / n)
    return res


def run_map(map_name, cfg, wm, shot_dir):
    # 跨图链
    for desc in cfg["chain"]:
        wait_battle()
        r = cross_map(desc, 100, 100)
        if not r.get("ok"):
            print(f"!! cross_map {desc} 失败: {r}")
            return
        time.sleep(1.5)
    got = d.expr('tostring(tp.场景.地图.名称)')
    print(f"[{map_name}] 到图, Lua地图名={got}")
    samples = []
    for k, (x, y) in enumerate(cfg["coords"]):
        wait_battle()
        post("/api/act/teleport", {"x": x, "y": y})
        time.sleep(1.0)
        gx, gy = d.role_grid()
        path = rf"{shot_dir}\anchor_{map_name}_{k}.png"
        d.press_tab(wm.hwnd)
        d.bitblt_window(wm.hwnd, path)
        d.press_tab(wm.hwnd)
        dots = find_red_dots(path)
        if not dots:
            print(f"  {map_name} ({gx:.0f},{gy:.0f}) 未检出红点 dots={dots}")
            continue
        cx, cy, area = dots[0]
        samples.append((gx, gy, cx, cy))
        print(f"  {map_name} ({gx:.0f},{gy:.0f}) -> 红点({cx:.1f},{cy:.1f}) "
              f"area={area} 其余候选={[(round(a,1),round(b,1),c) for a,b,c in dots[1:3]]}")
        time.sleep(0.4)
    if len(samples) >= 3:
        r = fit(samples)
        print(f"[{map_name}] origin=({r[0][0]:.1f},{r[1][0]:.1f}) "
              f"scale=({r[0][1]:.4f},{r[1][1]:.4f}) "
              f"maxresid=({r[0][2]:.1f},{r[1][2]:.1f})px")
    else:
        print(f"[{map_name}] 样本不足({len(samples)})，无法拟合")
    return samples


def main():
    wm = WindowManager()
    wm.bind(pid=4172)
    out = {}
    for name, cfg in PLAN.items():
        out[name] = run_map(name, cfg, wm, r'E:\DS\mhxy-gui-automation')
    with open(r'E:\DS\mhxy-gui-automation\debug_anchor_fit.json', 'w',
              encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("已存 debug_anchor_fit.json")


if __name__ == "__main__":
    main()
