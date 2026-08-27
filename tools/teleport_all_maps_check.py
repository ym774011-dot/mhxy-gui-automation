# -*- coding: utf-8 -*-
"""全图瞬移连通性检查（WORLD_BOSS 监控地图轮询一遍）v2。

改进（2026-08-27）：
  - 开跑前等待战斗结束（战斗中 1003 跨图会被拒绝）
  - 每跳后轮询 tp.当前地图 直到 ID 变化（切图加载需要时间）
  - 记录每图实测 ID 与 当前地图名（用于补 MAP_ID_TO_NAME）
  - 失败自动重试一次

用法:
    E:/py/python.exe tools/teleport_all_maps_check.py [--maps 地图1,地图2 ...]
"""
import os
import sys
import time

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from tasks.library import WORLD_BOSS as WB


def _map_id(gw):
    try:
        return WB._lua_expr(gw, "tostring(tp.当前地图 or '')").strip()
    except Exception:
        return ""


def _map_name(gw):
    try:
        return WB._lua_expr(gw, "tostring(tp.当前地图名 or '')").strip()
    except Exception:
        return ""


def _wait_battle_end(gw, timeout=120.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if not WB._in_battle(gw):
            return True
        time.sleep(3.0)
    return False


def _hop_and_verify(gw, target, x, y):
    """跨图并轮询确认 ID 变化。返回 (ok, id_after, name_after, note)。"""
    id_before = _map_id(gw)
    res = WB._gw_cross_map(gw, target, x, y)
    if not res.get("ok"):
        return False, id_before, "", f"接口错误: {res.get('error')}"
    # 轮询等 ID 变化
    deadline = time.time() + 12.0
    id_after, name_after = id_before, ""
    while time.time() < deadline:
        time.sleep(1.5)
        id_after = _map_id(gw)
        name_after = _map_name(gw)
        if id_after and id_after != id_before:
            break
    changed = bool(id_after and id_after != id_before)
    # 权威名优先
    if name_after and name_after != "nil":
        good = name_after == target or target in name_after or name_after in target
        note = f"name={name_after!r} id={id_after}"
        return good, id_after, name_after, note
    good = changed
    note = (f"id {id_before}->{id_after}" if changed
            else f"ID未变化({id_before})")
    return good, id_after, name_after, note


def main():
    gw = WB.DEFAULT_GATEWAY
    maps = list(WB.DEFAULT_MONITORED_MAPS)
    for i, a in enumerate(sys.argv):
        if a == "--maps" and i + 1 < len(sys.argv):
            maps = [m.strip() for m in sys.argv[i + 1].split(",") if m.strip()]

    print(f"gateway = {gw}")
    if not _wait_battle_end(gw):
        print("!! 战斗超过 120s 未结束，中止")
        return
    cur = _map_name(gw) or _map_id(gw)
    print(f"起始地图 = {cur!r}")

    discovered = {}   # target -> (id, name)
    rows = []
    for m in maps:
        if m == cur:
            rows.append((m, "SKIP(已在图)"))
            continue
        note = ""
        ok = False
        for attempt in (1, 2):
            if m in WB.DEFAULT_MAP_CENTER:
                x, y = WB.DEFAULT_MAP_CENTER[m]
                ok, id_a, name_a, note = _hop_and_verify(gw, m, x, y)
            else:
                ok, id_a, name_a, note = _hop_and_verify(gw, m, None, None)
            if ok:
                break
            print(f"  [retry] {m} 第{attempt}次失败: {note}")
            time.sleep(2.0)
        discovered[m] = (id_a, name_a)
        rows.append((m, ("OK  " if ok else "FAIL") + " " + note))
        cur = m if ok else cur
        time.sleep(0.8)

    print("\n===== 结果 =====")
    for m, s in rows:
        print(f"  {m:<6} {s}")
    print("\n===== ID 发现（补 MAP_ID_TO_NAME 用）=====")
    for m, (i_, n_) in discovered.items():
        print(f"  {m}: id={i_} 当前地图名={n_ or '(nil)'}")
    fails = [m for m, s in rows if s.startswith("FAIL")]
    print(f"\n共 {len(rows)} 图, FAIL {len(fails)}: {fails}")


if __name__ == "__main__":
    main()
