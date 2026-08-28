# -*- coding: utf-8 -*-
"""验证 2026-08-29 两项修复（用后即删）：
1) _dismiss_engine_error_dialog 能点掉标题"致命的错误"的真实 MessageBox；
2) _http_json 读超时不再立即 raise——挂起重试，恢复后无缝续跑。
"""
import sys, os, time, json, threading, subprocess
import socketserver, http.server

ROOT = r"E:\DS\mhxy-gui-automation"
sys.path.insert(0, ROOT)

# ---------- 测试 1：弹窗点掉 ----------
child = subprocess.Popen(
    [sys.executable, "-c",
     "import ctypes;ctypes.windll.user32.MessageBoxW(0,'this arg is not a userdata!','致命的错误',0)"],
    cwd=ROOT)
time.sleep(1.5)
assert child.poll() is None, "子进程弹窗未存活，测试环境异常"

import importlib.util
spec = importlib.util.spec_from_file_location(
    "WORLD_BOSS", os.path.join(ROOT, "tasks", "library", "WORLD_BOSS.py"))
WB = importlib.util.module_from_spec(spec)
spec.loader.exec_module(WB)

ok = WB._dismiss_engine_error_dialog()
t0 = time.time()
try:
    child.wait(timeout=10)
except subprocess.TimeoutExpired:
    pass
gone = child.poll() is not None
print(f"[T1] dismiss={ok} 弹窗已关闭={gone} 耗时={time.time()-t0:.1f}s")
assert ok and gone, "T1 失败：弹窗未被点掉"

# ---------- 测试 2：读超时挂起重试，第二次成功 ----------
class StallHandler(http.server.BaseHTTPRequestHandler):
    hits = {"n": 0}
    def do_POST(self):
        StallHandler.hits["n"] += 1
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if StallHandler.hits["n"] == 1:
            time.sleep(30)           # 第一发：不响应，逼客户端读超时
        else:
            body = json.dumps({"ok": True, "result": {"value": "RECOVERED"}}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    def log_message(self, *a):
        pass

srv = socketserver.TCPServer(("127.0.0.1", 18099), StallHandler)
srv.allow_reuse_address = True
threading.Thread(target=srv.serve_forever, daemon=True).start()

t0 = time.time()
r = WB._http_json("http://127.0.0.1:18099", "/api/lua",
                  {"code": "x"}, timeout=2.0)
dt = time.time() - t0
print(f"[T2] 第{StallHandler.hits['n']}次请求成功 result={r.get('result', {}).get('value')} 耗时={dt:.1f}s")
assert r.get("result", {}).get("value") == "RECOVERED", "T2 失败：未恢复"
assert StallHandler.hits["n"] >= 2, "T2 失败：没有重试"

# ---------- 测试 3：持续超时最终放弃（不永久卡死）----------
WB.GATEWAY_DOWN_MAX_WAIT_S = 6.0   # 缩短挂起上限

class AlwaysStallHandler(StallHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        time.sleep(30)

srv2 = socketserver.TCPServer(("127.0.0.1", 18098), AlwaysStallHandler)
threading.Thread(target=srv2.serve_forever, daemon=True).start()

t0 = time.time()
try:
    WB._http_json("http://127.0.0.1:18098", "/api/lua", {"code": "x"}, timeout=2.0)
    print("[T3] 失败：未按预期 raise")
except Exception as e:
    print(f"[T3] 挂起 {time.time()-t0:.1f}s 后按预期放弃: {type(e).__name__}")
    assert time.time() - t0 >= 5.5, "T3 失败：放弃过早"

srv.shutdown(); srv2.shutdown()
print("ALL_PASS")
