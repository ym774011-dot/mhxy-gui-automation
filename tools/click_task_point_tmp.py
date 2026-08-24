# -*- coding: utf-8 -*-
"""快速测试: 点击任务点 (24,54) 屏幕位置触发战斗。"""
import json
import sys
import time
import urllib.request

PROJECT = r"E:\DS\mhxy-gui-automation"
for p in (PROJECT, PROJECT + r"\core"):
    if p not in sys.path:
        sys.path.insert(0, p)


def lua(code, timeout=6):
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:18082/api/lua",
            data=json.dumps({"code": code}).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        d = json.loads(urllib.request.urlopen(req, timeout=timeout).read())
        return d.get("result", {}).get("value") if d.get("ok") else None
    except Exception:
        return None


def main():
    from core.window_manager import window_manager
    from core.input_controller import input_controller
    window_manager.bind(pid=13616)

    # 任务点(24,54) → 内部(480,1080) → 屏幕坐标
    code = (
        'local f = _G["取画面坐标"] '
        'local ok, r = pcall(f, 480, 1080, 1000, 620, 0) '
        'if ok and type(r)=="table" then '
        '_G.__out = tostring(r.x + 500) .. "," .. tostring(r.y + 310) '
        'else _G.__out = "fail" end'
    )
    text = lua(code)
    print("任务点(24,54)屏幕坐标:", text)
    if text and "," in text:
        px, py = int(float(text.split(",")[0])), int(float(text.split(",")[1]))
        print(f"点击 ({px},{py})")
        input_controller.click(px, py, click_delay=0.3)
        time.sleep(2)
        input_controller.click(px, py - 4, click_delay=0.3)
        print("已点击")
    time.sleep(5)
    # 验证
    st = lua('_G.__out = "战斗中=" .. tostring(tp.战斗中) .. "|地图=" .. tostring(tp.当前地图)')
    print("验证:", st)


if __name__ == "__main__":
    main()
