# -*- coding: utf-8 -*-
"""全图瞬移测试：对监控地图逐一 cross_map，记录 ID 变化 + 截图左上角地名。"""
import sys, os, time, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tasks.library import WORLD_BOSS as WB
from core import window_manager as wm

GW = WB.DEFAULT_GATEWAY
MAPS = ["宝象国", "东海湾", "长寿村", "朱紫国", "长寿郊外",
        "江南野外", "建邺城", "大唐国境", "大唐境外", "花果山"]

mgr = wm.WindowManager()
if not mgr.try_restore_last_binding():
    mgr.bind(pid=15224)
mgr.update_rect()

import mss
from mss.tools import to_png


def shot_corner(tag):
    l, t, r, b = mgr.get_client_rect()
    mon = {"left": l, "top": t, "width": 240, "height": 60}
    img = mss.mss().grab(mon)
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"corner_{tag}.png")
    to_png(img.rgb, img.size, output=p)
    return p


results = []
for name in MAPS:
    rec = {"target": name}
    try:
        before = WB._lua_expr(GW, "tostring(tp.当前地图)")
        rec["before"] = before
        d = WB._gw_cross_map(GW, name)
        rec["gw"] = {k: d.get(k) for k in ("ok", "route", "hop", "error", "detail") if k in d}
        time.sleep(2.5)
        after = WB._lua_expr(GW, "tostring(tp.当前地图)")
        rec["after"] = after
        rec["battle"] = WB._in_battle(GW)
        rec["captcha"] = WB._captcha_active(GW)
        rec["corner_png"] = os.path.basename(shot_corner(name))
        rec["moved"] = (before != after)
    except Exception as e:
        rec["error"] = repr(e)
    results.append(rec)
    print(json.dumps(rec, ensure_ascii=False))

with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "tp_test_result.json"), "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=1)
print("DONE")
