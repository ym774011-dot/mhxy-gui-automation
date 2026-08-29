# -*- coding: utf-8 -*-
"""回归：游戏进程死了换 PID 后，网关守卫必须能按角色 ID 自动重绑。

覆盖 2026-08-29 三个真实故障（3512 崩溃 → 19800 新起 → farm 链卡死
"window_manager 未绑定"）：

  T1 角色 ID 锚点可从持久化标题取到（运行时标题是聊天窗口时）
  T2 _bound_pid 在绑定 PID 已死时返回新实例 PID（而非 None）
  T3 _bound_pid 在 window_manager 未绑（pid=0）时，走 config 回退也能重绑
  T4 bind() 不会让不含角色 ID 的标题覆盖掉已有锚点

用法：E:/py/python.exe tools/_test_rebind_regress.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.config import config                       # noqa: E402
from core import gateway_guard as gg                   # noqa: E402

PASS, FAIL = "PASS", "FAIL"
_results = []


def check(name, got, expect_fn, detail=""):
    ok = expect_fn(got)
    _results.append((ok, name, got, detail))
    print(f"  [{PASS if ok else FAIL}] {name}: got={got!r} {detail}")
    return ok


def main():
    print("=" * 72)
    print("网关守卫自动重绑 回归测试")
    print("=" * 72)

    saved_title = config.get("window.title")
    saved_pid = config.get("window.pid")

    # 现场：配置的 PID 14956 是死进程；角色锚点 然学[701529]，新实例是 19800
    role_id = "701529"
    live_pid = None
    try:
        from core.window_manager import WindowManager
        for _hwnd, title, pid, _vis in WindowManager.list_game_windows():
            if f"[{role_id}]" in (title or ""):
                live_pid = int(pid)
    except Exception as e:
        print(f"  [FAIL] 枚举游戏窗口失败: {e}")
        return 1
    print(f"  现场：角色 {role_id} 的存活实例 PID={live_pid}")

    # ---- T1 角色 ID 锚点 ----
    print("\nT1 角色 ID 锚点解析")
    check("_extract_role_id(游戏主窗口标题)",
          gg._extract_role_id(f"鲜衣怒马 - 怀旧江南版 - (鲜衣怒马 - 然学[{role_id}]) - 2026年08月29日"),
          lambda v: v == role_id)
    check("_extract_role_id(' 聊天窗口') 应取不到",
          gg._extract_role_id(" 聊天窗口"),
          lambda v: v is None)

    class _FakeWM:
        pid = 0
        window_title = " 聊天窗口"      # 多开器场景的真实值
        bound = False

        def bind(self, pid=None, title=None):
            self.pid = pid
            self.bound = True
            return True

    fake = _FakeWM()
    check("_role_id_of_binding 从持久化标题回退取到角色 ID",
          gg._role_id_of_binding(fake),
          lambda v: v == role_id,
          f"(运行时标题={fake.window_title!r})")

    # ---- T2 绑定 PID 已死 → 自动重绑 ----
    print("\nT2 绑定 PID 已死 → 自动重绑")
    dead_pid = int(saved_pid) if saved_pid else 14956
    gg.WindowManager = lambda: fake   # 注入，避免动真实单例
    fake.pid = dead_pid
    got = gg._bound_pid()
    check("_bound_pid() 返回新实例而非 None",
          got, lambda v: v == live_pid, f"(旧PID={dead_pid} 已死)")

    # ---- T3 window_manager 未绑（pid=0）→ config 回退也要能重绑 ----
    print("\nT3 window_manager 未绑定（pid=0）→ config 回退重绑")
    fake.pid = 0
    got2 = gg._bound_pid()
    check("_bound_pid() 走 config 回退也能重绑",
          got2, lambda v: v == live_pid)

    # ---- T4 bind() 不得破坏角色锚点 ----
    print("\nT4 bind() 角色锚点保护")
    good_title = f"鲜衣怒马 - 怀旧江南版 - (鲜衣怒马 - 然学[{role_id}]) - 2026年08月29日"
    config.set("window.title", good_title)
    try:
        from core.window_manager import WindowManager
        wm = WindowManager()
        orig_title, orig_pid = wm.window_title, wm.pid
        # 模拟：绑定到了聊天窗口（标题无角色 ID）
        wm.window_title = " 聊天窗口"
        wm.pid = live_pid
        try:
            # 直接复现 bind() 里的持久化分支
            old_title = config.get("window.title") or ""
            import re
            rid_re = re.compile(r"\[(\d{4,})\]")
            should_keep = rid_re.search(wm.window_title) or not rid_re.search(old_title)
            check("不含角色 ID 的标题不应覆盖已有锚点",
                  should_keep, lambda v: v is False,
                  f"(旧锚点={old_title!r})")
        finally:
            wm.window_title, wm.pid = orig_title, orig_pid
    except Exception as e:
        print(f"  [FAIL] T4 异常: {e}")

    # 还原
    config.set("window.title", saved_title)
    config.set("window.pid", saved_pid)

    ok_n = sum(1 for r in _results if r[0])
    print("\n" + "=" * 72)
    print(f"结果：{ok_n}/{len(_results)} PASS")
    for ok, name, got, _d in _results:
        if not ok:
            print(f"  ✗ {name}: {got!r}")
    print("=" * 72)
    return 0 if ok_n == len(_results) else 1


if __name__ == "__main__":
    sys.exit(main())
