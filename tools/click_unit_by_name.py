# -*- coding: utf-8 -*-
"""
click_unit_by_name.py — 点击指定名称的场景单位（江湖大盗等）

流程: 网关读场景人物表 → 名称匹配 → x/y → 取画面坐标换算屏幕像素 → 后台点击
用法: python tools/click_unit_by_name.py 江湖大盗
"""
import json
import sys
import time
import urllib.request

PROJECT = r"E:\DS\mhxy-gui-automation"
for p in (PROJECT, PROJECT + r"\core"):
    if p not in sys.path:
        sys.path.insert(0, p)

GATEWAY = "http://127.0.0.1:18082"


def lua(code, timeout=8):
    req = urllib.request.Request(
        GATEWAY + "/api/lua",
        data=json.dumps({"code": code}).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    d = json.loads(urllib.request.urlopen(req, timeout=timeout).read())
    return d.get("result", {}).get("value") if d.get("ok") else None


def find_unit(name):
    """读场景人物表，返回匹配单位的 (x, y, 格子x, 格子y)。"""
    code = (
        'local out = "" '
        'local t = tp.场景.场景人物 '
        'for k, v in pairs(t) do '
        '  if type(v)=="table" and v.名称 and v.名称=="%s" then '
        '    out = out .. tostring(v.x) .. "," .. tostring(v.y) '
        '          .. "," .. tostring(v.格子x) .. "," .. tostring(v.格子y) .. "|" '
        '  end '
        'end '
        '_G.__out = out'
    ) % name
    text = lua(code)
    if not text:
        return []
    units = []
    for seg in text.split("|"):
        parts = seg.split(",")
        if len(parts) == 4:
            try:
                units.append((float(parts[0]), float(parts[1]), parts[2], parts[3]))
            except ValueError:
                pass
    return units


def to_screen(x, y, win_w=1000, win_h=620):
    """取画面坐标换算内部坐标 → 屏幕像素。

    ★ 2026-08-20 实测: 取画面坐标(x,y,w,h) 返回相对窗口中心的偏移，
      屏幕坐标 = 偏移 + (w/2, h/2)。窗口客户区 1000x620。
    """
    code = (
        'local f = _G["取画面坐标"] '
        'if f then local ok, r = pcall(f, %f, %f, %d, %d, 0) '
        'if ok and type(r)=="table" then '
        '_G.__out = tostring(r.x + %d) .. "," .. tostring(r.y + %d) '
        'else _G.__out = "" end else _G.__out = "" end'
    ) % (x, y, win_w, win_h, win_w // 2, win_h // 2)
    text = lua(code)
    if not text:
        return None
    try:
        px, py = text.split(",")
        return (float(px), float(py))
    except (ValueError, TypeError):
        return None


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "江湖大盗"
    retry = int(sys.argv[2]) if len(sys.argv) > 2 else 5

    # 绑定窗口（读配置 PID 或手动指定）
    import json as _json
    try:
        cfg = _json.load(open(PROJECT + r"\config\settings.json", encoding="utf-8"))
        cfg_pid = cfg.get("window", {}).get("pid") or 0
    except Exception:
        cfg_pid = 0
    from core.window_manager import window_manager
    from core.input_controller import input_controller
    if len(sys.argv) > 2 and sys.argv[2].isdigit():
        # 用法: python tools/click_unit_by_name.py 江湖大盗 13616 [重试次数]
        pid = int(sys.argv[2])
        retry = int(sys.argv[3]) if len(sys.argv) > 3 else 5
    else:
        pid = cfg_pid
        retry = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    ok = window_manager.bind(pid=pid) if pid else False
    if not ok:
        print(f"⚠️ 窗口绑定失败 (pid={pid})，仅读单位不点击")
        input_controller_ready = False
    else:
        input_controller_ready = True

    print(f"寻找单位: {name}（重试 {retry} 次）")
    for i in range(1, retry + 1):
        units = find_unit(name)
        if units:
            x, y, gx, gy = units[0]
            if x == 0 and y == 0:
                # x/y 未加载时用格子坐标 ×20 估算内部坐标
                try:
                    x, y = float(gx) * 20, float(gy) * 20
                except (TypeError, ValueError):
                    pass
            screen = to_screen(x, y)
            if screen and 0 < screen[0] < 1000 and 0 < screen[1] < 620:
                px, py = int(screen[0]) - 2, int(screen[1]) - 2
                print(f"  命中 [{name}] 内部({x:.1f},{y:.1f}) 格子({gx},{gy}) → 屏幕({px},{py})")
                if input_controller_ready:
                    input_controller.click(px, py, click_delay=0.1)
                    print(f"  ✅ 已点击 (第{i}次)")
                    return 0
                print(f"  ⚠️ 窗口未绑定，跳过点击（坐标 {px},{py}）")
                return 2
            else:
                print(f"  第{i}次: 找到但屏幕坐标异常 {screen}，重试…")
        else:
            print(f"  第{i}次: 未找到 {name}（单位动态刷新），重试…")
        time.sleep(1.5)

    print(f"❌ {retry} 次未找到可点击的 {name}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
