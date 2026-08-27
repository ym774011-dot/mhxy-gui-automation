# -*- coding: utf-8 -*-
"""WORLD_BOSS 新增地图数据 全量实测
流程：跨图传送进入 → 记录实际地图ID/名 → 在角色当前位置附近做一次校准走路点击 → 等到达。
"""
import sys, os, time, random
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tasks.library.WORLD_BOSS import (
    _http_json, _lua_expr, _cur_map_name, _gw_cross_map,
    _walk_to, _role_grid, _grid_dist,
)

GW = "http://127.0.0.1:18082"
TEST_MAPS = ["傲来国", "大唐境外", "长寿郊外", "花果山", "大唐国境"]

print("== gateway 探测 ==")
try:
    cur0 = _cur_map_name(GW)
    print(f"当前地图: {cur0}")
except Exception as e:
    print(f"GATEWAY_ERR: {e}")
    sys.exit(1)

found_ids = {}
results = []
for m in TEST_MAPS:
    print(f"\n===== {m} =====")
    entry = {"map": m}
    try:
        # 1) 跨图传送进入（走传送路线，不瞬移落 BOSS）
        before = _cur_map_name(GW)
        r = _gw_cross_map(GW, m)
        time.sleep(2.5)
        # 读原始 ID 与名（用于补 MAP_ID_TO_NAME）
        try:
            raw_id = _lua_expr(GW, "tostring(tp.当前地图 or '')")
            raw_name = _lua_expr(GW, "tostring(tp.当前地图名 or '')")
            found_ids[m] = (raw_id, raw_name)
        except Exception:
            pass
        after = _cur_map_name(GW)
        ok_enter = (after == m) or (m.replace("城", "") in str(after)) or (str(after) in m)
        print(f"  进入: {before} -> {after}  raw_id={found_ids.get(m)}  {'OK' if ok_enter else 'MISMATCH'}")
        entry["enter"] = f"{after} ({'OK' if ok_enter else 'MISMATCH'})"
        if not ok_enter:
            entry["walk"] = "SKIP(未进图)"
            results.append(entry)
            continue

        # 2) 校准走路：目标 = 当前位置附近 ±5 格（小位移验证像素映射）
        rg = _role_grid(GW)
        if rg is None:
            print("  ! 读不到角色坐标，跳过走路")
            entry["walk"] = "SKIP(无角色坐标)"
            results.append(entry)
            continue
        jx = max(0, int(rg[0]) + random.randint(-5, 5))
        jy = max(0, int(rg[1]) + random.randint(-5, 5))
        print(f"  角色在 {tuple(round(v,1) for v in rg)}，试走 ({jx},{jy})")
        t0 = time.time()
        wres = _walk_to(m, jx, jy, background=True, verbose=True)
        print(f"  点击结果: {wres.get('message')}")
        # 3) 等到达
        arrived = False
        deadline = time.time() + 60
        while time.time() < deadline:
            rg2 = _role_grid(GW)
            if rg2 and _grid_dist(rg2, jx, jy) <= 6:
                arrived = True
                break
            time.sleep(1.5)
        dt = time.time() - t0
        rgf = _role_grid(GW)
        print(f"  到达: {'YES' if arrived else 'NO'} ({dt:.0f}s) 最终位置 "
              f"{tuple(round(v,1) for v in rgf) if rgf else '?'}")
        entry["walk"] = f"{'OK' if arrived else 'FAIL'} target=({jx},{jy}) final={tuple(round(v,1) for v in rgf) if rgf else '?'}"
    except Exception as e:
        print(f"  ! 异常: {e}")
        entry["walk"] = f"ERR {e}"
    results.append(entry)

print("\n===== 汇总 =====")
for e in results:
    print(f"{e['map']}: enter={e.get('enter')} walk={e.get('walk')}")
print("\n===== 实测地图ID（补 MAP_ID_TO_NAME 用） =====")
for m, (rid, rn) in found_ids.items():
    print(f"{m}: id={rid} name={rn}")
