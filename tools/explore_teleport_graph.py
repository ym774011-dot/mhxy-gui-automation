# -*- coding: utf-8 -*-
"""BFS 探测全服传送路线图（tp.场景.传送），存 data/teleport_routes.json。

v2 改动（2026-08-27）：
  - 跨次运行累积：加载已有 json，已 dump 的图不重复 dump，但未探测的邻边继续展开
  - 自动寻路：沿已知图 hop 到有未探测边的 frontier 节点再展开（支持多段路径）
  - desc 三种格式都认：'X传送Y' / 'X进Y' / 'X出Y'
  - 子场景（酒店/铺/店/塔…）不展开，防图爆炸
"""
import json
import os
import re
import sys
import time
from collections import deque

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from tasks.library import WORLD_BOSS as WB

OUT_PATH = os.path.join(_PROJECT_ROOT, "data", "teleport_routes.json")

SUBLOC_RE = re.compile(
    r"酒店|铺|店|寺|塔|殿|国子监|阁|布庄|镖局|斋|堂|官府|路口|一层|二层|三层"
    r"|衙门|钱庄|李府|猎户|民居|合生记")


def canon_dest(dest):
    for known in list(WB.DEFAULT_MONITORED_MAPS) + ["大唐国境"]:
        if known in dest:
            return known
    return dest


def extract_dest(desc):
    m = re.search(r"(?:传送|进|出)(.+)$", desc)
    return m.group(1).strip() if m else ""


def dump_table(gw):
    code = (
        'local out = "" '
        'local t = tp.场景.传送 '
        'if t then for i = 1, #t do '
        '  local s = tostring(t[i].切换 or "") '
        '  local xy = "-,-" '
        '  if t[i].坐标 then xy = tostring(t[i].坐标.x) .. "," .. tostring(t[i].坐标.y) end '
        '  out = out .. s .. "|" .. xy .. ";" '
        'end end '
        '_G.__out = out'
    )
    d = WB._http_json(gw, "/api/lua", {"code": code})
    v = d.get("result", {}).get("value") or ""
    out = []
    for item in v.split(";"):
        item = item.strip()
        if "|" not in item:
            continue
        desc, xy = item.rsplit("|", 1)
        try:
            x, y = (int(float(p)) for p in xy.split(","))
        except ValueError:
            x = y = 0
        out.append({"desc": desc, "x": x, "y": y})
    return out


def map_id(gw):
    try:
        return WB._lua_expr(gw, "tostring(tp.当前地图 or '')").strip()
    except Exception:
        return ""


def save(id_to_name, graph):
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump({"id_to_name": id_to_name, "graph": graph},
                  f, ensure_ascii=False, indent=1)


def main():
    gw = WB.DEFAULT_GATEWAY
    # 等战斗结束
    t0 = time.time()
    while WB._in_battle(gw) and time.time() - t0 < 90:
        time.sleep(3.0)

    if os.path.exists(OUT_PATH):
        with open(OUT_PATH, encoding="utf-8") as f:
            saved = json.load(f)
    else:
        saved = {"id_to_name": {}, "graph": {}}
    id_to_name = dict(WB.MAP_ID_TO_NAME)
    for k, v in saved.get("id_to_name", {}).items():
        if not id_to_name.get(k):
            id_to_name[k] = v
    graph = dict(saved.get("graph", {}))
    visited = set(graph.keys())
    name_to_id = {v: k for k, v in id_to_name.items()}

    def node_pending(nid):
        """该图是否还有未探测的可行邻边。未知图视为有。"""
        if nid not in graph:
            return True
        for e in graph[nid]["routes"]:
            raw = extract_dest(e["desc"])
            if not raw or SUBLOC_RE.search(raw):
                continue
            d = canon_dest(raw)
            did = name_to_id.get(d)
            if did is None or did not in visited:
                return True
        return False

    def bfs_frontier(start_id):
        """沿已知图寻路到最近的有未探测边的节点，返回边列表或 None。"""
        q = deque([(start_id, [])])
        seen = {start_id}
        while q:
            node, path = q.popleft()
            for e in graph.get(node, {}).get("routes", []):
                raw = extract_dest(e["desc"])
                if not raw or SUBLOC_RE.search(raw):
                    continue
                d = canon_dest(raw)
                nid = name_to_id.get(d)
                if nid is None:
                    return path + [e]        # 全新图
                if nid in seen:
                    continue
                if nid not in visited or node_pending(nid):
                    return path + [e]
                q.append((nid, path + [e]))
                seen.add(nid)
        return None

    def do_hop(e):
        """执行一次 cross_map hop 并确认 ID 变化。返回新 ID 或 None。"""
        before = map_id(gw)
        raw = extract_dest(e["desc"])
        d = canon_dest(raw)
        cx, cy = WB.DEFAULT_MAP_CENTER.get(d, (10, 10))
        try:
            res = WB._http_json(gw, "/api/act/cross_map",
                                {"desc": e["desc"], "x": cx, "y": cy,
                                 "wait_ms": 3500, "sync": True}, timeout=25.0)
        except Exception as ex:
            print(f"   [hop err] {e['desc']}: {ex}")
            return None
        if not res.get("ok"):
            print(f"   [hop fail] {e['desc']}: {res.get('error')}")
            return None
        deadline = time.time() + 12.0
        after = before
        while time.time() < deadline:
            time.sleep(1.5)
            after = map_id(gw)
            if after and after != before:
                break
        if after == before:
            print(f"   [hop dead] {e['desc']}: ID未变({before})")
            return None
        known_nm = id_to_name.get(after, "")
        nm = d if (known_nm.startswith("未知") or not known_nm) else known_nm
        id_to_name[after] = nm
        name_to_id[nm] = after
        print(f"   [hop OK] {e['desc']}: {before}->{after} ({nm})")
        return after

    start_id = map_id(gw)
    print(f"起点: id={start_id} name={id_to_name.get(start_id)}  已知图: {len(visited)}")
    hops = 0
    MAX_HOPS = 40
    while hops < MAX_HOPS:
        cur = map_id(gw)
        if not cur:
            print("!! 读不到当前地图 ID，中止")
            break
        if cur not in graph:
            entries = dump_table(gw)
            nm = id_to_name.get(cur, f"未知{cur}")
            graph[cur] = {"name": nm, "routes": entries}
            visited.add(cur)
            print(f"\n== [{cur}] {nm}: {len(entries)} 条路线")
            for e in entries:
                print(f"   {e['desc']}  @{e['x']},{e['y']}")
            save(id_to_name, graph)
            time.sleep(0.5)
        path = bfs_frontier(cur)
        if not path:
            print("\n所有可达图已探测完")
            break
        for e in path:
            if do_hop(e):
                hops += 1
            time.sleep(1.0)

    save(id_to_name, graph)
    print(f"\n完成: {len(visited)} 图已 dump, 共 {hops} 次 hop, 存 {OUT_PATH}")
    print("ID 表:", id_to_name)


if __name__ == "__main__":
    main()
