# -*- coding: utf-8 -*-
"""实测 lua_call 受保护化（致命弹窗兜底）是否生效，且未破坏注入队列。

三项断言：
  A. 网关 attach 到目标 PID，Lua state 已捕获
  B. 网关日志出现 "lua_call 已受保护化"（兜底已装）
  C. 通过 /api/lua 真跑一次 Lua —— 这是最关键的一条：
     lua_call 的 onLeave 承担注入队列消费，若 Interceptor.replace 让它停摆，
     这里会直接超时挂死（请求永不返回）。

用法：E:/py/python.exe tools/_test_lua_call_guard.py
"""
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import gateway_guard as gg   # noqa: E402

PORT = int(gg._gw_port())
BASE = f"http://127.0.0.1:{PORT}"
GATEWAY_DIR = r"E:\DS\mhxy-mcp-gateway"
LOG = os.path.join(GATEWAY_DIR, f"gateway_run_{PORT}.log")

results = []


def check(name, ok, detail=""):
    results.append((ok, name, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name} {detail}")


def status():
    with urllib.request.urlopen(f"{BASE}/api/status", timeout=5) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def main():
    print("=" * 72)
    print(f"lua_call 受保护化 实测（网关端口 {PORT}）")
    print("=" * 72)

    # 1) 自愈：绑到当前存活的游戏实例
    print("\n[1] 自愈拉起网关并 attach 当前游戏实例")
    t0 = time.time()
    ok, info = gg.ensure_gateway(timeout=90.0, verbose=True)
    check("ensure_gateway", ok, f"耗时 {time.time() - t0:.1f}s info={info}")
    if not ok:
        return 1

    st = status().get("result", {})
    check("A. attach + Lua state 已捕获",
          bool(st.get("attached") and st.get("lua_state_captured")),
          f"pid={st.get('pid')} attached={st.get('attached')} "
          f"lua={st.get('lua_state_captured')}")

    # 2) 日志确认受保护化已装
    try:
        with open(LOG, "r", encoding="utf-8", errors="ignore") as f:
            tail = "".join(f.readlines()[-120:])
    except Exception as e:
        tail = ""
        print(f"  (读日志失败: {e})")
    check("B. 日志含 'lua_call 已受保护化'",
          "lua_call 已受保护化" in tail)
    check("B2. fatal_guard 未加载（默认关闭）",
          "fatal_guard 已默认关闭" in tail)

    # 3) 真跑一次 Lua —— 队列消费没被 replace 破坏就一定会返回
    print("\n[3] /api/lua 真跑一次（验证注入队列未被 replace 破坏）")
    code = "_G.__out = tostring(1+1)"
    body = json.dumps({"code": code, "result_var": "__out"}).encode("utf-8")
    req = urllib.request.Request(f"{BASE}/api/lua", data=body,
                                 headers={"Content-Type": "application/json"})
    t1 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            res = json.loads(r.read().decode("utf-8", "replace"))
        dt = time.time() - t1
        val = res.get("result", {}).get("value")
        check("C. /api/lua 正常返回（未死锁）",
              dt < 15 and val == "2", f"耗时 {dt:.2f}s value={val!r}")
    except Exception as e:
        check("C. /api/lua 正常返回（未死锁）", False, f"{type(e).__name__}: {e}")

    print("\n" + "=" * 72)
    n = sum(1 for r in results if r[0])
    print(f"结果：{n}/{len(results)} PASS")
    for ok_, name, d in results:
        if not ok_:
            print(f"  ✗ {name} {d}")
    print("=" * 72)
    return 0 if n == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
