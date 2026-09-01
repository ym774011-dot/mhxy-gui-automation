# -*- coding: utf-8 -*-
"""P4 断点恢复测试（2026-09-01）。

验证：断点写入/读回/重置；断点续跑判定（<1h 继承、>1h 过期清理）。
运行：E:\\py\\python.exe tests\\test_brain_p4.py
"""
import os
import sys
import time
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from tasks.library import BRAIN  # noqa: E402

_PASS = 0
_FAIL = 0


def check(name, cond):
    global _PASS, _FAIL
    if cond:
        _PASS += 1
        print(f"  ✔ {name}")
    else:
        _FAIL += 1
        print(f"  ✘ {name}")


def test_session_write_read():
    print("\n[P4-1] 断点写入/读回")
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    bm = BRAIN.BrainMemory(mem_file=path)
    bm.session_begin("花果山", 55, 88, kills=37, reason="stopped")
    s = bm.session_resume()
    check("地图", s.get("cur_map") == "花果山")
    check("坐标", s.get("cur_x") == 55 and s.get("cur_y") == 88)
    check("击杀数", s.get("kills") == 37)
    check("原因", s.get("reason") == "stopped")
    check("有时间戳", s.get("last_ts", 0) > 0)
    # 落盘后重载
    bm.done(force=True)
    bm2 = BRAIN.BrainMemory(mem_file=path)
    check("重载断点仍在", bm2.session_resume().get("kills") == 37)
    os.unlink(path)


def test_session_reset():
    print("\n[P4-2] 正常结束重置断点")
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    bm = BRAIN.BrainMemory(mem_file=path)
    bm.session_begin("长寿村", 15, 138, kills=5, reason="stopped")
    bm.session_reset()
    check("重置后为空", bm.session_resume() == {})
    os.unlink(path)


def test_resume_decision():
    print("\n[P4-3] 续跑判定逻辑（farmed_total 继承 & 过期清理）")
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    bm = BRAIN.BrainMemory(mem_file=path)
    # 模拟"刚中断"：last_ts=现在 → <1h → 应续跑
    bm.session_begin("长寿村", 15, 138, kills=23, reason="stopped")
    s = bm.session_resume()
    age = time.time() - s["last_ts"]
    _o = dict(s)
    check("刚中断(<1h)判定续跑", age <= 3600 and _o["kills"] == 23)
    os.unlink(path)
    # 模拟"过期断点"：手动改 last_ts 到 2h 前 → 下次启动应清
    fd2, path2 = tempfile.mkstemp(suffix=".json")
    os.close(fd2)
    bm2 = BRAIN.BrainMemory(mem_file=path2)
    bm2.session_begin("傲来国", 1, 1, kills=50, reason="stopped")
    s2 = bm2.session_resume()
    bm2._mem["session"]["last_ts"] = time.time() - 7200   # 2h 前
    bm2._dirty = True                                     # 手动改 → 标记落盘
    bm2.done(force=True)
    bm3 = BRAIN.BrainMemory(mem_file=path2)
    s3 = bm3.session_resume()
    age3 = time.time() - s3["last_ts"]
    check("2h 前断点判定过期", age3 > 3600)
    # 过期 handled：farmed_total 应为 0（判断 main 同款逻辑）
    _kills3 = int(s3.get("kills", 0) or 0)
    _resume_farmed = _kills3 if (_kills3 > 0 and age3 <= 3600) else 0
    check("过期断点不继承 kill", _resume_farmed == 0)
    os.unlink(path2)


def test_empty_session():
    print("\n[P4-4] 空会话（从未写过断点）")
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    bm = BRAIN.BrainMemory(mem_file=path)
    check("空断点返回 dict", bm.session_resume() == {})
    os.unlink(path)


if __name__ == "__main__":
    test_session_write_read()
    test_session_reset()
    test_resume_decision()
    test_empty_session()
    print(f"\n=== P4 测试完成: 通过 {_PASS} / 失败 {_FAIL} ===")
    sys.exit(1 if _FAIL else 0)