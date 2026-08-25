# -*- coding: utf-8 -*-
"""
DSHNPC - 杜少海 NPC 处理（2026-08-25）

替代任务序列 [YOLO 点杜少海 + 获取任务 + 关闭对话框] 三个事件：
1. 按名称找杜少海（tp.场景.场景人物，id 精确索引）
2. CALL 事件开始 弹对话
3. 弹窗检测：CALL 后对话栏出现（记录文本/选项非空）
   → 有弹窗：右键 (550,85) 关闭
   → 无弹窗：不右键（不打扰）

纯 Lua 数据链路（不依赖截屏/窗口可见性），后台挂机可用。
"""

import time
from typing import Optional, Tuple, Union, List

try:
    from utils.logger import logger
except Exception:
    import logging
    logger = logging.getLogger("DSHNPC")

try:
    from core.group_config import gateway_url
    DEFAULT_GATEWAY = gateway_url()  # 多组：组1=18082，组2=18083...
except Exception:
    DEFAULT_GATEWAY = "http://127.0.0.1:18082"

# 弹窗关闭的右键位置（与任务序列"关闭对话框"事件一致，窗口像素坐标）
CLOSE_DIALOG_POS = (550, 85)

# NPC 默认名称（可被 DSHNPC(npc_name=...) 覆盖）
DEFAULT_NPC_NAME = "杜少海"


def _http_json(gateway: str, path: str, data=None, timeout: float = 8.0):
    import json
    import urllib.request
    body = json.dumps(data or {}).encode("utf-8")
    req = urllib.request.Request(
        gateway + path, data=body,
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def _gw_retry(gateway: str, path: str, data=None, timeout: float = 8.0):
    """调网关并自愈重试一次（连接失败/script destroyed → ensure_gateway 后重试）。"""
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


def find_npcs_by_name(gateway: str, npc_name: str) -> List[dict]:
    """按名称找全部同名 NPC 候选（[{id,x,y},...]）。
    场景人物 key 为数字 id，保留供 CALL 精确索引。"""
    code = f"""
local out = {{}}
for id,u in pairs(tp.场景.场景人物 or {{}}) do
  if type(u)=="table" and tostring(u.名称 or "")=="{npc_name}" then
    out[#out+1] = string.format("%s|%s|%s", tostring(id), tostring(u.格子x or ""), tostring(u.格子y or ""))
  end
end
_G.__out = table.concat(out, ";")"""
    try:
        raw = _lua(gateway, code)
    except Exception:
        return []
    cands = []
    for entry in (raw or "").split(";"):
        if "|" in entry:
            parts = entry.split("|")
            if len(parts) >= 3:
                cands.append({"id": parts[0], "x": parts[1], "y": parts[2]})
    return cands


def _check_dialog(gateway: str) -> dict:
    """检测对话栏是否弹窗：返回 {'open': bool, 'text_len': n, 'option_len': n}。"""
    code = """local t = tp.窗口.对话栏
if not t then _G.__out = "none|0|0"; return end
local tl, ol = 0, 0
local rt = t.记录文本 or {}
for k,v in pairs(rt) do
  if type(v)=="table" then for kk,vv in pairs(v) do if type(vv)=="string" and #vv>0 then tl = tl + 1 end end
  elseif type(v)=="string" and #v>0 then tl = tl + 1 end
end
local o = t.选项 or {}
for k,v in pairs(o) do if type(v)=="table" then ol = ol + 1 end end
_G.__out = "open|" .. tl .. "|" .. ol"""
    try:
        raw = _lua(gateway, code)
    except Exception:
        return {"open": False, "text_len": 0, "option_len": 0}
    parts = (raw or "none|0|0").split("|")
    return {
        "open": parts[0] == "open" and (int(parts[1]) > 0 or int(parts[2]) > 0),
        "text_len": int(parts[1]) if len(parts) > 1 else 0,
        "option_len": int(parts[2]) if len(parts) > 2 else 0,
    }


def _find_accept_option(gateway: str) -> dict:
    """读对话栏选项，找含"接任务"关键词的选项坐标。

    选项对象结构：{基本内容, 跳转链接, 选中判断={x,y,w,h}}——
    选中判断 表的 x/y 就是该选项的**客户区坐标**，**左键点击即选中**
    （2026-08-25 实测：选项.选中判断={x=119,y=386,w=126,h=14}）。
    事件解析(跳转链接) 对接任务选项是假成功（日志 ok=True 但任务没接），
    必须用左键点击坐标。
    """
    code = """
local out = {}
local t = tp.窗口.对话栏.选项 or {}
for k,v in pairs(t) do
  if type(v)=="table" then
    local text = tostring(v.基本内容 or "")
    local sj = v.选中判断
    local x, y = -1, -1
    if type(sj)=="table" then x = tonumber(sj.x); y = tonumber(sj.y) end
    out[#out+1] = text .. "|" .. tostring(x) .. "|" .. tostring(y)
  end
end
_G.__out = table.concat(out, ";")"""
    try:
        raw = _lua(gateway, code)
    except Exception:
        return {}
    accept_kw = ("怎么", "接取", "接受")
    for entry in (raw or "").split(";"):
        if "|" not in entry:
            continue
        parts = entry.split("|")
        text = parts[0] if parts else ""
        x, y = -1, -1
        try:
            x, y = int(parts[1]), int(parts[2])
        except (ValueError, IndexError, TypeError):
            pass
        if x <= 0 or y <= 0:
            continue
        if any(kw in text for kw in accept_kw):
            return {"text": text, "x": x, "y": y}
    return {}


def _left_click_accept(x: int, y: int) -> bool:
    """左键点击接任务选项（窗口像素坐标，不缩放——渲染=窗口尺寸）。"""
    try:
        from core.input_controller import input_controller
        input_controller.click(x, y, button="left", press_delay=0.1)
        return True
    except Exception as e:
        logger.warning(f"DSHNPC: 左键点击接受选项失败: {e}")
        return False


def _right_click_close():
    """右键关闭对话弹窗（窗口像素坐标，与任务序列"关闭对话框"一致）。"""
    try:
        from core.input_controller import input_controller
        input_controller.right_click(CLOSE_DIALOG_POS[0], CLOSE_DIALOG_POS[1],
                                     click_delay=100)
        return True
    except Exception as e:
        logger.warning(f"DSHNPC: 右键关闭弹窗失败: {e}")
        return False


def DSHNPC(
    npc_name: str = DEFAULT_NPC_NAME,
    gateway: str = DEFAULT_GATEWAY,
    verbose: bool = False,
    dialog_wait: float = 0.4,
) -> dict:
    """杜少海 NPC 处理主流程。

    1. 找杜少海（可能有多个候选，逐个 CALL）
    2. CALL 事件开始 弹对话
    3. 弹窗检测：有弹窗 → 右键 (550,85) 关闭；无弹窗 → 不右键

    :param npc_name: NPC 名称（默认"杜少海"）
    :param gateway: 网关地址（多组自动解析）
    :param dialog_wait: CALL 后等待对话栏刷新的秒数
    :return: dict {ok, message, steps, elapsed_ms}
    """
    t0 = time.time()
    steps = {}

    # ---- 1) 找 NPC ----
    cands = find_npcs_by_name(gateway, npc_name)
    steps["find_npc"] = {"count": len(cands), "cands": cands}
    if not cands:
        return {
            "ok": False,
            "message": f"NPC '{npc_name}' 不在当前场景（可能未刷新/不在该地图）",
            "steps": steps,
            "elapsed_ms": round((time.time() - t0) * 1000, 1),
        }

    # ---- 2) 逐个 CALL 事件开始 ----
    last_err = "未知"
    for ci, cand in enumerate(cands):
        nid = cand.get("id")
        if not nid:
            continue
        code = f"""
local v = tp.场景.场景人物[tonumber({nid})]
if not v or type(v) ~= "table" then _G.__out = "NOTFOUND"; return end
local mt = getmetatable(v)
local ok, ret = pcall(mt.__index.事件开始, v)
_G.__out = tostring(ok) .. "|" .. tostring(v.名称 or "")"""
        try:
            raw = _lua(gateway, code)
        except Exception as e:
            last_err = f"CALL 异常: {e}"
            continue
        if not raw or raw == "NOTFOUND":
            last_err = f"候选{ci} id={nid} 消失"
            continue
        parts = raw.split("|")
        ok = parts[0] == "true"
        realname = parts[1] if len(parts) > 1 else npc_name
        if not ok:
            last_err = f"候选{ci} id={nid} CALL 返回 false"
            continue

        # ---- 3) 弹窗检测：等对话栏刷新 ----
        time.sleep(dialog_wait)
        dialog = _check_dialog(gateway)
        steps["dialog"] = dialog

        if not dialog["open"]:
            # 没弹窗（罕见）→ 不打扰
            steps["close"] = {"ok": True, "skipped": "CALL 成功但无弹窗"}
            return {
                "ok": True,
                "message": f"CALL {realname} 成功，无弹窗",
                "steps": steps,
                "target": {"npc": realname, "id": nid},
                "elapsed_ms": round((time.time() - t0) * 1000, 1),
            }

        # 有弹窗 → 读"接任务"选项坐标 → 左键点击（事件解析是假成功，必须左键）
        opt = _find_accept_option(gateway)
        steps["accept_option"] = opt
        if not opt:
            # 没找到接受选项 → 兜底右键关（避免卡住）
            closed = _right_click_close()
            steps["close"] = {"ok": closed, "pos": list(CLOSE_DIALOG_POS),
                              "fallback": "未找到接受选项，兜底右键关"}
            return {
                "ok": False,
                "message": f"有弹窗但未找到接受选项（怎么/接取/接受），已兜底右键关",
                "steps": steps,
                "target": {"npc": realname, "id": nid},
                "elapsed_ms": round((time.time() - t0) * 1000, 1),
            }

        # 左键点击接受选项（= 接任务）
        clicked = _left_click_accept(opt["x"], opt["y"])
        steps["click_accept"] = {"ok": clicked, "pos": (opt["x"], opt["y"]),
                                 "text": opt["text"]}
        if not clicked:
            closed = _right_click_close()
            steps["close"] = {"ok": closed, "fallback": "左键点击失败，右键关"}
            return {
                "ok": False,
                "message": f"左键点击接受选项失败，已右键关",
                "steps": steps,
                "target": {"npc": realname, "id": nid},
                "elapsed_ms": round((time.time() - t0) * 1000, 1),
            }

        # ---- 4) 接任务后可能再弹"少侠再见"告别对话 → 右键关闭 ----
        time.sleep(0.4)
        dialog2 = _check_dialog(gateway)
        steps["dialog2"] = dialog2
        if dialog2["open"]:
            closed = _right_click_close()
            steps["close"] = {"ok": closed, "pos": list(CLOSE_DIALOG_POS),
                              "reason": "接任务后仍有弹窗，右键关闭"}
        else:
            steps["close"] = {"ok": True, "skipped": "接任务后无弹窗"}

        return {
            "ok": True,
            "message": f"杜少海 CALL+左键接任务成功（{opt['text']} @ {opt['x']},{opt['y']}）",
            "steps": steps,
            "target": {"npc": realname, "id": nid},
            "elapsed_ms": round((time.time() - t0) * 1000, 1),
        }

    return {
        "ok": False,
        "message": f"全部 {len(cands)} 个 '{npc_name}' 候选 CALL 失败（最后: {last_err}）",
        "steps": steps,
        "elapsed_ms": round((time.time() - t0) * 1000, 1),
    }
