# -*- coding: utf-8 -*-
"""确认当前门派闯关的目标门派"""
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from library.map_packs import MPCG as M
r = M.MPCG_open_taskbar(gateway="http://127.0.0.1:18083", verbose=True)
print(json.dumps(r, ensure_ascii=False, indent=1))