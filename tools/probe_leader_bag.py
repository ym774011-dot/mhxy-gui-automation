# -*- coding: utf-8 -*-
"""只读探针：查指定文件通道角色的背包可见性/占用/可售列表。用法: python probe_leader_bag.py [gateway]"""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
spec = importlib.util.spec_from_file_location(
    "ZGUI", os.path.join(ROOT, "tasks", "library", "ZGUI.py"))
ZGUI = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ZGUI)

gw = sys.argv[1] if len(sys.argv) > 1 else "file://pzxy_p6880"
print("gateway:", gw)
print("bag_visible:", ZGUI._bag_visible(gw))
print("bag_used_count:", ZGUI._bag_used_count(gw))
items = ZGUI._sellable_items(gw)
print("sellable_items:", len(items))
for it in items[:12]:
    print("  ", it)
