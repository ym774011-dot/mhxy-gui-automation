# -*- coding: utf-8 -*-
"""全链路实弹测试：公告 -> 跨图 -> 扫描 -> 走路/CALL -> 战斗。

正常工作模式：默认目标表全量 BOSS，按优先级打
（三界财神爷 > 知了王 > 其他，代码 _boss_priority 已内置）。
先按网关 /api/status 的已注入 PID 绑定 window_manager，保证走路可用
（不绑定会退化成瞬移环带，违反防举报要求）。
"""
import json
import sys

sys.path.insert(0, r"E:/DS/mhxy-gui-automation")

from urllib.request import Request, urlopen

from tasks.library.WORLD_BOSS import (
    DEFAULT_GATEWAY,
    DEFAULT_MONITORED_MAPS,
    DEFAULT_TARGET_BOSSES,
    WORLD_BOSS_auto_farm,
)


def gateway_pid(gateway: str):
    try:
        with urlopen(Request(gateway.rstrip("/") + "/api/status"), timeout=10) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
        pid = ((data.get("result") or {}).get("pid")) or data.get("pid")
        print("[bind] /api/status result.pid ->", pid)
        return pid
    except Exception as e:
        print("[bind] /api/status 失败:", e)
        return None


def main() -> None:
    pid = gateway_pid(DEFAULT_GATEWAY)
    if pid:
        try:
            from core.window_manager import window_manager
            window_manager.bind(pid=int(pid))
            print("[bind] window_manager.bind(pid=%s) ok, bound=%s"
                  % (pid, window_manager.bound))
        except Exception as e:
            print("[bind] 绑定失败（走路会退化为瞬移兜底！）:", e)
    else:
        print("[bind] 拿不到网关 PID，跳过绑定（走路会退化为瞬移兜底！）")

    res = WORLD_BOSS_auto_farm(
        monitored_maps=list(DEFAULT_MONITORED_MAPS),
        target_bosses=list(DEFAULT_TARGET_BOSSES),   # 全目标，按优先级打
        max_runtime=900,        # 15 分钟实测窗口
        clear_timeout=12.0,
        battle_timeout=240.0,
        walk_background=True,
        verbose=True,
    )
    print("AUTO_FARM_RESULT:", json.dumps(res, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
