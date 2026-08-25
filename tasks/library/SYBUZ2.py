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
import random
from typing import Optional, Tuple, Union, List
from utils.logger import logger



try:
    from config.config import config
except Exception:
    config = None

try:
    from core.group_config import gateway_url
    DEFAULT_GATEWAY = gateway_url()  # ★2026-08-25 多组：组1=18082，组2=18083...
except Exception:
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


def find_npc_by_name(gateway: str, npc_name: str, target_coord=None) -> Optional[dict]:
    """在 tp.场景.场景人物 按名称搜索 NPC，返回 {id, 格子x, 格子y, 名称} 或 None.

    ★2026-08-24 多开同名修复：同一场景可能同时存在多个同名 NPC（不同玩家任务
      实例各自刷一个，如多个"江湖大盗"）。返回**全部候选**中离 target_coord
      最近的一个——自己的任务 NPC 一定在任务追踪栏坐标附近（1~3 格），
      别人的在更远坐标。无 target_coord 时返回第一个匹配。
    """
    code = f"""
local out = {{}}
for id,u in pairs(tp.场景.场景人物 or {{}}) do
  if type(u)=="table" and tostring(u.名称 or "")=="{npc_name}" then
    local gx = tonumber(u.格子x or -1) or -1
    local gy = tonumber(u.格子y or -1) or -1
    out[#out+1] = string.format("%s|%s|%s|%s", id, gx, gy, gx*1000+gy)
  end
end
-- 按格子坐标排序（稳定输出，pairs 顺序不定会导致抓错同名 NPC）
table.sort(out, function(a,b)
  local _,_,_,sa = string.find(a, "|%d+|%d+|(%d+)$")
  local _,_,_,sb = string.find(b, "|%d+|%d+|(%d+)$")
  return (sa or "0") < (sb or "0")
end)
_G.__out = table.concat(out, ";")"""
    try:
        raw = _lua(gateway, code)
    except Exception:
        return None
    if not raw:
        return None
    cands = []
    for entry in raw.split(";"):
        if "|" in entry:
            parts = entry.split("|")
            if len(parts) >= 3:
                try:
                    cands.append({"id": parts[0], "x": parts[1], "y": parts[2]})
                except Exception:
                    pass
    if not cands:
        return None
    # 按与 target_coord 的曼哈顿距离升序选最近
    if target_coord is not None:
        try:
            tx, ty = int(target_coord[0]), int(target_coord[1])
            cands.sort(key=lambda c: (abs(int(c["x"]) - tx) + abs(int(c["y"]) - ty), c["id"]))
        except (ValueError, TypeError, IndexError):
            pass
    return cands[0]


def find_npcs_by_name(gateway: str, npc_name: str, npc_model: str = "") -> List[dict]:
    """返回名称匹配的 NPC 候选列表（[{id,x,y,model},...]）。

    ★2026-08-24 v4 定论：**只用名称过滤，不再过滤模型**——
      不同地图的江湖大盗 NPC 模型不同（建邺城=护卫，东海湾/江南野外
      可能是其他，巫医/御林军示例证实混淆），硬按 npc_model 过滤会
      漏掉真候选；任务上下文的元表代理让 `t.名称` 返回"江湖大盗"，
      但 CALL 时 v.名称 返回真实名（"超级巫医"/"御林军左统领"/"护卫"等）。

    真假由 call_npc_event_start 的"对话含战斗词"动态判定，本函数
    只负责尽可能多地圈出"可能是任务 NPC"的候选。

    ★id 是数字 key（tp.场景.场景人物 的 key 为 number:1,2,3...），
      保留数字供 CALL 精确索引。
    """
    code = f"""
local out = {{}}
for id,u in pairs(tp.场景.场景人物 or {{}}) do
  if type(u)=="table" and tostring(u.名称 or "")=="{npc_name}" then
    out[#out+1] = string.format("%s|%s|%s|%s", tostring(id),
      tostring(u.格子x or ""), tostring(u.格子y or ""), tostring(u.模型 or ""))
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
                cands.append({"id": parts[0], "x": parts[1], "y": parts[2],
                              "model": parts[3] if len(parts) > 3 else ""})
    return cands


def call_npc_event_start(gateway: str, npc_name: str, target_coord=None, target_location=None,
                         npc_model: str = "", verbose: bool = False) -> Tuple[bool, str]:
    """按名称搜 NPC → 在目标坐标上 CALL 事件开始() 弹对话.

    ★2026-08-24 定论（用户要求）：**只在目标坐标上 CALL，绝不瞬移去找 NPC**。
      角色已由 SYBUZ2 主流程瞬移到任务坐标 (gx,gy)——NPC 就刷新在任务坐标附近，
      直接在原地按名称+模型+就近选候选，用候选 **id 精确索引** CALL。
      禁止 SYHS 微调瞬移：会把角色带到别人的 NPC 格子上（跳到别人目标）。

    ★2026-08-24 多开同名修复：同图多个同名 NPC（别人任务的江湖大盗）——
      用 npc_model（JHRW1.npc，如"护卫"）过滤「模型」字段，直接锁定自己的
      任务 NPC（别人的同名 NPC/模板怪模型不同），再用 id 精确 CALL。
      CALL 后仍校验 v.名称 + 拒绝语，双保险。

    :param npc_model: 任务追踪栏 NPC 类型名（JHRW1 返回的 npc 字段），
        对应 NPC 对象的「模型」字段。为空则只按名称过滤。
    :return: (ok, 详情)
    """
# ---- 全部候选（只按名称），按离任务坐标曼哈顿距离升序 ----
    all_cands = find_npcs_by_name(gateway, npc_name)
    if not all_cands:
        return False, f"未找到 NPC '{npc_name}'（可能未刷新/不在此图）"
    if target_coord is not None:
        try:
            tx, ty = int(target_coord[0]), int(target_coord[1])
            all_cands.sort(key=lambda c: (abs(int(c["x"]) - tx) + abs(int(c["y"]) - ty), c["id"]))
        except (ValueError, TypeError, IndexError):
            pass

    # ★2026-08-24 v4：动态判定——CALL 后看对话框选项含战斗词才认，否就关掉换下一个
    battle_keywords = ("抓归案", "抓捕", "对付", "教训", "击杀", "杀死", "击败")
    last_err = "未知"
    for ci, cand in enumerate(all_cands):
        nid = cand.get("id")
        if not nid:
            continue
        # ---- CALL 事件开始：用候选 id 精确索引 ----
        code = f"""
local v = tp.场景.场景人物[tonumber({nid})]
if not v or type(v) ~= "table" then _G.__out = "NOTFOUND"; return end
local mt = getmetatable(v)
local ok, ret = pcall(mt.__index.事件开始, v)
local realname = tostring(v.名称 or "")
_G.__out = tostring(ok) .. "|" .. realname"""
        try:
            raw = _lua(gateway, code)
        except Exception as e:
            last_err = f"候选{ci} id={nid} CALL 异常: {e}"
            continue
        if not raw or raw == "NOTFOUND":
            last_err = f"候选{ci} id={nid} 消失"
            continue
        parts = raw.split("|")
        ok = parts[0] == "true"
        realname = parts[1] if len(parts) > 1 else ""

        if not ok:
            # ★2026-08-24 v5：临时微调一次再重试——CALL pcall 失败通常是因为
            # 任务追踪栏 (97,52) ≠ NPC 实际格子（差 1-3 格），客户端距离校验
            # 让 pcall 返回 false。临时 SYHS 瞬移到候选 NPC 格子再 CALL 一次。
            # 不预先微调（避免跳到别人目标），只在 CALL 失败时 retry。
            try:
                cx, cy = int(cand["x"]), int(cand["y"])
                from tasks.library.SYHS import SYHS
                rs = SYHS((cx, cy), target_location=target_location, gateway=gateway,
                          verbose=False, wait_stable=False, stable_timeout=10, stable_min_settle=0.8)
                if rs.get("ok"):
                    time.sleep(0.3)
                    # 重试 CALL 事件开始
                    try:
                        raw = _lua(gateway, code)
                    except Exception:
                        pass
                    if raw and raw != "NOTFOUND":
                        parts2 = raw.split("|")
                        ok2 = parts2[0] == "true"
                        realname2 = parts2[1] if len(parts2) > 1 else ""
                        if ok2:
                            # 重试成功：进入战斗词判定
                            time.sleep(0.3)
                            opts = get_dialog_options(gateway)
                            opt_text = " ".join(opts)
                            if any(kw in opt_text for kw in battle_keywords):
                                if verbose:
                                    logger.info(f"SYBUZ2: 候选{ci} 临时微调+重试成功 id={nid} 实际={realname2}")
                                return True, f"NPC={realname2} CALL事件开始 ok={ok2} 候选{ci} id={nid} 微调retry对话含战斗词"
                            # 重试成功但对话不对——关掉
                            try:
                                from core.input_controller import input_controller



                                input_controller.right_click(500, 310, click_delay=200)
                            except Exception:
                                pass
                            time.sleep(0.3)
                    last_err = f"候选{ci} id={nid} CALL false → 微调retry仍失败"
            except Exception as e:
                if verbose:
                    logger.warning(f"SYBUZ2: 候选{ci} 微调retry 异常 {e}")
            continue

        # ★★★ 动态判定：等对话栏刷新，看选项文本是否含战斗关键词 ★★★
        # 这是真正的稳定性判定（21:42 实测路径）——
        # CAL 任何 NPC 都可能成功，但只有任务 NPC 会弹"抓归案/对付"等战斗选项。
        time.sleep(0.3)
        opts = get_dialog_options(gateway)
        opt_text = " ".join(opts)
        if not any(kw in opt_text for kw in battle_keywords):
            # 不是任务 NPC（CALL 到了巫医/路人等）——关闭对话换下一个
            last_err = f"候选{ci} id={nid} 实际={realname} 对话无战斗词, 关掉换下一个"
            if verbose:
                logger.warning(f"SYBUZ2: {last_err}, opts={opts}")
            try:
                from core.input_controller import input_controller
                input_controller.right_click(500, 310, click_delay=200)
            except Exception:
                pass
            time.sleep(0.3)
            continue

        # 含战斗词 = 任务 NPC
        return ok, f"NPC={realname} CALL事件开始 ok={ok} 候选{ci} id={nid} 对话含战斗词"

    return False, f"全部 {len(all_cands)} 个候选 CALL 后对话均无战斗词（最后: {last_err}）"


def get_dialog_text(gateway: str) -> str:
    """读对话栏当前文本（NPC 说的话），用于拒绝语校验。"""
    code = """local out = {}
local t = tp.窗口.对话栏.记录文本 or {}
for k,v in pairs(t) do
  if type(v)=="table" then
    for kk,vv in pairs(v) do
      if type(vv)=="string" and #vv > 0 then out[#out+1] = vv end
    end
  elseif type(v)=="string" and #v > 0 then
    out[#out+1] = v
  end
end
if #out == 0 then
  -- 兜底: 选项基本内容（NPC 台词常在选项区上方）
  local o = tp.窗口.对话栏.选项 or {}
  for k,v in pairs(o) do
    if type(v)=="table" then out[#out+1] = tostring(v.基本内容 or "") end
  end
end
_G.__out = table.concat(out, "|")"""
    try:
        raw = _lua(gateway, code)
    except Exception:
        return ""
    return raw or ""


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
    npc_model: str = "",
    home_coord: Tuple[int, int] = (240, 101),
    battle_timeout: float = 180.0,
    gateway: str = DEFAULT_GATEWAY,
    verbose: bool = False,
    x: Union[int, str, None] = None,
    y: Union[int, str, None] = None,
    random_offset: bool = True,
    offset_x: tuple = (5, 15),
    offset_y: tuple = (5, 15),
):
    """
    站桩瞬移任务完整流程（Lua 直接 CALL 版，2026-08-23 突破）。

    :param target_coord: (gx, gy) 地图坐标 / JHRW dict / 地图名(字符串)
    :param target_location: 目标地图名（跨图判断，如 "江南野外"）
    :param npc_name: 目标 NPC 名称（默认"江湖大盗"）
    :param npc_model: 任务追踪栏 NPC 类型名（JHRW1.npc，如"护卫"）——
        对应 NPC 对象的「模型」字段，用于多开同名 NPC 精确定位（2026-08-24）
    :param home_coord: 站桩点（默认 240,101 长安）
    :param battle_timeout: 战斗等待超时秒数
    :param gateway: 网关地址
    :param x/y: 独立坐标分量（GUI 事件拆传兼容）
    :param random_offset: ★2026-08-25 仿人化——瞬移落点随机偏移，
        避免每次精确命中任务坐标暴露脚本规律（默认 x±5~15, y±5~15，
        随机符号，最大曼哈顿 30）。三轮实测：
        - x±400 → 91 触发 ❌
        - x±100 → 40 仍触发 ❌
        - x±30  → 48 仍触发 ❌
        - x±5~15 → 最大 30 留 20 余量给 NPC 散布，理论不触发
        仿人化效果减弱（5~15 格随机），但绝对安全。
        任务序列如需关闭传 random_offset=false。
    :param offset_x/offset_y: 偏移范围 (min, max)
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
        # ★2026-08-24 多开同名修复：从 JHRW dict 取 npc 字段（任务追踪栏 NPC 类型名，
        #   如"护卫"），作为 NPC「模型」过滤条件
        if not npc_model:
            npc_model = target_coord.get("npc") or ""
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
    # ★2026-08-24 提速：wait_stable=False——CALL 事件开始是纯 Lua 数据层操作，
    #   不依赖画面定格；等画面定格(4-5s)纯属浪费。场景人物表在瞬移后 Lua 层即
    #   已就绪。若 find NPC 为空由 call_npc_event_start 内部 retry 兜底。
    # ★2026-08-25 仿人化随机偏移：瞬移落点 = 任务坐标 ± 随机偏移
    #   （x 10~400, y 10~40，随机符号），避免每次精确落点暴露脚本规律。
    #   偏移后 CALL 仍用任务点 (gx,gy) 做候选距离排序（NPC 刷在任务点附近），
    #   CALL 本身同图任意距离有效，偏移不影响。
    gx_tele, gy_tele = gx, gy
    if random_offset:
        try:
            dx = random.randint(offset_x[0], offset_x[1])
            dy = random.randint(offset_y[0], offset_y[1])
            dx = dx if random.random() < 0.5 else -dx
            dy = dy if random.random() < 0.5 else -dy
            gx_tele, gy_tele = gx + dx, gy + dy
            steps["teleport_offset"] = (dx, dy)
            if verbose:
                logger.info(f"SYBUZ2: 瞬移随机偏移 ({dx:+d},{dy:+d}) → ({gx_tele},{gy_tele})")
        except (ValueError, TypeError):
            gx_tele, gy_tele = gx, gy
    try:
        from tasks.library.SYHS import SYHS
        r = SYHS((gx_tele, gy_tele), target_location=target_location, gateway=gateway,
                 verbose=verbose, wait_stable=False)
        steps["teleport_to_target"] = {
            "ok": r.get("ok"), "coord": (gx_tele, gy_tele),
            "map_switch": (r.get("map_switch") or {}).get("mode"),
            "server_sync": r.get("server_sync"),
        }
        if not r.get("ok"):
            return {"ok": False, "message": f"瞬移到任务点失败: {r.get('message')}",
                    "steps": steps, "elapsed_ms": round((time.time() - t0) * 1000, 1)}
    except Exception as e:
        return {"ok": False, "message": f"SYHS 调用异常: {e}", "steps": steps,
                "elapsed_ms": round((time.time() - t0) * 1000, 1)}

    # ---- 2) 按名称+模型搜 NPC → 在任务坐标上 CALL 事件开始（★核心突破，不瞬移）----
    npc_ok, npc_info = call_npc_event_start(gateway, npc_name, target_coord=(gx, gy),
                                            target_location=target_location, npc_model=npc_model,
                                            verbose=verbose)
    steps["call_npc"] = {"ok": npc_ok, "info": npc_info}
    if not npc_ok:
        # ★2026-08-24 用户要求（v2）：失败不立即瞬移回长安，原地等任务上下文切换
        # 重试最多 10 次（间隔 2.5s，共 ~25s 窗口）。任务 NPC 名称是动态标签
        # （江湖大盗↔鬼怪/巫医/统领），上下文切换后同图会重刷真名——原地轮询
        # 命中率高且省瞬移。**但 10 次全失败必须回城**，否则任务序列永远停在
        # 任务图上无法推进（JHRW1 读同一任务、SYBUZ2 再失败，死循环）。
        for _ in range(10):
            time.sleep(2.5)
            npc_ok, npc_info = call_npc_event_start(gateway, npc_name, target_coord=(gx, gy),
                                                    target_location=target_location,
                                                    npc_model=npc_model, verbose=verbose)
            steps.setdefault("call_npc_retries", []).append({"ok": npc_ok, "info": npc_info})
            if npc_ok:
                break
    if not npc_ok:
        steps["battle"] = {"ok": False, "info": f"NPC '{npc_name}' 未找到"}
        # ★10 次全失败 → 回城重来（兜底，防任务序列卡死在任务图）
        steps["return_home"] = _return_home(gateway, home_coord, verbose)
        return {"ok": False,
                "message": f"NPC '{npc_name}' 未找到（原地重试10次后仍未命中，回城重来）",
                "steps": steps, "target_coord": (gx, gy), "target_location": target_location,
                "elapsed_ms": round((time.time() - t0) * 1000, 1)}

    # ---- 3) 读选项 → CALL 事件解析 选战斗 ----
    time.sleep(0.3)  # 等对话栏刷新（提速：0.6s→0.3s，对话在 CALL 返回后已写入）
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
        # 提速：wait_stable=False，回城后下一轮任务会重新瞬移，无需定格等待
        rb = SYHS(home_coord, target_location="长安", gateway=gateway,
                  verbose=verbose, wait_stable=False)
        return {"ok": rb.get("ok"), "message": rb.get("message")}
    except Exception as e:
        return {"ok": False, "message": str(e)}
