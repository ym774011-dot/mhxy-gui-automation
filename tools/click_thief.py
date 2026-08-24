# -*- coding: utf-8 -*-
"""
click_thief.py — 瞬移 → 等画面定格 → 找江湖大盗 → 点击（触发战斗）

★ 关键时序（用户指正）:
  瞬移后画面有加载延迟，必须等画面定格(单位渲染完成)再点击。
  判定"渲染完成" = 场景人物 x/y > 0（加载=false→true）

用法: python tools/click_thief.py [目标格子x] [目标格子y] [最大等待秒]
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
UNIT_NAME = "江湖大盗"


def lua(code, timeout=8):
    try:
        req = urllib.request.Request(
            GATEWAY + "/api/lua",
            data=json.dumps({"code": code}).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        d = json.loads(urllib.request.urlopen(req, timeout=timeout).read())
        return d.get("result", {}).get("value") if d.get("ok") else None
    except Exception:
        return None


def teleport(x, y):
    """瞬移到地图坐标(格子)，自动×20 内部换算 + 1002 同步。"""
    req = urllib.request.Request(
        GATEWAY + "/api/act/teleport",
        data=json.dumps({"x": x, "y": y}).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    d = json.loads(urllib.request.urlopen(req, timeout=10).read())
    return d.get("ok", False), d.get("result", {})


def find_unit_rendered(name, need_xy=True):
    """找目标单位。优先 x/y 有效；否则用格子坐标(格子×20≈世界坐标)。

    实测: 任务怪(江湖大盗)的 x/y 常为 0（暗雷单位不填充世界坐标），
    但格子坐标始终有效。此时世界坐标 = 格子×20（地图内近似）。
    """
    code = (
        'local out = "" '
        'local t = tp.场景.场景人物 '
        'for k, v in pairs(t) do '
        '  if type(v)=="table" and v.名称 and v.名称=="%s" then '
        '    local ux, uy = v.x or 0, v.y or 0 '
        '    if ux <= 0 and v.格子x then ux, uy = tonumber(v.格子x)*20, tonumber(v.格子y)*20 end '
        '    out = out .. tostring(k) .. "," .. tostring(ux) .. "," .. tostring(uy) '
        '          .. "," .. tostring(v.格子x) .. "," .. tostring(v.格子y) .. "|" '
        '  end '
        'end '
        '_G.__out = out'
    ) % UNIT_NAME
    text = lua(code)
    if not text:
        return None
    for seg in text.split("|"):
        p = seg.split(",")
        if len(p) >= 4:
            try:
                return (int(p[0]), float(p[1]), float(p[2]), p[3], p[4])
            except ValueError:
                continue
    return None


def to_screen(x, y):
    """取画面坐标(世界坐标→屏幕)。★实测该函数不响应,改用角色偏移近似。"""
    code = (
        'local f = _G["取画面坐标"] '
        'local ok, r = pcall(f, %f, %f, 1000, 620, 0) '
        'if ok and type(r)=="table" then '
        '_G.__out = tostring(r.x + 500) .. "," .. tostring(r.y + 310) '
        'else _G.__out = "fail" end'
    ) % (x, y)
    text = lua(code)
    if not text or text == "fail":
        return None
    try:
        px, py = text.split(",")
        return (float(px), float(py))
    except (ValueError, TypeError):
        return None


def wait_scene_stable(target_x, target_y, max_wait=8):
    """等画面定格：轮询角色是否到达目标格 + 目标单位是否渲染。"""
    t0 = time.time()
    while time.time() - t0 < max_wait:
        # 1) 角色到达目标格（内部坐标≈目标×20 ± 公差）
        pos = lua('_G.__out = tostring(tp.角色坐标.x) .. "," .. tostring(tp.角色坐标.y)')
        if pos and "," in pos:
            px, py = (float(v) for v in pos.split(","))
            target_internal_x, target_internal_y = target_x * 20, target_y * 20
            # 允许 ±200 内部单位(约10格)公差
            if abs(px - target_internal_x) < 200 and abs(py - target_internal_y) < 200:
                # 2) 目标单位在场景表（格子坐标有效即视为可定位）
                unit = find_unit_rendered(UNIT_NAME)
                if unit:
                    return unit, (px, py)
        time.sleep(0.5)
    # 超时: 返回最后的角色位置 + 单位(可能未渲染)
    unit = find_unit_rendered(UNIT_NAME)
    pos = lua('_G.__out = tostring(tp.角色坐标.x) .. "," .. tostring(tp.角色坐标.y)')
    if pos and "," in pos:
        pxy = tuple(float(v) for v in pos.split(","))
    else:
        pxy = (0.0, 0.0)
    return unit, pxy


def main():
    tx = int(sys.argv[1]) if len(sys.argv) > 1 else 27   # 大盗格子X
    ty = int(sys.argv[2]) if len(sys.argv) > 2 else 94   # 大盗格子Y
    max_wait = int(sys.argv[3]) if len(sys.argv) > 3 else 10

    from core.window_manager import window_manager
    from core.input_controller import input_controller
    window_manager.bind(pid=13616)

    print(f"[1] 瞬移到 ({tx},{ty}) ...")
    ok, res = teleport(tx, ty)
    if not ok:
        print(f"❌ 瞬移失败: {res}")
        return 1
    print(f"    内部({res.get('internal_coord')}) 同步={res.get('server_sync')}")

    print(f"[2] 等画面定格 (最多{max_wait}s) ...")
    unit, pos = wait_scene_stable(tx, ty, max_wait)
    print(f"    角色位置: ({pos[0]:.0f},{pos[1]:.0f})")

    if not unit:
        print(f"❌ {max_wait}s 内未等到 {UNIT_NAME} 渲染完成")
        print("    可能: 怪物不在该格 / 被遮挡 / 任务已更新")
        return 2

    idx, wx, wy, gx, gy = unit
    print(f"[3] 找到 {UNIT_NAME}: 索引{idx} 世界({wx:.1f},{wy:.1f}) 格子({gx},{gy})")

    screen = to_screen(wx, wy)
    if screen and 0 < screen[0] < 1000 and 0 < screen[1] < 620:
        px, py = int(screen[0]), int(screen[1])
        print(f"[4] 屏幕坐标 ({px},{py}) 点击...")
        input_controller.click(px, py, click_delay=0.3)
        time.sleep(2)
        input_controller.click(px, py - 4, click_delay=0.3)
        print("    已点击（双击）")
    else:
        print(f"[4] 换算异常 {screen}，改用角色位置点击")
        px, py = int(pos[0]), int(pos[1])
        input_controller.click(px, py, click_delay=0.3)

    time.sleep(6)
    st = lua('_G.__out = "战斗中=" .. tostring(tp.战斗中) .. "|地图=" .. tostring(tp.当前地图)')
    print(f"[5] 最终状态: {st}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
