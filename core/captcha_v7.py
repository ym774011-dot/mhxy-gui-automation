# -*- coding: utf-8 -*-
"""captcha_v7.py — 验证码 V7 直解模块（2026-08-25）

替换旧"等 captcha_monitor 被动解"的机制：任务引擎弹窗时**主动 Lua 直解**。

原理（铁证 13:53 实战）：
  tp.窗口.防脚本.验证码             = 答案（100%）
  tp.窗口.防脚本.验证按钮.按钮       = {x,y,宽度=140,高度=22} = 答案按钮渲染区
  → PostMessage 点击按钮中心 → 2.5s 内验证通过（零 OCR 零匹配）

网关端口按组解析（group_config.gateway_port，与 gateway_guard 一致）。
"""
import json
import os
import time
import urllib.request

_GATEWAY_PORT = None


def _gw_url() -> str:
    """按组解析网关端口（组1=18083？组2=18082 —— 以 group_config 为准）。"""
    global _GATEWAY_PORT
    if _GATEWAY_PORT is None:
        try:
            from core.group_config import gateway_port
            _GATEWAY_PORT = gateway_port()
        except Exception:
            _GATEWAY_PORT = 18082
    return f"http://127.0.0.1:{_GATEWAY_PORT}"


def _lua(code: str, timeout: float = 4.0, gateway: str = None):
    try:
        url = gateway if gateway else _gw_url()
        req = urllib.request.Request(
            url.rstrip("/") + "/api/lua",
            data=json.dumps({"code": code}).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except Exception:
        return {"ok": False, "error": "gw_unreachable"}


def lua_answer(gateway: str = None) -> str:
    """读验证码答案（100% 准确）。非弹窗/失败返回 None。"""
    r = _lua('_G.__out = tostring(tp.窗口.防脚本.验证码 or "")', gateway=gateway)
    if not r.get("ok"):
        return None
    v = (r.get("result") or {}).get("value") or ""
    if isinstance(v, str) and len(v) >= 4 and v.replace(" ", "").isalnum() \
            and not v.replace(" ", "").isdigit():
        return v
    return None


def lua_answer_button_xy(gateway: str = None):
    """读答案按钮渲染区 {x,y,w,h} → 返回中心 (cx, cy)。失败返回 None。"""
    code = ('_G.__out=""; '
            'local b = tp.窗口.防脚本.验证按钮 and tp.窗口.防脚本.验证按钮.按钮; '
            'if b and b.x and b.y and b.宽度 and b.高度 then '
            '_G.__out = tostring(b.x)..","..tostring(b.y)..","..tostring(b.宽度)..","..tostring(b.高度) '
            'end')
    r = _lua(code, gateway=gateway)
    if not r.get("ok"):
        return None
    v = (r.get("result") or {}).get("value") or ""
    if not v or "," not in v:
        return None
    parts = v.split(",")
    if len(parts) != 4:
        return None
    try:
        x, y, w, h = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
        return (x + w // 2, y + h // 2)
    except ValueError:
        return None


def _click_client(hwnd, cx, cy):
    """后台点击（PostMessage 左键按下+抬起）。hwnd 无效/失败返回 False。"""
    import win32con
    import win32gui
    try:
        if not hwnd:
            return False
        lparam = (cy << 16) | (cx & 0xFFFF)
        r1 = win32gui.PostMessage(hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lparam)
        r2 = win32gui.PostMessage(hwnd, win32con.WM_LBUTTONUP, 0, lparam)
        return bool(r1 and r2)
    except Exception:
        return False


def _lua_visible(gateway: str = None) -> bool:
    """弹窗是否显示中（Lua 可视字段，防误点残留）。"""
    r = _lua('_G.__out = tostring(tp.窗口.防脚本.可视)', gateway=gateway)
    if not r.get("ok"):
        return False
    return str((r.get("result") or {}).get("value") or "").strip().lower() == "true"


def solve_v7(hwnd, verify_wait: float = 2.5, gateway: str = None) -> tuple:
    """V7 直解：Lua 读答案+按钮坐标 → 点击 → 返回 (ok, detail)。

    :param hwnd: 游戏窗口句柄（后台点击目标）
    :param gateway: 网关 URL（缺省按组解析；MPCG 等可显式传 http://127.0.0.1:18083）
    :return: (True, {"answer":..., "xy":...}) 或 (False, {"reason":...})
    """
    # 弹窗判断：可视=true 才是真弹窗（残留时可视=false，防止误点残留按钮）
    if not _lua_visible(gateway):
        return False, {"reason": "no_captcha"}
    answer = lua_answer(gateway)
    if not answer:
        return False, {"reason": "lua_answer_unavailable"}
    xy = lua_answer_button_xy(gateway)
    if not xy:
        return False, {"reason": "lua_button_xy_unavailable", "answer": answer}
    ok = _click_client(hwnd, xy[0], xy[1])
    if ok and verify_wait > 0:
        time.sleep(verify_wait)
    return ok, {"answer": answer, "xy": xy, "clicked": ok}
