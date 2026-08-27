# -*- coding: utf-8 -*-
"""验证下一个门派护法（默认魔王寨 29,43）"""
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from library.map_packs import MPCG as M
GW="http://127.0.0.1:18083"
target = sys.argv[1] if len(sys.argv) > 1 else "魔王寨"
r = M.MPCG_call_guard(map_name=target, gateway=GW, verbose=True)
print(json.dumps(r, ensure_ascii=False, indent=1))