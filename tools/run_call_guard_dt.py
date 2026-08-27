# -*- coding: utf-8 -*-
"""运行 MPCG_call_guard 验证大唐官府护法完整流程"""
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from library.map_packs import MPCG as M

GW = "http://127.0.0.1:18083"
r = M.MPCG_call_guard(map_name="大唐官府", gateway=GW, verbose=True)
print("=" * 60)
print(json.dumps(r, ensure_ascii=False, indent=1))