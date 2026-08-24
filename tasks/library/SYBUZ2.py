# -*- coding: utf-8 -*-
"""
SYBUZ2 - 站桩瞬移任务函数包（Lua 直接 CALL 版）。

★2026-08-23 23:16 突破：无需点击/协议/模板——直接调用场景 NPC 对象的
  ``事件开始`` 方法即可弹出对话，再调用对话栏 ``事件解析`` 选战斗选项。

完整链路（角色从不走路，画面仅跨图时 0.3s 闪变）：
  1. SYHS jump 到任务地图（跨图必须，NPC 只在当前图加载）
  2. 按名称搜索目标 NPC（默认"江湖大盗"）→ 直接 CALL 事件开始 → 弹对话
     （★同图内任意距离有效，无需走到 NPC 跟前）
  3. 读对话栏选项 → 找战斗类选项（抓捕/战斗/击杀/挑战/查明等关键词）
     → CALL 对话栏:事件解析(跳转链接) → 进战斗
  4. 轮询 tp.战斗中 等战斗结束
  5. SYHS jump 回站桩点 (240,101)

参数:
  target_coord: (gx, gy) 或 JHRW dict（自动取 target_coord/target_location）
  target_location: 目标地图名（跨图判断）
  npc_name: 目标 NPC 名称（默认"江湖大盗"）
  home_coord: 站桩点（默认 240,101 长安）
  battle_timeout: 战斗等待超时
  gateway: 网关地址
"""
import json
import time
from typing import Optional, Tuple, Union, List
from utils.logger import logger

try:
    from config.config import config
except Exception:
    config = None

DEFAULT_GATEWAY = "http://127.0.0.1:18082"


def _http_json(gateway: str, path: str, data=None, timeout: float = 8.0):
    """POST/GET JSON 到网关."""
    import urllib.request
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(
        gateway.rstrip("/") + path,
        data=body,
        headers={"Content-Type": "application/json"} if body else {},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def _gw_retry(gateway: str, path: str, data=None, timeout: float = 8.0):
    """调网关并自愈重试一次：连接失败（10061）或 ok=false
    （script has been destroyed 等，frida 会话随游戏重启失效）都触发
    ensure_gateway 后重试（2026-08-24）。"""
    try:
        r = _http_json(gateway, path, data, timeout)
    except Exception:
        r = None
    if r is None or not r.get("ok"):
        try:
            from core.gateway_guard import ensure_gateway
            ensure_gateway(verbose=False)
        except Exception:
            pass
        r = _http_json(gateway, path, data, timeout)
    return r


def _lua(gateway: str, code: str) -> str:
    """执行 Lua 代码（通过网关 /api/lua），返回 __out 值。"""
    r = _gw_retry(gateway, "/api/lua", {"code": code})
    if not r.get("ok"):
        raise RuntimeError(f"Lua 执行失败: {r.get('error', r)}")
    return r.get("result", {}).get("value") or ""


def _lua_expr(gateway: str, expr: str) -> str:
    r = _gw_retry(gateway, "/api/lua/expr", {"expr": expr})
    if not r.get("ok"):
        raise RuntimeError(f"expr 失败: {r.get('error', r)}")
    return r.get("result", {}).get("value") or ""


def find_npc_by_name(gateway: str, npc_name: str) -> Optional[dict]:
    """在 tp.场景.场景人物 按名称搜索 NPC，返回 {id, 格子x, 格子y, 名称} 或 None."""
    code = f"""
local out = {{}}
for id,u in pairs(tp.场景.场景人物 or {{}}) do
  if type(u)=="table" and tostring(u.名称 or "")=="{npc_name}" then
    out[#out+1] = string.format("%s|%s|%s", id, tostring(u.格子x or ""), tostring(u.格子y or ""))
  end
end
_G.__out = table.concat(out, ";")"""
    try:
        raw = _lua(gateway, code)
    except Exception:
        return None
    if not raw:
        return None
    for entry in raw.split(";"):
        if "|" in entry:
            parts = entry.split("|")
            if len(parts) >= 2:
                return {"id": parts[0], "x": parts[1], "y": parts[2] if len(parts) > 2 else ""}
    return None


def call_npc_event_start(gateway: str, npc_name: str, target_coord=None, target_location=None,
                         verbose: bool = False) -> Tuple[bool, str]:
    """按名称搜 NPC → （若需要）微调瞬移到 NPC 实际格子 → CALL 事件开始() 弹对话.

    ★2026-08-24 修复「距离太远」：事件开始() 内部有客户端距离校验，
      角色坐标必须与 NPC 格子一致。任务追踪栏坐标(如 162,124)是任务目标点，
      NPC 实际刷新在附近格子 → 直接用任务坐标 CALL 会弹"您距离这个npc太远了"。
      故先 find_npc_by_name 拿 NPC 格子，若与当前坐标不一致 → SYHS 同图微调瞬移，
      确保角色坐标 = NPC 格子后再 CALL。

    :return: (ok, 详情)
    """
    info = find_npc_by_name(gateway, npc_name)
    if not info:
        return False, f"未找到 NPC '{npc_name}'（可能未刷新/不在此图）"

    # ---- 微调瞬移到 NPC 实际格子（消除"距离太远"）----
    try:
        nx, ny = int(info["x"]), int(info["y"])
        if (target_coord is None or (nx, ny) != tuple(int(v) for v in target_coord)) and nx >= 0 and ny >= 0:
            from tasks.library.SYHS import SYHS
            rs = SYHS((nx, ny), target_location=target_location, gateway=gateway,
                      verbose=verbose, wait_stable=True, stable_timeout=20, stable_min_settle=2.0)
            if rs.get("ok"):
                if verbose:
                    logger.info(f"SYBUZ2: 微调瞬移到 NPC 格子 ({nx},{ny}) 消除距离校验")
            else:
                if verbose:
                    logger.warning(f"SYBUZ2: 微调瞬移失败 ({nx},{ny}): {rs.get('message')}，继续尝试 CALL")
    except (ValueError, TypeError):
        pass

    code = f"""
local v = nil
for id,u in pairs(tp.场景.场景人物 or {{}}) do
  if type(u)=="table" and tostring(u.名称 or "")=="{npc_name}" then v = u break end
end
if not v then _G.__out = "NOTFOUND"; return end
local mt = getmetatable(v)
local ok, ret = pcall(mt.__index.事件开始, v)
_G.__out = tostring(ok) .. "|" .. tostring(v.名称)"""
    try:
        raw = _lua(gateway, code)
    except Exception as e:
        return False, f"CALL 异常: {e}"
    if not raw or raw == "NOTFOUND":
        return False, f"NPC '{npc_name}' 消失（战斗后刷新或任务未到阶段）"
    parts = raw.split("|")
    ok = parts[0] == "true"
    return ok, f"NPC={parts[1] if len(parts) > 1 else npc_name} CALL事件开始 ok={ok}"


def get_dialog_options(gateway: str) -> List[str]:
    """读对话栏选项文本列表."""
    code = """local out={}
local t = tp.窗口.对话栏.选项 or {}
for k,v in pairs(t) do
  if type(v)=="table" then out[#out+1] = tostring(v.基本内容 or "") end
end
_G.__out = table.concat(out, "|")"""
    try:
        raw = _lua(gateway, code)
    except Exception:
        return []
    return [s for s in raw.split("|") if s]


def call_dialog_option(gateway: str, keyword: str = "抓捕") -> Tuple[bool, str]:
    """找含关键词的对话选项并 CALL 事件解析(跳转链接) → 执行. 返回 (ok, 详情).

    ★2026-08-24 修复: 关键词同时匹配「基本内容」(显示文本) 与「跳转链接」；
      找不到时返回 NOOPTION 让上层循环试其他关键词——
      **绝不兜底选第一个选项**（会选到"告诉我要怎么做吧！"这类对话指引，
      事件解析 ok 但没进战斗 → wait_battle_done 空转 180s 超时）。
    """
    code = f"""
local t = tp.窗口.对话栏.选项 or {{}}
local target = nil
local label = nil
for k,v in pairs(t) do
  if type(v)=="table" and v.跳转链接 then
    local text = tostring(v.基本内容 or "") .. "|" .. tostring(v.跳转链接 or "")
    if text:find("{keyword}") then target = v.跳转链接; label = tostring(v.基本内容 or v.跳转链接); break end
  end
end
if not target then _G.__out = "NOOPTION"; return end
local ok, ret = pcall(function() return tp.窗口.对话栏:事件解析(target) end)
_G.__out = tostring(ok) .. "|" .. tostring(label)"""
    try:
        raw = _lua(gateway, code)
    except Exception as e:
        return False, f"选项CALL异常: {e}"
    if not raw or raw == "NOOPTION":
        return False, f"对话栏无含'{keyword}'的选项（可手工选或换关键词）"
    parts = raw.split("|")
    ok = parts[0] == "true"
    return ok, f"选项[{parts[1] if len(parts) > 1 else ''}] 事件解析 ok={ok}"


def wait_battle_done(gateway: str, timeout: float = 120.0, verbose: bool = False) -> Tuple[bool, str]:
    """等战斗结束：tp.战斗中 true→false.

    ★2026-08-24 防卡防护：若 15s 内从未检测到 战斗中=true，说明选项解析成功
      但实际没进战斗（非战斗选项），提前放弃，不空转满 timeout。
    """
    t0 = time.time()
    saw_true = False
    battle = "?"
    while time.time() - t0 < timeout:
        try:
            battle = _lua_expr(gateway, "tostring(tp.战斗中)")
        except Exception:
            battle = "?"
        if battle == "true":
            saw_true = True
        elif saw_true and battle == "false":
            return True, "战斗结束"
        # 15s 从未进战斗 → 快速放弃
        if not saw_true and time.time() - t0 > 15.0:
            return False, f"15s 内未进入战斗(战斗中={battle})，判定未开战"
        time.sleep(1.0)
    return saw_true, f"超时({int(timeout)}s) 战斗中最终={battle}"


def SYBUZ2(
    target_coord: Union[Tuple[int, int], dict, str, None] = None,
    target_location: Optional[str] = None,
    npc_name: str = "江湖大盗",
    home_coord: Tuple[int, int] = (240, 101),
    battle_timeout: float = 180.0,
    gateway: str = DEFAULT_GATEWAY,
    verbose: bool = False,
    x: Union[int, str, None] = None,
    y: Union[int, str, None] = None,
):
    """
    站桩瞬移任务完整流程（Lua 直接 CALL 版，2026-08-23 突破）。

    :param target_coord: (gx, gy) 地图坐标 / JHRW dict / 地图名(字符串)
    :param target_location: 目标地图名（跨图判断，如 "江南野外"）
    :param npc_name: 目标 NPC 名称（默认"江湖大盗"）
    :param home_coord: 站桩点（默认 240,101 长安）
    :param battle_timeout: 战斗等待超时秒数
    :param gateway: 网关地址
    :param x/y: 独立坐标分量（GUI 事件拆传兼容）
    :return: dict {ok, message, steps, target_coord, target_location, elapsed_ms}
    """
    t0 = time.time()
    steps = {}

    # ---- 参数解析（与 SYHS 同款兼容）----
    if isinstance(target_coord, str) and not target_location:
        target_location = target_coord
        target_coord = None
    if target_coord is None and x is not None and y is not None:
        try:
            target_coord = (int(x), int(y))
        except (TypeError, ValueError):
            target_coord = None
    if isinstance(target_coord, dict):
        if not target_location:
            target_location = target_coord.get("target_location")
        tc = target_coord.get("target_coord") or target_coord.get("internal_coord")
        if isinstance(tc, (list, tuple)) and len(tc) >= 2:
            gx, gy = int(tc[0]), int(tc[1])
        else:
            return {"ok": False, "message": "target_coord dict 缺少坐标字段", "steps": steps,
                    "elapsed_ms": round((time.time() - t0) * 1000, 1)}
    elif isinstance(target_coord, (list, tuple)) and len(target_coord) >= 2:
        gx, gy = int(target_coord[0]), int(target_coord[1])
    else:
        return {"ok": False, "message": "缺少 target_coord", "steps": steps,
                "elapsed_ms": round((time.time() - t0) * 1000, 1)}

    # ---- 1) 瞬移任务点（跨图 0.3s 闪变）----
    try:
        from tasks.library.SYHS import SYHS
        r = SYHS((gx, gy), target_location=target_location, gateway=gateway,
                 verbose=verbose, wait_stable=True, stable_timeout=20, stable_min_settle=2.0)
        steps["teleport_to_target"] = {
            "ok": r.get("ok"), "coord": (gx, gy),
            "map_switch": (r.get("map_switch") or {}).get("mode"),
            "server_sync": r.get("server_sync"),
        }
        if not r.get("ok"):
            return {"ok": False, "message": f"瞬移到任务点失败: {r.get('message')}",
                    "steps": steps, "elapsed_ms": round((time.time() - t0) * 1000, 1)}
    except Exception as e:
        return {"ok": False, "message": f"SYHS 调用异常: {e}", "steps": steps,
                "elapsed_ms": round((time.time() - t0) * 1000, 1)}

    # ---- 2) 按名称搜 NPC → 微调瞬移到 NPC 格子 → CALL 事件开始（★核心突破）----
    npc_ok, npc_info = call_npc_event_start(gateway, npc_name, target_coord=(gx, gy),
                                            target_location=target_location, verbose=verbose)
    steps["call_npc"] = {"ok": npc_ok, "info": npc_info}
    if not npc_ok:
        # NPC 未找到：等 1.5s 重试（任务 NPC 可能延迟刷新）
        time.sleep(1.5)
        npc_ok, npc_info = call_npc_event_start(gateway, npc_name, target_coord=(gx, gy),
                                                target_location=target_location, verbose=verbose)
        steps["call_npc_retry"] = {"ok": npc_ok, "info": npc_info}
    if not npc_ok:
        steps["battle"] = {"ok": False, "info": f"NPC '{npc_name}' 未找到"}
        steps["return_home"] = _return_home(gateway, home_coord, verbose)
        return {"ok": False, "message": f"NPC '{npc_name}' 未找到（任务阶段不对或需刷新）",
                "steps": steps, "target_coord": (gx, gy), "target_location": target_location,
                "elapsed_ms": round((time.time() - t0) * 1000, 1)}

    # ---- 3) 读选项 → CALL 事件解析 选战斗 ----
    time.sleep(0.6)  # 等对话栏刷新
    opt_ok, opt_info = call_dialog_option(gateway, keyword="抓捕")
    steps["dialog_option"] = {"ok": opt_ok, "info": opt_info}
    if not opt_ok:
        # 尝试其他关键词
        for kw in ("战斗", "击杀", "挑战", "查明", "对付", "教训"):
            opt_ok, opt_info = call_dialog_option(gateway, keyword=kw)
            steps["dialog_option_" + kw] = {"ok": opt_ok, "info": opt_info}
            if opt_ok:
                break

    # ---- 4) 等战斗结束 ----
    if opt_ok:
        battle_ok, battle_info = wait_battle_done(gateway, battle_timeout, verbose=verbose)
        steps["battle"] = {"ok": battle_ok, "info": battle_info}
        # ★战斗结束后延迟 1 秒右键点击一次（2026-08-23 用户要求，关闭战斗结算界面）
        if battle_ok:
            time.sleep(1.0)
            try:
                from core.input_controller import input_controller
                input_controller.right_click(500, 310, click_delay=200)
                steps["post_battle_right_click"] = {"ok": True, "info": "战斗结束1s后右键(500,310)"}
                if verbose:
                    logger.info("SYBUZ2: 战斗结束 1s 后右键点击 (500,310)")
            except Exception as e:
                steps["post_battle_right_click"] = {"ok": False, "info": str(e)}
    else:
        steps["battle"] = {"ok": False, "info": "未进战斗(选项未匹配)"}

    # ---- 5) 瞬移回站桩点 ----
    back = _return_home(gateway, home_coord, verbose)
    steps["return_home"] = back

    ok = bool(npc_ok and opt_ok and battle_ok if steps["battle"]["ok"] is not False else npc_ok)
    return {
        "ok": ok,
        "target_coord": (gx, gy),
        "target_location": target_location,
        "steps": steps,
        "message": (
            f"站桩瞬移任务完成（CALL {npc_name}）" if ok else
            f"部分失败: NPC={npc_ok} 对话选项={opt_ok} 战斗={steps['battle']['ok']}"
        ),
        "elapsed_ms": round((time.time() - t0) * 1000, 1),
    }


def _return_home(gateway: str, home_coord: Tuple[int, int], verbose: bool = False) -> dict:
    try:
        from tasks.library.SYHS import SYHS
        rb = SYHS(home_coord, target_location="长安", gateway=gateway,
                  verbose=verbose, wait_stable=True, stable_timeout=20, stable_min_settle=2.0)
        return {"ok": rb.get("ok"), "message": rb.get("message")}
    except Exception as e:
        return {"ok": False, "message": str(e)}
