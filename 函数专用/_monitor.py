# -*- coding: utf-8 -*-
"""持续观察 run.log + 网关状态。"""
import os
import sys
import json
import time
import urllib.request

RUN_LOG = r"E:\DS\mhxy-gui-automation\函数专用\run.log"
GW = "http://127.0.0.1:18082"


def gw_online():
    try:
        req = urllib.request.Request(GW + "/api/status")
        r = json.loads(urllib.request.urlopen(req, timeout=3).read().decode("utf-8", "replace"))
        st = r.get("result") or {}
        return st.get("attached") and st.get("lua_state_captured")
    except Exception:
        return None  # 解不开=离线


def tail(path, n=0):
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()
    return lines[-n:] if n else lines


if __name__ == "__main__":
    # 刚启动：报告 run.log 最新 10 行 + 网关状态
    print("run.log 存在:", os.path.exists(RUN_LOG), flush=True)
    if os.path.exists(RUN_LOG):
        for ln in tail(RUN_LOG, 10):
            print(ln.rstrip(), flush=True)
    print("网关在线:", gw_online(), flush=True)