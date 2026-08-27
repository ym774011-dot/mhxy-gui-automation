# -*- coding: utf-8 -*-
"""实测 PID17000 网关下，会员卡瞬移全部 15 个门派（MPCG_teleport_sect）。"""
import sys, json, time
sys.path.insert(0, r"E:\DS\mhxy-gui-automation")
import library.map_packs.MPCG as M

GW = "http://127.0.0.1:18083"

print("15 门派全量瞬移测试（PID 绑网关）")
print("=" * 60)
ok_cnt = 0
fail = []
for name in M.SECT_LIST_15:
    r = M.MPCG_teleport_sect(map_name=name, gateway=GW, verbose=False)
    mark = "OK " if r.get("ok") else "FAIL"
    if r.get("ok"):
        ok_cnt += 1
    else:
        fail.append(name)
    print(f"[{mark}] {name:<6} src={r.get('source','-'):<6} "
          f"map={r.get('map_id','-')} arrived={r.get('arrived_map_id','-')} "
          f"| {r.get('message','')}")
    time.sleep(1.5)  # 每次跳换之间停留，避免刷屏

print("=" * 60)
print(f"通过 {ok_cnt}/15；失败: {fail if fail else '无'}")