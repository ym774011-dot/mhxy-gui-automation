# -*- coding: utf-8 -*-
"""整夜全量测试守护（到 12:00）
- 强制清除 WORLDBOSS_NO_CROSS 残留
- 循环调用 WORLD_BOSS_auto_farm：每次限 max_runtime，异常/自然结束后
  自动重连网关+重绑进程并重启下一轮，直到到达结束时间
- 每轮结束打印汇总，错落休息 5s 防风暴
★2026-09-01 07:08 重启原因：修复「开包点击固定点(695,601)命中常驻商人 →
  弹窗关不掉 → 飞行符跨图全退 hop 链」的轮换点位逻辑，需重启加载新代码。"""
import sys, os, json, time, psutil
from datetime import datetime as _dt

# ★2026-09-01 内部日志 Tee：Python 自行追加写日志文件（绕过 shell 重定向截断问题）
_LOG_PATH = r"E:\DS\tmp\night_guard_0901.log"
_logf = open(_LOG_PATH, "a", encoding="utf-8", buffering=1)


class _Tee:
    def __init__(self, *streams):
        self.streams = streams

    def write(self, s):
        for st in self.streams:
            try:
                st.write(s)
                st.flush()
            except Exception:
                pass
        return len(s)

    def flush(self):
        for st in self.streams:
            try:
                st.flush()
            except Exception:
                pass


sys.stdout = _Tee(sys.__stdout__, _logf)
sys.stderr = _Tee(sys.__stderr__, _logf)

os.environ.pop("WORLDBOSS_NO_CROSS", None)
for _f in (r"E:\DS\WORLDBOSS_NO_CROSS.flag",):
    try:
        if os.path.exists(_f):
            os.remove(_f)
            print("已删除残留 flag:", _f, flush=True)
    except Exception:
        pass

_ROOT = r"E:\DS\mhxy-gui-automation"
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

END_STR = "2026-09-01T12:00:00"
END_TS = _dt.strptime(END_STR, "%Y-%m-%dT%H:%M:%S").timestamp()

from core.task_library_manager import task_library
n = task_library.load_from_config()
print("模块加载:", n, flush=True)

def ensure_bound():
    """确保绑定最新游戏进程 + 网关在线。"""
    from core.window_manager import window_manager
    pids = [p.info["pid"] for p in psutil.process_iter(attrs=["pid", "name"])
            if "十年一梦" in p.info["name"]]
    if not pids:
        return None
    window_manager.bind(pid=int(max(pids)))
    from core.gateway_guard import ensure_gateway
    ok, info = ensure_gateway(timeout=90.0, verbose=False)
    return max(pids) if ok else None

round_no = 0
total_farmed = 0
while time.time() < END_TS:
    round_no += 1
    remain = END_TS - time.time()
    runtime = min(3000.0, max(600.0, remain - 60))   # 每轮最长 50min，留收尾余量
    print("\n" + "=" * 60, flush=True)
    print("[第%d轮] %s 剩余 %.0fmin  本轮 max_runtime=%.0fs"
          % (round_no, _dt.now().strftime("%H:%M:%S"), remain / 60, runtime), flush=True)
    print("=" * 60, flush=True)

    pid = ensure_bound()
    if pid is None:
        print("!! 找不到游戏进程，60s 后重试...", flush=True)
        time.sleep(60)
        continue

    kwargs = {
        "max_runtime": int(runtime),
        "chat_poll_interval": 1.5,
        "boss_scan_interval": 1.0,
        "clear_timeout": 10.0,
        "battle_timeout": 180.0,
        "walk_background": True,
        "verbose": True,
        "xiang_enabled": True,
        "xiang_interval_min": 300,
    }
    try:
        ok, result, err = task_library.call_function(
            "WORLD_BOSS", "WORLD_BOSS_auto_farm", **kwargs)
        print("[第%d轮] 返回 ok=%s" % (round_no, ok), flush=True)
        if result and isinstance(result, dict):
            f = result.get("farmed_total", 0) or 0
            total_farmed += f
            print("[第%d轮] 本轮击杀 %d，累计 %d" % (round_no, f, total_farmed), flush=True)
        if err:
            print("[第%d轮] err=%s" % (round_no, str(err)[:500]), flush=True)
    except Exception as e:
        print("[第%d轮] 异常: %s" % (round_no, repr(e)[:500]), flush=True)

    # 轮间：重连网关 + 短休，异常自愈后进入下一轮
    try:
        ensure_bound()
    except Exception:
        pass
    time.sleep(5)

print("\n=== 07:10 到达，整夜全量测试结束 ===", flush=True)
print("总击杀: %d" % total_farmed, flush=True)