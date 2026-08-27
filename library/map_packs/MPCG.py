# -*- coding: utf-8 -*-
"""
MPCG - 门派闯关专用识别与配合函数（Lua 网关直读版，2026-08-25 refactor-mpcg-lua）
================================================================================
功能: 参照 JHRW1 / SYBUZ2 / DSHNPC 的 Lua 网关直读模式，重做原"截图+整词模板+字模"
      方案。默认读游戏 Lua 层数据，不截屏、不依赖窗口可见，后台挂机可用。

===== 数据源（2026-08-25 实测确认，组2·大唐官府）=====
  - 门派闯关任务记录: tp.窗口.任务追踪栏.数据记录 中「类型=107」的那条记录
  - 关键字段:
      当前序列   当前处于第几关（1 起）
      闯关序列   table{1..15}：位置→门派索引（目标门派 = 闯关序列[当前序列]）
  - 实测定标:
      当前序列=1 且闯关序列[1]=1 → 任务栏显示「大唐官府,0次」✅
      ⇒ 目标门派名 = 15门派序表[闯关序列[当前序列]]
      ⇒ 完成次数 count = 当前序列 - 1
  - 15门派序表（索引1 起，索引1=大唐官府 已交叉验证；其余沿用标准门派闯关顺序，
    与 core/sect_task_recognizer.MAP_NAMES 前 15 一致）:
      大唐官府/方寸山/化生寺/凌波城/龙宫/魔王寨/女儿村/普陀山/
      盘丝洞/神木林/狮驼岭/天宫/无底洞/五庄观/阴曹地府

边界:
  - 未接门派闯关任务（数据记录无类型=107）→ 返回兼容空值，可回退截图
  - 网关不可用/自愈拉起仍失败 → 自动回退原截图识别引擎（source='screenshot'）
  - 后台读取依赖"任务已激活"，无需任务栏可见（Lua 数据记录非渲染层）

依赖: mhxy-mcp-gateway 网关（frida 附加，HTTP 默认 18082/多组）
      core.group_config（多组网关 URL）、core.gateway_guard（网关自愈）
      core.sect_task_recognizer（回退截图识别引擎）、core.window_manager/screen_capture

使用方式:
  1. 任务序列（GUI「函数调用」事件）:
     module=MPCG, function=MPCG_recognize
     → 结果 dict 存入变量，后续可用 ${MPCG_recognize.target_location} /
       ${MPCG_recognize.map_name} / ${MPCG_recognize.count} / ${MPCG_recognize.text} 引用
     function=MPCG_open_taskbar（打开/确认任务追踪栏）
     function=MPCG_teleport_sect（跳转目标门派图, 传 map_name=X）
  2. 命令行:
     python MPCG.py                   # 识别当前游戏窗口（组1 网关 18082）
     python MPCG.py -p 12345          # 指定 PID
     python MPCG.py --port 18083      # 指定网关端口（多组）
"""
# ============================================================
# 函数中文元信息（GUI 下拉框显示用）
# ============================================================
__function_meta__ = {
    "MPCG_recognize": {
        "title": "门派闯关: 识别当前目标任务（Lua 直读，落截图回退）",
        "args": {
            "gateway": "mhxy-mcp-gateway 地址/端口（默认按组自动解析，如 http://127.0.0.1:18082/18083）",
            "pid": "游戏进程 PID（回退截图时用；默认取任务库已绑定 PID）",
            "roi": "回退截图识别区域 (x,y,w,h)，默认 (840,156,150,131)；Lua 直读时忽略",
            "verbose": "是否打印过程日志",
        },
    },
    "MPCG_open_taskbar": {
        "title": "门派闯关: 确认任务追踪栏数据就绪",
        "args": {
            "gateway": "mhxy-mcp-gateway 地址/端口（默认按组自动解析）",
            "verbose": "是否打印过程日志",
        },
    },
    "MPCG_teleport_sect": {
        "title": "门派闯关: 跳转到目标门派图（网关跨图+瞬移+服务端同步）",
        "args": {
            "map_name": "目标门派名（如 大唐官府/天宫）；也接受 MPCG_recognize 输出 dict",
            "gateway": "mhxy-mcp-gateway 地址/端口（默认按组自动解析）",
            "x": "可选，目标地图坐标 x（缺省用当前图传送入口坐标）",
            "y": "可选，目标地图坐标 y",
            "verbose": "是否打印过程日志",
        },
    },
    "MPCG_call_guard": {
        "title": "门派闯关: CALL 门派护法（瞬移到护法旁→CALL→请出招吧开战）",
        "args": {
            "map_name": "目标门派名；也接受 MPCG_recognize 输出 dict（自动取 target_location）",
            "x": "可选，护法所在格坐标 x（缺省用内置 SECT_GUARD_COORDS）",
            "y": "可选，护法所在格坐标 y",
            "gateway": "mhxy-mcp-gateway 地址/端口（默认按组自动解析）",
            "pid": "游戏 PID（缺省用网关绑定）",
            "start": "True=点「请出招吧」开战（默认），False=只 CALL 打开对话",
            "verbose": "是否打印过程日志",
        },
    },
    "MPCG_goto_city": {
        "title": "门派闯关: 回主城长安（完成后回长安 193,125 CALL 门派闯关使者）",
        "args": {
            "city": "目标主城名/关键字（默认长安）",
            "x": "到城后落点 x（默认 193，门派闯关使者）",
            "y": "到城后落点 y（默认 125）",
            "gateway": "mhxy-mcp-gateway 地址/端口（默认按组自动解析）",
            "pid": "游戏 PID（缺省用网关绑定）",
            "verbose": "是否打印过程日志",
        },
    },
    "MPCG_accept_round": {
        "title": "门派闯关: 回城后自动接取下一轮（CALL使者→点「准备好了」）",
        "args": {
            "gateway": "mhxy-mcp-gateway 地址/端口（默认按组自动解析）",
            "pid": "游戏 PID（缺省用网关绑定）",
            "do_goto": "True=若不在长安先回城；False=要求已在长安（默认False）",
            "x": "可选，落点 x（默认 193，门派闯关使者）",
            "y": "可选，落点 y（默认 125）",
            "verbose": "是否打印过程日志",
        },
    },
    "main": {
        "title": "命令行测试入口",
        "args": {},
    },
    "MPCG_auto_round": {
        "title": "门派闯关: 整轮自动（勾一个全链路：识别→传送→CALL→开战→循环→回城→接下一轮）",
        "args": {
            "timeout": "整轮最长等待秒数（默认5400=90分钟，仅时间兜底）",
            "max_steps": "【已废弃】不再限制关卡数（默认0=不限）；只看门派闯关是否完成，steps 仅作进度打印",
            "rounds": "连续自动跑几轮，完成后自动回城接下一轮（默认1）",
            "gateway": "mhxy-mcp-gateway 地址/端口（默认按组自动解析）",
            "pid": "游戏 PID（缺省用网关绑定）",
            "verbose": "是否打印过程日志",
        },
    },
}
import json
import sys
import os
import re
import time
import urllib.request
from typing import Optional, Tuple, Union

try:
    from utils.logger import logger
except Exception:  # 独立运行
    import logging
    logger = logging.getLogger("MPCG")
    logging.basicConfig(level=logging.INFO)

# ============================================================
# 项目路径 + 默认网关（多组）
# ============================================================
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJ_ROOT = os.path.abspath(os.path.join(_THIS_DIR, "..", ".."))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

try:
    from core.group_config import gateway_url
    DEFAULT_GATEWAY = gateway_url()
except Exception:
    DEFAULT_GATEWAY = "http://127.0.0.1:18082"

try:
    from core.input_controller import input_controller
except Exception:  # 独立运行
    input_controller = None

# ============================================================
# 15 门派序表（索引 1 起）。索引 1=大唐官府 已实测交叉验证；
# 其余顺序与 core.sect_task_recognizer.MAP_NAMES 前 15 一致（标准门派闯关顺序）。
# ============================================================
SECT_LIST_15 = [
    "大唐官府", "方寸山", "化生寺", "凌波城", "龙宫", "魔王寨", "女儿村",
    "普陀山", "盘丝洞", "神木林", "狮驼岭", "天宫", "无底洞", "五庄观",
    "阴曹地府",
]

# 默认识别区域（回退截图用；客户区坐标）
DEFAULT_ROI = (840, 156, 150, 131)


# ============================================================
# 网关调用（复用 JHRW1 自愈模式：连接/内部 rpc 失败 → ensure_gateway → 重试一次）
# ============================================================
def _lua_call(gateway: str, code: str, timeout: float = 10.0) -> dict:
    """调网关 /api/lua 执行 Lua，返回 {ok, value, error}。带自愈重试。"""
    req = urllib.request.Request(
        gateway.rstrip("/") + "/api/lua",
        data=json.dumps({"code": code}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )

    def _do():
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))

    try:
        d = _do()
    except Exception as e:
        d, _err = None, e
    if d is None or not d.get("ok"):
        # 连接失败 或 网关内部失败 → 自动拉起网关 → 重试一次
        try:
            from core.gateway_guard import ensure_gateway
            ok, info = ensure_gateway(verbose=False)
        except Exception:
            ok, info = False, {}
        if not ok:
            err = d.get("error") if d is not None else _err
            return {
                "ok": False,
                "error": (
                    f"{err}（网关不可用且自动拉起失败：{info.get('error', '未知')}。"
                    f"请确认游戏已启动，或手动运行 E:/DS/mhxy-mcp-gateway/启动网关.bat）"
                ),
            }
        try:
            d = _do()
        except Exception as e2:
            return {"ok": False, "error": f"{e2}（网关自愈拉起后仍连接失败，检查 {gateway}）"}
    if d.get("ok"):
        return {"ok": True, "value": d.get("result", {}).get("value")}
    return {"ok": False, "error": d.get("error", "")}


def _http_json(gateway: str, path: str, data: Optional[dict] = None, timeout: float = 10.0) -> dict:
    """向网关发 HTTP（GET/POST JSON）。"""
    req = urllib.request.Request(
        gateway.rstrip("/") + path,
        data=json.dumps(data).encode("utf-8") if data is not None else None,
        headers={"Content-Type": "application/json"} if data is not None else {},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


# ============================================================
# Lua 读取：类型=107 门派闯关记录 → {current_seq, seq_table, count, target_index}
# ============================================================
_LUA_READ_MPCG = r'''
local out = {}
local t = tp.窗口.任务追踪栏.数据记录
local hit = nil
if type(t) == "table" then
  for k, v in pairs(t) do
    if type(v) == "table" and tostring(v.类型 or "") == "107" then hit = v end
  end
end
if not hit then _G.__out = "NO_MPCG"; return end
out.current_seq = tostring(hit.当前序列 or "0")
local seq = {}
if type(hit.闯关序列) == "table" then
  for k, v in pairs(hit.闯关序列) do seq[#seq + 1] = tonumber(v) end
  table.sort(seq, function(a, b) return a < b end)  -- 数值序；字符串排序会因"10"<"2"打乱
end
out.seq = table.concat(seq, ",")
out.seq_count = tostring(#seq)
-- 目标门派索引 = 闯关序列[当前序列]
out.target_index = "0"
local cs = tonumber(hit.当前序列)
local sq = hit.闯关序列
if cs and type(sq) == "table" and sq[cs] then out.target_index = tostring(sq[cs]) end
_G.__out = ""
for k, v in pairs(out) do _G.__out = _G.__out .. k .. "=" .. v .. "\n" end
'''


def _parse_kv(text: str) -> dict:
    data = {}
    for line in (text or "").splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            data[k.strip()] = v.strip()
    return data


def _lua_read_mpcg(gateway: str) -> dict:
    """读门派闯关 Lua 记录，返回 dict；无记录返回 {'ok': False}。"""
    r = _lua_call(gateway, _LUA_READ_MPCG)
    if not r.get("ok"):
        return {"ok": False, "error": r.get("error", "")}
    v = (r.get("value") or "").strip()
    if v == "NO_MPCG":
        return {"ok": False, "error": "未接门派闯关任务（数据记录无类型=107）"}
    d = _parse_kv(v)
    current_seq = 0
    try:
        current_seq = int(d.get("current_seq") or 0)
    except (TypeError, ValueError):
        pass
    target_index = 0
    try:
        target_index = int(d.get("target_index") or 0)
    except (TypeError, ValueError):
        pass
    return {
        "ok": True,
        "current_seq": current_seq,
        # 完成次数 = 当前序列 - 1（已实测校准：当前序列=1 显示 0 次）
        "count": max(0, current_seq - 1),
        "target_index": target_index,
        "seq_raw": d.get("seq", ""),
        "seq_count": int(d.get("seq_count") or 0),
        # 本服（2026-08-25 实测）闯关序列恒等 1..15、当前序列=9，无法借序表映射出真实目标。
        # identity=True 表示「恒等序」：不得再以 SECT_LIST_15 映射目标，应以对话/弹窗文本为准。
        "seq_identity": _is_identity_seq(d.get("seq", "")),
    }


# ============================================================
# Lua 读取：任务追踪栏「介绍文本」渲染文本（真实可靠的目标门派 + 完成次数）
# 本服类型=107 记录的「闯关序列」恒等 1..15、当前序列不可信；但任务追踪栏
# 介绍文本会实时渲染「请立即前往 X 门派…已成功完成了 N 次考验」，据此最稳。
# ============================================================
_LUA_READ_INTRO = r'''
local tb=tp.窗口.任务追踪栏.介绍文本
if not tb then _G.__out=''; return end
if not tb.显示表 then _G.__out=''; return end
local parts={}
for _,line in ipairs(tb.显示表) do
  if type(line)=='table' then
    for _,seg in ipairs(line) do
      if type(seg)=='table' and seg.内容 then parts[#parts+1]=seg.内容 end
    end
  end
end
_G.__out=table.concat(parts,'')
'''


def _lua_read_mpcg_intro(gateway: str) -> dict:
    """读取任务追踪栏介绍文本；返回 {ok, text, target, count}。"""
    r = _lua_call(gateway, _LUA_READ_INTRO)
    if not r.get("ok"):
        return {"ok": False, "error": r.get("error", "")}
    text = (r.get("value") or "").strip()
    if not text:
        return {"ok": False, "error": "介绍文本为空"}
    return {
        "ok": True,
        "text": text,
        "target": _intro_target(text),
        "count": _intro_count(text),
    }


def _intro_target(text: str) -> Optional[str]:
    """从介绍文本中匹配门派名（按 SECT_LIST_15 白名单，出现即命中）。"""
    for name in SECT_LIST_15:
        if name in (text or ""):
            return name
    return None


def _intro_count(text: str) -> int:
    """从介绍文本解析「已成功完成了 N 次」。"""
    m = re.search(r"完成[了]?\s*(\d+)\s*次", text or "")
    try:
        return int(m.group(1)) if m else 0
    except (TypeError, ValueError):
        return 0


# 介绍文本的「本轮已完成」提示（无门派目标 + 命中以下措辞 = 闯关已结束待领奖）
_DONE_INTRO_RE = re.compile(r"领取奖励|领奖|全部完成|已完成全部|考验结束|考验已完成|闯关完成")
# 介绍文本的「需要接任务」提示（无门派目标 + 命中以下措辞 = 任务还没接/接完要再接，
# 应去长安使者处接取，绝不能当成「完成」收尾！2026-08-26 拆出，避免误判退出）
_ACCEPT_INTRO_RE = re.compile(r"领取任务|领取下一轮|门派闯关使者|使者处领取|前往.*使者|闯关使者")


def _sect_name(target_index: int) -> str:
    """门派索引 → 门派名（1 起）。越界返回 ''。"""
    if 1 <= target_index <= len(SECT_LIST_15):
        return SECT_LIST_15[target_index - 1]
    return ""


def _is_identity_seq(seq_raw: str) -> bool:
    """判断闯关序列是否为恒等 1..N（本服不可信，不能用于映射目标门派）。"""
    raw = (seq_raw or "").strip()
    if not raw:
        return False
    try:
        vals = [int(x) for x in raw.split(",") if x.strip() != ""]
    except (TypeError, ValueError):
        return False
    if not vals:
        return False
    return vals == list(range(1, len(vals) + 1))


# ============================================================
# MPCG_recognize：默认 Lua 直读 + 截图回退
# ============================================================
def _recognize_screenshot(pid: Optional[int], roi):
    """回退截图识别（原方案）。返回与 MPCG_recognize 同结构 dict。"""
    from core.sect_task_recognizer import recognize_sect_task, _load_templates
    from core.window_manager import window_manager
    from core.screen_capture import screen_capture

    x, y, w, h = roi
    if pid is not None:
        if not window_manager.is_valid() or getattr(window_manager, "pid", None) != pid:
            window_manager.bind(pid=pid)
    if not window_manager.is_valid():
        pid = _find_game_pid()
        if pid:
            window_manager.bind(pid=pid)
    if not window_manager.is_valid():
        return {
            "map_name": None, "count": "?", "text": "?,?次", "best_score": 0.0,
            "roi": list(roi), "source": "screenshot", "error": "窗口未绑定",
        }
    img_bgr = screen_capture.capture_region(x, y, w, h)
    if img_bgr is None:
        return {
            "map_name": None, "count": "?", "text": "?,?次", "best_score": 0.0,
            "roi": list(roi), "source": "screenshot", "error": "截图失败",
        }
    detail = recognize_sect_task(img_bgr, templates=_load_templates(), return_detail=True)
    return {
        "target_location": detail["map_name"],
        "map_name": detail["map_name"],
        "count": detail["count"],
        "text": detail["text"],
        "best_score": detail["best_score"],
        "roi": list(roi),
        "source": "screenshot",
        "digit_count": detail["digit_count"],
    }


def MPCG_recognize(
    pid: Optional[int] = None,
    roi: Optional[Tuple[int, int, int, int]] = None,
    gateway: str = DEFAULT_GATEWAY,
    verbose: bool = True,
):
    """
    识别门派闯关任务: 目标门派 + 完成次数。

    默认走 Lua 网关直读（type=107 记录）；网关不可用或无记录时回退截图识别。

    :param pid: 游戏进程 PID（回退截图用；None 用窗口管理器已绑定 PID）
    :param roi: 回退截图识别区域 (x,y,w,h)，默认 (840,156,150,131)
    :param gateway: 网关地址/端口（可按组传 http://127.0.0.1:18083）
    :param verbose: 是否打印过程日志
    :return: dict {
        'target_location': '大唐官府' or None,   # 目标门派名
        'map_name': 同上,
        'count': '0' or '?',                     # 完成次数（字符串，兼容）
        'text': '大唐官府,0次',
        'best_score': 1.0(Lua) / 截图分数,
        'roi': [840,156,150,131],
        'source': 'lua_gateway' | 'screenshot',
    }
    """
    if roi is None:
        roi = DEFAULT_ROI

    # ★首选：任务追踪栏「介绍文本」渲染文本（真实目标门派 + 次数，不依赖恒等序列）
    try:
        intro = _lua_read_mpcg_intro(gateway)
    except Exception:
        intro = {"ok": False, "error": "intro 读取异常"}
    if intro.get("ok") and intro.get("target"):
        return {
            "target_location": intro["target"],
            "map_name": intro["target"],
            "count": str(intro["count"]),
            "text": f"{intro['target']},{intro['count']}次",
            "best_score": 1.0,
            "roi": list(roi),
            "source": "lua_intro",
            "intro_text": intro.get("text", ""),
        }

    lu = _lua_read_mpcg(gateway)
    if lu.get("ok") and lu.get("target_index"):
        map_name = _sect_name(lu["target_index"])
        count = str(lu["count"])
        if map_name and lu.get("seq_identity"):
            # 本服闯关序列恒等（不可信）→ 不伪造目标，交由对话/弹窗文本判定，避免错传(盘丝洞)
            logger.warning(
                f"MPCG_recognize: 闯关序列恒等(seq={lu['seq_raw']})不可映射目标，"
                f"应由对话/弹窗文本判定（记录当前序列={lu['current_seq']}）")
            return {
                "target_location": None,
                "map_name": None,
                "count": count,
                "text": f"{count}次(序列恒等不可映射)",
                "best_score": 1.0,
                "roi": list(roi),
                "source": "lua_gateway",
                "seq_identity": True,
                "current_seq": lu["current_seq"],
                "target_index": lu["target_index"],
                "seq_raw": lu["seq_raw"],
                "seq_count": lu["seq_count"],
            }
        if map_name:
            result = {
                "target_location": map_name,
                "map_name": map_name,
                "count": count,
                "text": f"{map_name},{count}次",
                "best_score": 1.0,          # Lua 直读视为满分命中
                "roi": list(roi),
                "source": "lua_gateway",
                "current_seq": lu["current_seq"],
                "target_index": lu["target_index"],
                "seq_count": lu["seq_count"],
                "seq_identity": False,
            }
            if verbose:
                logger.info(f"MPCG_recognize(lua): {result['text']} "
                            f"cur={lu['current_seq']} idx={lu['target_index']}")
            return result

    # ---- 回退截图 ----
    # ★2026-08-26：Lua 明确「未接任务」（无类型=107）时，截图识别会把任务栏残留文字
    #   误判成目标门派（如「大唐官府」），导致假 CALL、假 steps。此时直接返回「无任务」，
    #   交由 MPCG_auto_round 走接任务分支，绝不回退截图瞎猜。
    if lu.get("error") and "未接" in lu.get("error", ""):
        return {
            "target_location": None,
            "map_name": None,
            "count": "0",
            "text": "未接门派闯关任务",
            "best_score": 0.0,
            "roi": list(roi),
            "source": "lua_no_quest",
        }
    logger.warning(
        f"MPCG_recognize: Lua 直读不可用（{lu.get('error', '目标索引缺失')}），回退截图识别")
    result = _recognize_screenshot(pid, roi)
    if verbose:
        logger.info(f"MPCG_recognize(截图回退): {result.get('text')}")
    return result


# ============================================================
# MPCG_open_taskbar：确认任务追踪栏数据就绪（纯 Lua 读取）
# ============================================================
def MPCG_open_taskbar(gateway: str = DEFAULT_GATEWAY, verbose: bool = False) -> dict:
    """
    确认门派闯关任务数据就绪（Lua 层可读）。

    纯 Lua 读取不需要任务栏可见（数据记录非渲染层）。本函数验证类型=107 记录存在，
    网关不可用/无任务时给出明确结果，供任务序列做前置校验。

    :param gateway: 网关地址/端口
    :param verbose: 是否打印过程日志
    :return: dict {ok, message, source, ...}
    """
    t0 = time.time()
    lu = _lua_read_mpcg(gateway)
    if not lu.get("ok"):
        return {
            "ok": False,
            "message": f"{lu.get('error', '未接门派闯关任务')}（source=lua）",
            "source": "lua_gateway",
            "elapsed_ms": round((time.time() - t0) * 1000, 1),
        }
    map_name = _sect_name(lu["target_index"])
    if lu.get("seq_identity"):
        # 本服闯关序列恒等 → 不可映射目标，需对话/弹窗文本判定
        return {
            "ok": False,
            "message": f"任务记录存在但闯关序列恒等(seq={lu['seq_raw']})，无法由序表确认目标，"
                       f"请以使者/护法弹窗文本为准（source=lua）",
            "source": "lua_gateway",
            "current_seq": lu["current_seq"],
            "seq_identity": True,
            "elapsed_ms": round((time.time() - t0) * 1000, 1),
        }
    ok = bool(map_name)
    if verbose:
        logger.info(f"MPCG_open_taskbar: 当前序列={lu['current_seq']} 目标={map_name} "
                    f"(idx={lu['target_index']}) 次数={lu['count']}")
    return {
        "ok": ok,
        "message": f"任务追踪栏数据就绪: 目标={map_name or '未知'} 完成{lu['count']}次"
                   if ok else "目标门派索引无效",
        "map_name": map_name,
        "count": lu["count"],
        "current_seq": lu["current_seq"],
        "source": "lua_gateway",
        "elapsed_ms": round((time.time() - t0) * 1000, 1),
    }


# ============================================================
# 门派地图ID（会员卡瞬移实测采集，2026-08-25，组2·PID17000）
# ============================================================
SECT_MAP_ID = {
    "大唐官府": "1198", "方寸山": "1135", "化生寺": "1002", "凌波城": "1150",
    "龙宫": "1116", "魔王寨": "1512", "女儿村": "1142", "普陀山": "1140",
    "盘丝洞": "1513", "神木林": "1138", "狮驼岭": "1131", "天宫": "1111",
    "无底洞": "1139", "五庄观": "1146", "阴曹地府": "1122",
}

# v1 图（旧图）无法通过会员卡直接瞬移？——实测均可抵达，以下为跨图 desc 直达回退，非主路径。
# 会员卡「门派传送」子菜单第 2 项（门派传送）与每门派选项的 选中判断 中心坐标，随实例动态读取。

# ============================================================
# 各门派护法所在地图坐标（网格, 地图坐标格 = 真实坐标/20）。
# 2026-08-25 玩家提供：会员卡落地后瞬移到该坐标即可让「X门派护法」刷进附近。
# 龙宫(-1,-1)=无需瞬移（任务落地即在护法旁），直接 CALL 龙宫护法。
# 已实测锚定：大唐官府护法 真实(2780,920)=格(139,46) ≈ 玩家坐标(132,47)✅
# ============================================================
SECT_GUARD_COORDS = {
    "阴曹地府": (64, 80),  "方寸山": (42, 122), "女儿村": (79, 81),
    "神木林": (42, 161),   "化生寺": (29, 76),  "大唐官府": (132, 47),
    "盘丝洞": (148, 101),  "无底洞": (56, 89),  "魔王寨": (29, 43),
    "狮驼岭": (100, 6),    "天宫": (191, 129),  "普陀山": (70, 50),
    "凌波城": (39, 74),    "五庄观": (35, 34),  "龙宫": (-1, -1),
}

# 护法对话选项文字（CALL 成功后点该选项开始派系考验）
_GUARD_START_OPTION = "请出招吧"

# ============================================================
# 后台窗口事件（PostMessage，不抢焦点，PID17000 后台挂机可用）
# ============================================================
_WM_MOUSEMOVE = 0x0200
_WM_LBUTTONDOWN = 0x0201
_WM_LBUTTONUP = 0x0202
_WM_RBUTTONDOWN = 0x0204
_WM_RBUTTONUP = 0x0205
_WM_KEYDOWN = 0x0100
_WM_KEYUP = 0x0101
_VK_TAB = 0x09
_MK_L = 0x0001
_MK_R = 0x0002


def _lp(x, y):
    return (int(y) << 16) | (int(x) & 0xFFFF)


def _click(hwnd, cx, cy, rbutton=False):
    """后台左键/右键点击客户区坐标 (cx, cy)。hwnd 无效直接返回 False。"""
    if not hwnd or cx is None or cy is None:
        return False
    import ctypes
    user32 = ctypes.windll.user32
    down, up, mk = (_WM_RBUTTONDOWN, _WM_RBUTTONUP, _MK_R) if rbutton \
        else (_WM_LBUTTONDOWN, _WM_LBUTTONUP, _MK_L)
    user32.PostMessageW(hwnd, _WM_MOUSEMOVE, 0, _lp(cx, cy))
    time.sleep(0.12)
    user32.PostMessageW(hwnd, down, mk, _lp(cx, cy))
    time.sleep(0.12)
    user32.PostMessageW(hwnd, up, 0, _lp(cx, cy))
    return True


def _press_key(hwnd, vk=_VK_TAB):
    if hwnd:
        import ctypes
        user32 = ctypes.windll.user32
        user32.PostMessageW(hwnd, _WM_KEYDOWN, vk, 0)
        user32.PostMessageW(hwnd, _WM_KEYUP, vk, 0)


def _lua_expr(gateway, expr: str):
    """走网关 /api/lua/expr 求值，返回字符串值或 None。"""
    try:
        d = _http_json(gateway, "/api/lua/expr", {"expr": expr})
        return d.get("result", {}).get("value")
    except Exception:
        return None


def _lua_read(gateway, code: str) -> str:
    """执行一段 Lua（约定写入 _G.__out），返回字符串值。"""
    r = _lua_call(gateway, code)
    return r.get("value") or ""


# ---- 会员卡菜单状态读取（对话栏即会员传送界面）----
def _member_dialog_state(gateway) -> str:
    code = r'''
local d = tp.窗口.对话栏
local out = "可视=" .. tostring(d and d.可视 or false)
local opt = d and d.选项
if type(opt) == "table" then
  for i = 1, 30 do
    local o = opt[i]
    if type(o) ~= "table" then break end
    out = out .. "|" .. tostring(o.跳转链接 or "")
  end
end
_G.__out = out'''
    return _lua_read(gateway, code)


def _open_bag(gateway) -> bool:
    """用 Lua 直接 CALL 道具行囊:打开() 开背包（后台安全：不抢焦点、无鼠标/键盘注入）。

    实测（2026-08-25）：ALT+E 键盘在后台模式因游戏读不到系统键盘状态表而不可用；
    PostMessage 鼠标点击按钮又可能有误差。CALL 窗口方法 打开() 直接在游戏内开箱，
    可视=true 且物品随之加载。返回是否已打开。"""
    r = _lua_call(gateway, r'''
local b = tp.窗口 and tp.窗口.道具行囊
if not b then _G.__out="NO"; return end
local ok, err = pcall(function() return b["打开"](b) end)
_G.__out = tostring(ok) .. (err and (":" .. tostring(err)) or "")''')
    for _ in range(5):
        if _lua_expr(gateway, "tostring(tp.窗口.道具行囊.可视 or false)") == "true":
            return True
        time.sleep(0.15)
    return False


def _member_card_pos(gateway):
    """袋中「鲜衣怒马会员卡」item 坐标 (x,y)；找不到返回 (None,None)。"""
    code = r'''
local bag = tp.窗口.道具行囊
local out = "-1,-1"
if type(bag) == "table" and type(bag.物品) == "table" then
  for k, it in pairs(bag.物品) do
    if type(it) == "table" and tostring(it.名称 or "") == "鲜衣怒马会员卡" then
      out = tostring(it.x) .. "," .. tostring(it.y)
      break
    end
  end
end
_G.__out = out'''
    v = _lua_read(gateway, code)
    try:
        x, y = v.split(",")
        return int(x), int(y)
    except (ValueError, TypeError):
        return None, None


def _member_sect_center(gateway, name):
    """门派传送子菜单里目标门派选项中心坐标；未找到返回 (None,None)。"""
    code = (r'''
local opt = tp.窗口.对话栏.选项
local out = ""
if type(opt) == "table" then
  for i = 1, 30 do
    local o = opt[i]
    if type(o) == "table" and tostring(o.跳转链接 or "") == "NM" then
      local j = o.选中判断
      if type(j) == "table" then
        out = tostring((tonumber(j.x or 0)+tonumber(j.x2 or 0))/2) .. "," ..
              tostring((tonumber(j.y or 0)+tonumber(j.y2 or 0))/2)
      end
      break
    end
  end
end
_G.__out = out''').replace("NM", str(name))
    v = _lua_read(gateway, code)
    try:
        x, y = v.split(",")
        return int(float(x)), int(float(y))
    except (ValueError, TypeError):
        return None, None


def _click_keyword_option(hwnd, gateway, keyword) -> bool:
    """在对话栏选项中找到 文字/跳转 含 keyword 的项，点击其『选中判断』中心。

    分辨率无关：中心（j.x/j.x2、j.y/j.y2）从游戏实时读取，不写死像素坐标。
    坐标未就绪（_dialog_options 中 cx/cy 为空）时返回 False，由上层下次重试。"""
    for o in _dialog_options(gateway):
        probe = (o.get("text") or "") + "|" + (o.get("link") or "")
        if keyword in probe and o.get("cx") and o.get("cy"):
            return _click(hwnd, int(float(o["cx"])), int(float(o["cy"])))
    return False


def _member_teleport_enable(hwnd, gateway) -> bool:
    """确保「会员传送·门派列表」子菜单真实显示（`可视=true` 且含 15 门派）。

    ⚠ `可视=false` 表示菜单只存在于数据层、未渲染 → 点击无效，必须用右键重开。
    状态判断：
      - 可视 && 已含门派 → 就绪，返回 True
      - 可视 && 卡根菜单（领取每日福利/我要存钱）→ 点「门派传送」(147,415) 进入门派列表
      - 其它（不可视/在别处）→ 右键会员卡重开
    """
    for _ in range(6):
        st = _member_dialog_state(gateway) or ""
        vis = "可视=true" in st
        is_root = ("领取每日福利" in st) or ("我要存钱" in st)
        has_sect = any(s in st for s in SECT_LIST_15) and not is_root
        if vis and has_sect:
            return True
        if vis and is_root:
            # 卡根菜单「门派传送」项：动态读『选中判断』中心点击（分辨率无关，不再写死 147,415）
            if not _click_keyword_option(hwnd, gateway, "门派传送"):
                # 坐标未就绪（刚右键重开菜单，选中判断未填充）→ 保留菜单，下次再点
                continue
            deadline = time.time() + 1.2
            while time.time() < deadline:
                time.sleep(0.15)
                tmp = _member_dialog_state(gateway) or ""
                if "可视=true" in tmp and any(s in tmp for s in SECT_LIST_15) and "我要存钱" not in tmp:
                    return True
            continue
        # 不可视 → 右键会员卡重开（快速：点击后立刻轮询菜单就绪）
        cx, cy = _member_card_pos(gateway)
        if cx is None:
            return False
        _click(hwnd, cx, cy, rbutton=True)
        deadline = time.time() + 1.0
        while time.time() < deadline:
            time.sleep(0.15)
            tmp = _member_dialog_state(gateway) or ""
            if "可视=true" in tmp and any(s in tmp for s in SECT_LIST_15) and "我要存钱" not in tmp:
                return True
    return False


def _gateway_pid(gateway) -> Optional[int]:
    """从网关 /api/status 取绑定的游戏 PID（用于绑定窗口）。"""
    try:
        d = _http_json(gateway, "/api/status")
        res = d.get("result")
        pid = res.get("pid") if isinstance(res, dict) else (res or {}).get("pid")
        return int(pid) if pid else None
    except Exception:
        return None


def _bind_hwnd(gateway, pid):
    """绑定到游戏窗口，返回 hwnd；pid 缺省用网关 PID。"""
    from core.window_manager import window_manager
    if pid is None:
        pid = _gateway_pid(gateway)
    if pid:
        try:
            window_manager.bind(pid=pid)
        except Exception:
            pass
    return getattr(window_manager, "hwnd", None)


def _cur_map_id(gateway) -> str:
    return (_lua_expr(gateway, "tostring(tp.当前地图 or '')") or "").strip()


# ---- 回退：跨图 desc 直达（会员卡不可用时兜底）----
def _find_hop_teleport(gateway: str, target_name: str):
    """在当前图传送表找能到 target_name 的传送条目，返回 (desc, x, y) 或 None。"""
    code = (
        'local out = "" '
        'local t = tp.场景.传送 '
        'for i = 1, #t do '
        '  local s = tostring(t[i].切换 or "") '
        '  if string.find(s, "%s") then '
        '    if t[i].坐标 then '
        '      out = s .. "|" .. tostring(t[i].坐标.x) .. "," .. tostring(t[i].坐标.y) '
        '    end '
        '    break '
        '  end '
        'end '
        '_G.__out = out'
    ) % str(target_name).strip()
    try:
        d = _http_json(gateway, "/api/lua", {"code": code})
        v = d.get("result", {}).get("value")
    except Exception:
        return None
    if v and "|" in v and "," in v:
        desc_part, xy = v.split("|", 1)
        x, y = xy.split(",")
        return desc_part, int(float(x)), int(float(y))
    return None


def _teleport_by_desc(gateway, map_name, x, y):
    """回退：/api/act/cross_map 1003 跨图+瞬移+1002 同步。返回 (ok, arrived)。"""
    hop = _find_hop_teleport(gateway, map_name)
    if not hop:
        return False, None
    desc, d_x, d_y = hop
    tx, ty = (x, y) if x is not None and y is not None else (d_x, d_y)
    try:
        r = _http_json(gateway, "/api/act/cross_map",
                       {"desc": desc, "x": tx, "y": ty, "wait_ms": 3000, "sync": True},
                       timeout=25.0)
    except Exception:
        return False, None
    time.sleep(2.0)
    return bool(r.get("ok")), _cur_map_id(gateway)


# ============================================================
# MPCG_teleport_sect：跳转到目标门派图（会员卡瞬移主路径 + desc 回退）
# ============================================================
def MPCG_teleport_sect(
    map_name: Union[str, dict, None] = None,
    gateway: str = DEFAULT_GATEWAY,
    x: Optional[int] = None,
    y: Optional[int] = None,
    pid: Optional[int] = None,
    verbose: bool = False,
) -> dict:
    """
    跳转到目标门派图。

    主路径（2026-08-25 实测，15 门派全部可达）——会员卡「门派传送」后台点击瞬移：
      1. 通过网关 PID 绑定游戏窗口（后台 PostMessage，不抢焦点）
      2. 袋打开（未开则按 Tab）
      3. 会员卡菜单：右键卡重开 → 若在根菜单点「门派传送」→ 进入门派列表
      4. 读目标门派选项中心坐标，左键点击 → 服务器瞬移（3690 使用卡 + 15xx 切图）
      5. 校验 tp.当前地图 == 目标门派地图ID（SECT_MAP_ID，实测表）

    回退路径：会员卡不可用（袋无卡/菜单打不开）时，用跨图 desc 直达。

    :param map_name: 目标门派名（或 MPCG_recognize 输出 dict，自动取 target_location）
    :param gateway: 网关地址/端口（多组按 http://127.0.0.1:18083 传）
    :param x/y: 可选，到达门派图后的落点坐标（仅 desc 回退路径使用；会员卡路径由服务器落地）
    :param pid: 游戏进程 PID（缺省用网关绑定的 PID）
    :param verbose: 是否打印过程日志
    :return: dict {ok, message, target, source, map_id, arrived_map_id, elapsed_ms}
    """
    t0 = time.time()
    if isinstance(map_name, dict):
        map_name = map_name.get("target_location") or map_name.get("map_name") or map_name.get("map_location")
    map_name = str(map_name or "").strip()
    if not map_name:
        return {"ok": False, "message": "缺少 map_name（目标门派名）",
                "elapsed_ms": round((time.time() - t0) * 1000, 1)}
    target_map_id = SECT_MAP_ID.get(map_name)

    hwnd = _bind_hwnd(gateway, pid)
    if not hwnd:
        return {"ok": False,
                "message": f"未绑定到游戏窗口（pid={pid or '网关'}），无法后台点击会员卡",
                "target": map_name,
                "elapsed_ms": round((time.time() - t0) * 1000, 1)}

    before = _cur_map_id(gateway)

    # ---- 1) 确保袋打开（Lua CALL 道具行囊:打开()；后台安全，无需键盘/鼠标）----
    bag_vis = _lua_expr(gateway, "tostring(tp.窗口.道具行囊.可视 or false)")
    if bag_vis != "true":
        # ALT+E 键盘后台不可用（游戏读不到系统键盘状态表），PostMessage 点按钮有误差；
        # 直接 CALL 背包在游戏内开箱最稳
        if not _open_bag(gateway):
            # 兜底：CALL 失败再用真实输入 ALT+E
            if input_controller is not None:
                input_controller.press_key("alt+e")
            else:
                _press_key(hwnd, _VK_TAB)
            time.sleep(0.8)

    # ---- 2) 会员卡主路径 ----
    if _member_teleport_enable(hwnd, gateway):
        cx, cy = _member_sect_center(gateway, map_name)
        if cx is not None:
            if verbose:
                logger.info(f"MPCG_teleport_sect(会员卡): 点击「{map_name}」@{cx},{cy} "
                            f"目标地图ID={target_map_id} 原地图={before}")
            _click(hwnd, cx, cy)
            # 快速轮询地图切换：一到目标图立即继续，不留固定 3 秒空等
            arrived = _cur_map_id(gateway)
            deadline = time.time() + 3.0
            while time.time() < deadline and (not target_map_id or arrived != str(target_map_id)):
                time.sleep(0.2)
                arrived = _cur_map_id(gateway)
            ok = bool(target_map_id) and arrived == target_map_id
            return {
                "ok": ok,
                "message": f"跳转「{map_name}」{'成功' if ok else '失败'}（地图ID={arrived}）",
                "target": map_name,
                "source": "member_card",
                "map_id": target_map_id,
                "arrived_map_id": arrived,
                "elapsed_ms": round((time.time() - t0) * 1000, 1),
            }

    # ---- 3) 回退：跨图 desc ----
    if verbose:
        logger.info(f"MPCG_teleport_sect: 会员卡菜单不可用，回退 desc 跨图直达「{map_name}」")
    ok, arrived = _teleport_by_desc(gateway, map_name, x, y)
    return {
        "ok": ok,
        "message": f"跳转「{map_name}」{'成功' if ok else '失败'}（desc地图ID={arrived}）",
        "target": map_name,
        "source": "desc_cross_map",
        "map_id": target_map_id,
        "arrived_map_id": arrived,
        "elapsed_ms": round((time.time() - t0) * 1000, 1),
    }


# ============================================================
# 回城（门派闯关完成后回长安接下一轮）
# ============================================================
def MPCG_goto_city(
    city: str = "长安",
    x: Optional[int] = None,
    y: Optional[int] = None,
    gateway: str = DEFAULT_GATEWAY,
    pid: Optional[int] = None,
    verbose: bool = False,
) -> dict:
    """
    从任意位置回到主城（默认长安城）。

    背景：门派闯关每轮 15 次完成（「恭喜完成」弹窗后）角色会回到未知位置，无法
    直接找到「门派闯关使者」，也未必在城市。因此固定走可靠中转：
      1. 会员卡「门派传送」→ 大唐官府（SECT_MAP_ID 实测可稳定到达，与角色现位置无关）
      2. 大唐官府传送表含「大唐官府传送长安」→ /api/act/cross_map 跨图回长安(1001)
      3. 可选：在城内瞬移到 (x,y)（门派闯关使者默认 193,125）

    :param city: 目标主城名/描述关键字（默认「长安」）
    :param x/y: 到城后的落点坐标（默认门派闯关使者 193,125）
    :return: dict {ok, message, city, arrived_map_id, elapsed_ms}
    """
    t0 = time.time()
    if x is None or city == "长安":
        x = x if x is not None else 193
        y = y if y is not None else 125

    # 1) 会员卡传送 → 大唐官府（可靠中转，与现位置无关）
    lever = "大唐官府"
    tp = MPCG_teleport_sect(map_name=lever, gateway=gateway, pid=pid, verbose=verbose)
    if not tp.get("ok"):
        return {"ok": False, "message": f"中转{lever}失败: {tp.get('message')}",
                "source": tp.get("source"), "elapsed_ms": round((time.time() - t0) * 1000, 1)}

    # 2) 大唐官府 → 长安（cross_map desc）
    ok, arrived = _teleport_by_desc(gateway, city, x, y)
    if not ok:
        return {"ok": False, "message": f"无法从大唐官府跨图到「{city}」(map={arrived})",
                "elapsed_ms": round((time.time() - t0) * 1000, 1)}

    # 3) 城内瞬移到目标点（sync=True 已阻塞至服务端落位，仅留极短确认）
    _gateway_teleport_xy(gateway, x, y)
    time.sleep(0.3)
    return {
        "ok": True,
        "message": f"已回「{city}」并落位({x},{y})",
        "city": city,
        "arrived_map_id": arrived,
        "elapsed_ms": round((time.time() - t0) * 1000, 1),
    }


# ============================================================
# 门派闯关使者：回城后自动接下一轮（CALL使者 → 点「准备好了」）
# ============================================================
def _lua_find_npc_substr(gateway, substr: str) -> dict:
    """按「名称包含 substr」定位场景假人，返回 {ok, index, name}。"""
    code = ("local j=tp.场景.假人; local idx=nil "
            "for i=1,#j do if type(j[i])=='table' and (tostring(j[i].名称 or '')):find('》') then idx=i end end "
            "if not idx then _G.__out='NO'; return end "
            "_G.__out='IDX='..idx..' NAME='..tostring(j[idx].名称 or '')").replace("》", str(substr))
    v = _lua_read(gateway, code)
    if not v or v == "NO":
        return {"ok": False}
    d = dict(pair.split("=", 1) for pair in v.split() if "=" in pair)
    return {"ok": True, "index": int(d.get("IDX") or 0), "name": d.get("NAME", "")}


def _lua_events_start(gateway, index) -> bool:
    """调用场景假人 index 的 事件开始。返回是否成功。"""
    code = ("local j=tp.场景.假人; local o=j[%s] "
            "local ok,rr=pcall(function() return o['事件开始'](o) end); _G.__out=tostring(ok)") % int(index)
    r = _lua_call(gateway, code)
    return (r.get("value") or "").strip() == "true"


_ACCEPT_OPTION_KEYWORD = "准备好了"  # 使者接受选项：跳转/文字包含该词


def MPCG_accept_round(
    gateway: str = DEFAULT_GATEWAY,
    pid: Optional[int] = None,
    do_goto: bool = False,
    x: Optional[int] = None,
    y: Optional[int] = None,
    verbose: bool = False,
) -> dict:
    """
    回城后点击「门派闯关使者」→「准备好了」自动接取新一轮门派闯关。

    ★2026-08-25 修复「点不到接任务」：自动循环仅回城就 break，从未点使者接下一轮；
      且残留的会员传送菜单（对话栏.可视=false，仅数据层）会占住对话栏，导致使者
      对话框无法渲染、后台点击失效。必须先右键关闭残留，再 CALL 使者。

    流程：
      1. do_goto=True 且当前非长安(1001) → 先 MPCG_goto_city 长安 193,125
      2. 清理残留对话框/会员菜单（可视=true 的无按钮弹窗一律右键关闭）
      3. 定位「门派闯关使者」→ 事件开始
      4. 轮询读对话，取「准备好了」选项的有效坐标并后台点击
      5. 校验任务激活（任务追踪栏出现 类型=107 记录）

    :return: dict {ok, message, source, clicked, activated, dialog, elapsed_ms}
    """
    t0 = time.time()
    hwnd = _bind_hwnd(gateway, pid)
    if not hwnd:
        return {"ok": False, "message": "未绑定窗口，无法接取", "elapsed_ms": round((time.time() - t0) * 1000, 1)}

    # 1) 确保在长安（可选回城）
    if do_goto and _cur_map_id(gateway) != "1001":
        gc = MPCG_goto_city(gateway=gateway, pid=pid, verbose=verbose)
        if not gc.get("ok"):
            return {"ok": False, "message": f"回城失败: {gc.get('message')}",
                    "elapsed_ms": round((time.time() - t0) * 1000, 1)}
    elif not do_goto and _cur_map_id(gateway) != "1001":
        return {"ok": False, "message": f"当前不在长安(地图={_cur_map_id(gateway)})，无法接取使者",
                "elapsed_ms": round((time.time() - t0) * 1000, 1)}

    # 2) 清理残留对话框/会员菜单（会员传送菜单可视=false 也在数据层占位，点右下场景关闭）
    for _ in range(4):
        if _lua_expr(gateway, "tostring(tp.窗口.对话栏.可视 or false)") == "true":
            _click(hwnd, 150, 320, rbutton=True)
            ddl = time.time() + 0.8
            while time.time() < ddl and \
                    _lua_expr(gateway, "tostring(tp.窗口.对话栏.可视 or false)") == "true":
                time.sleep(0.15)
        else:
            break

    # 3) CALL 使者
    npc = _lua_find_npc_substr(gateway, "门派闯关")
    if not npc.get("ok"):
        return {"ok": False, "message": "场景未找到「门派闯关使者」（是否已回长安？）",
                "elapsed_ms": round((time.time() - t0) * 1000, 1)}
    if not _lua_events_start(gateway, npc["index"]):
        return {"ok": False, "message": f"CALL「{npc.get('name')}」失败",
                "elapsed_ms": round((time.time() - t0) * 1000, 1)}

    # 4) 轮询读对话，点「准备好了」接受
    clicked = False
    opts = []
    ddl = time.time() + 3.0
    while time.time() < ddl:
        opts = _dialog_options(gateway)
        for o in opts:
            txt = (o["text"] or "") + "|" + (o["link"] or "")
            if _ACCEPT_OPTION_KEYWORD in txt and o["cx"] and o["cy"]:
                hwnd2 = _bind_hwnd(gateway, pid)
                if hwnd2:
                    _click(hwnd2, int(float(o["cx"])), int(float(o["cy"])))
                    clicked = True
                break
        if clicked:
            break
        time.sleep(0.2)
    if not clicked:
        return {"ok": False, "message": "使者对话中未见「准备好了」有效选项（对话栏被其它菜单占用？）",
                "source": "accept_round", "dialog": opts,
                "elapsed_ms": round((time.time() - t0) * 1000, 1)}

    # 5) 校验任务激活（任务记录有延迟~1s，重试数秒）
    activated = False
    for _ in range(10):
        rec = _lua_read_mpcg(gateway)
        if rec.get("ok"):
            activated = True
            break
        time.sleep(0.3)
    return {
        "ok": True,
        "message": f"已点「准备好了」{'并确认任务激活' if activated else '（任务暂未读取到，疑似未接上）'}",
        "source": "accept_round",
        "clicked": clicked,
        "activated": activated,
        "dialog": opts,
        "elapsed_ms": round((time.time() - t0) * 1000, 1),
    }


# ============================================================
# 门派护法 CALL（CALL 门派护法 → 开始派系考验）
# ============================================================
def _lua_find_guard(gateway, map_name: str) -> dict:
    """在当前场景找「{map_name}护法」，返回 {ok, index, name, x, y}。
    找不到返回 {'ok': False}。"""
    name = f"{map_name}护法"
    code = ("local out={}; local j=tp.场景.假人; local idx=nil; local o=nil "
            "for i=1,#j do if type(j[i])=='table' and tostring(j[i].名称 or '')=='%s' then "
            "idx=i; o=j[i] end end "
            "if not o then _G.__out='NO'; return end "
            "out.cx=tostring(o.坐标 and o.坐标.x or ''); out.cy=tostring(o.坐标 and o.坐标.y or '')"
            " out.gx=tostring(o.格子x or ''); out.gy=tostring(o.格子y or '')"
            " _G.__out='IDX='..idx..' CX='..out.cx..' CY='..out.cy..' GX='..out.gx..' GY='..out.gy") % name
    v = _lua_read(gateway, code)
    if not v or v == "NO":
        return {"ok": False}
    d = dict(pair.split("=", 1) for pair in v.split() if "=" in pair)
    return {
        "ok": True,
        "index": int(d.get("IDX") or 0) if d.get("IDX") else None,
        "x": d.get("CX", ""), "y": d.get("CY", ""),
        "gx": d.get("GX", ""), "gy": d.get("GY", ""),
    }


def _gateway_teleport_xy(gateway, x: int, y: int, timeout: float = 15.0) -> dict:
    """走网关 /api/act/teleport 瞬移到地图坐标 (x,y)。返回 {ok, value/error}。"""
    try:
        d = _http_json(gateway, "/api/act/teleport", {"x": int(x), "y": int(y), "sync": True, "jump": True}, timeout=timeout)
        if d.get("ok"):
            return {"ok": True, "value": (d.get("result") or {}).get("_out", (d.get("result") or {}).get("value"))}
        return {"ok": False, "error": d.get("error", "瞬移接口失败")}
    except Exception as e:
        return {"ok": False, "error": f"瞬移请求异常: {e}"}


def _dialog_options(gateway) -> list:
    """读当前对话栏选项，返回 [{'text','link','content','cx','cy'}]。

    ★2026-08-25 修复：只填充『有效』的 选中判断 中心坐标。事件开始后对话框选项的
    选中判断 尚未初始化（曾读到退化值 (28,7) 导致后台点击开战失败），这里要求
    x2>x && y2>y && 中心>15px 才视为可用坐标，否则 cx/cy 留空由上层重试。"""
    code = r'''
local d=tp.窗口.对话栏
local out={}
if d and d.选项 then
  for i=1,20 do
    local o=d.选项[i]
    if type(o)~='table' then break end
    local j=(type(o.选中判断)=='table') and o.选中判断 or nil
    local cx,cy='',''
    if j then
      local x=tonumber(j.x or 0); local x2=tonumber(j.x2 or 0)
      local y=tonumber(j.y or 0); local y2=tonumber(j.y2 or 0)
      if x and x2 and y and y2 and x2>x and y2>y and x>15 and y>15 then
        cx=tostring((x+x2)/2); cy=tostring((y+y2)/2)
      end
    end
    out[#out+1]=string.format('%s|%s|%s|%s|%s', tostring(i), tostring(o.文字 or ''), tostring(o.跳转 or o.跳转链接 or ''), cx, cy)
  end
end
_G.__out=table.concat(out,'\n')'''
    v = _lua_read(gateway, code)
    opts = []
    for line in (v or "").splitlines():
        parts = line.split("|")
        if len(parts) >= 5:
            opts.append({"index": parts[0], "text": parts[1], "link": parts[2], "cx": parts[3], "cy": parts[4]})
    return opts


def MPCG_call_guard(
    map_name: Union[str, dict, None] = None,
    x: Optional[int] = None,
    y: Optional[int] = None,
    gateway: str = DEFAULT_GATEWAY,
    pid: Optional[int] = None,
    start: bool = True,
    verbose: bool = False,
) -> dict:
    """
    CALL 门派护法：瞬移到护法旁 → CALL 护法事件 → 点「请出招吧」开始考验。

    流程：
      1. 若目标非当前图，会员卡瞬移（MPCG_teleport_sect）到门派图
      2. 瞬移到护法坐标 (x,y)（缺省用 SECT_GUARD_COORDS；龙宫(-1,-1) 跳过瞬移）
      3. 定位「{门派}护法」→ 调用其 事件开始
      4. start=True 时读对话点「请出招吧」

    :param map_name: 目标门派名（或识别 dict）
    :param x/y: 护法所在格坐标（缺省用 SECT_GUARD_COORDS[map_name]）
    :param start: True=点「请出招吧」开战；False=只 CALL 打开对话
    :return: dict {ok, message, source, map_id, guard, dialog, started}
    """
    t0 = time.time()
    if isinstance(map_name, dict):
        map_name = map_name.get("target_location") or map_name.get("map_name") or map_name.get("map_location")
    map_name = str(map_name or "").strip()
    if not map_name:
        return {"ok": False, "message": "缺少 map_name", "elapsed_ms": round((time.time() - t0) * 1000, 1)}

    # 解析坐标
    if x is None or y is None:
        cx, cy = SECT_GUARD_COORDS.get(map_name, (None, None))
        x = x if x is not None else cx
        y = y if y is not None else cy
    need_move = not (x == -1 or (map_name == "龙宫"))

    # 1) 到门派图（龙宫不用跨图，直接在护法旁）
    if map_name != "龙宫":
        cur = _cur_map_id(gateway)
        want = SECT_MAP_ID.get(map_name)
        if cur != want:
            tp = MPCG_teleport_sect(map_name=map_name, gateway=gateway, pid=pid, verbose=verbose)
            if not tp.get("ok"):
                return {"ok": False, "message": f"瞬移到门派失败: {tp.get('message')}",
                        "source": tp.get("source"), "elapsed_ms": round((time.time() - t0) * 1000, 1)}

    # 1.5) 会员卡瞬移后菜单可能残留，先关闭，避免盖住后续护法对话/「请出招吧」
    hwnd_t = _bind_hwnd(gateway, pid)
    if hwnd_t and _lua_expr(gateway, "tostring(tp.窗口.对话栏.可视 or false)") == "true":
        _click(hwnd_t, 150, 320, rbutton=True)
        ddl = time.time() + 1.2
        while time.time() < ddl and \
                _lua_expr(gateway, "tostring(tp.窗口.对话栏.可视 or false)") == "true":
            time.sleep(0.2)

    # 2) 瞬移到护法旁（自校正：优先读护法真实网格坐标落位，避免硬编码坐标偏差导致开战失败）
    if need_move:
        tx, ty = x, y
        # 已到门派图，护法应已刷出 → 读其真实网格坐标，直接落位到护法身上（邻接校验必过）
        g0 = _lua_find_guard(gateway, map_name)
        if g0.get("ok") and g0.get("gx") and g0.get("gy"):
            try:
                tx, ty = int(float(g0["gx"])), int(float(g0["gy"]))
            except (TypeError, ValueError):
                pass
        elif g0.get("ok") and g0.get("x") and g0.get("y"):
            try:
                tx, ty = int(float(g0["x"]) // 20), int(float(g0["y"]) // 20)
            except (TypeError, ValueError):
                pass
        if tx is not None and ty is not None:
            mv = _gateway_teleport_xy(gateway, tx, ty)
            if not mv.get("ok") and verbose:
                logger.warning(f"MPCG_call_guard: 瞬移至护法({tx},{ty})失败: {mv.get('error')}——尝试直接CALL")

    # 3) CALL 护法（快速轮询：护法一刷出立即 CALL，不留固定空等）
    guard = {"ok": False}
    ginfo = None
    for _ in range(6):
        ginfo = _lua_find_guard(gateway, map_name)
        if ginfo.get("ok"):
            code = ("local j=tp.场景.假人; local o=j[%s] "
                    "local ok,rr=pcall(function() return o['事件开始'](o) end); "
                    "_G.__out=tostring(ok)") % ginfo["index"]
            r = _lua_call(gateway, code)
            if (r.get("value") or "").strip() == "true":
                guard["ok"] = True
            break
        time.sleep(0.35)

    if not guard.get("ok"):
        return {"ok": False,
                "message": f"未找到并 CALL「{map_name}护法」（坐标 {x or '?'},{y or '?'}；是否已在目标门派且护法刷出？）",
                "target": map_name, "source": "guard",
                "map_id": _cur_map_id(gateway), "guard_found": False,
                "elapsed_ms": round((time.time() - t0) * 1000, 1)}

    # 4) 读对话 + 点「请出招吧」开战（轮询到目标选项出现『有效』坐标再点——避免
    #    事件开始后选中判断未初始化读到退化坐标(28,7)导致点击无效）
    started = False
    if start:
        tgt = None
        ddl = time.time() + 2.0
        while time.time() < ddl:
            opts = _dialog_options(gateway)
            for o in opts:
                if o["text"] == _GUARD_START_OPTION or o["link"] == _GUARD_START_OPTION:
                    tgt = o
                    break
            if tgt and tgt["cx"] and tgt["cy"]:
                break
            time.sleep(0.2)
        if tgt and tgt["cx"] and tgt["cy"]:
            hwnd = _bind_hwnd(gateway, pid)
            if hwnd:
                _click(hwnd, int(float(tgt["cx"])), int(float(tgt["cy"])))
                started = True
    return {
        "ok": True,
        "target": map_name,
        "message": f"CALL「{map_name}护法」成功，{'已点「请出招吧」' if started else '对话待处理'}"
                   + (f"（护法@{ginfo.get('x')},{ginfo.get('y')} 格{ginfo.get('gx')},{ginfo.get('gy')}）" if ginfo.get("ok") else ""),
        "source": "guard_call",
        "guard_found": True,
        "dialog": opts,
        "started": started,
        "map_id": _cur_map_id(gateway),
        "elapsed_ms": round((time.time() - t0) * 1000, 1),
    }


# ============================================================
# MPCG_auto_round — 整轮自动聚合（对标 SYBUZ2：勾选一个函数即全链路联动）
# 内部编排: 状态轮询→验证码优先暂停避让→三态分发（战斗/弹窗/空闲）→
#           识别→传送→CALL护法→开战→循环至完成→回城→(rounds>1)接下一轮
# ============================================================
def _auto_state(gateway: str) -> dict:
    """读一行式 Lua 状态: 战斗/地图/对话栏可视/名称/文本。"""
    code = r'''
local out = {}
out[1] = "战斗=" .. tostring(tp.战斗中 and true or false)
out[2] = "地图=" .. tostring(tp.当前地图 or "")
local d = tp.窗口.对话栏
out[3] = "可视=" .. tostring(d and d.可视 or false)
out[4] = "名=" .. tostring(d and d.名称 or "")
out[5] = "文=" .. tostring(d and d.文本内容 or "")
_G.__out = table.concat(out, "\n")'''
    v = _lua_read(gateway, code)
    r = {}
    for line in (v or "").splitlines():
        if "=" in line:
            k, _, val = line.partition("=")
            r[k] = val
    return r


def _next_sect(text):
    """从对话/弹窗文本解析目标门派名。

    只用 SECT_LIST_15 白名单：目标门派名只可能出现在「前往/下一关…接受考验」类弹窗中。
    会员卡福利、任务流程说明等无关弹窗不含门派名 → 返回 None，避免误判成下一关。
    """
    text = text or ""
    if not text:
        return None
    # 1) 关键字后紧跟门派（白名单校验，颜色标记可能夹在中间）
    for kw in ("前往", "下一关", "应该前往"):
        for m in re.finditer(re.escape(kw), text):
            tail = text[m.end():m.end() + 16]
            for name in SECT_LIST_15:
                if name in tail:
                    return name
    # 2) 兜底：全文本含门派名，且与「前往/下一关/考验」之一共现
    if not any(k in text for k in ("前往", "下一关", "考验")):
        return None
    for name in SECT_LIST_15:
        if name in text:
            return name
    return None


def _auto_close_dialog(gateway, pid) -> bool:
    """右键关闭完成/确认弹窗（无按钮场景）。返回是否已关闭。"""
    hwnd = _bind_hwnd(gateway, pid)
    if not hwnd:
        return False
    _click(hwnd, 150, 320, rbutton=True)
    time.sleep(0.8)
    return _auto_state(gateway).get("可视") != "true"


def _verify_battle_start(gateway: str, timeout: float = 5.0) -> bool:
    """CALL 护法后校验战斗是否真的开始（tp.战斗中）。

    ★2026-08-26：MPCG_call_guard 返回 ok 仅代表「点了请出招吧」，不保证战斗触发。
    若角色离护法过远（坐标偏差，如神木林内置(46,159) vs 真实(42,161)），游戏忽略点击、
    战斗不开始，此前被静默当成成功，导致 steps 盲增、循环死锁。这里轮询战斗状态，
    未触发则打印明确告警，交由上层同门派重试/卡关结束逻辑处理。"""
    ddl = time.time() + timeout
    while time.time() < ddl:
        if _auto_state(gateway).get("战斗") == "true":
            return True
        time.sleep(0.5)
    print("  ⚠ CALL后未检测到战斗开始（角色可能离护法过远/坐标偏差，请核对 SECT_GUARD_COORDS）", flush=True)
    return False


def _mpcg_quest_active(gateway: str) -> dict:
    """判断门派闯关任务是否仍在进行——「是否完成」的唯一权威依据。

    ★2026-08-26 用户要求：终止条件不看关卡次数，只看门派闯关是否完成。
    循环遇到「同门派反复 CALL 失败」或「空闲读不到目标」时，必须靠任务态区分：
      任务还在 → 卡住了，继续重试（绝不因计数掐断）；
      任务没了 → 已完成/已交付，正常收尾回城。

    判定优先级：
      1) 介绍文本仍解析出门派目标        → 进行中（最强信号）
      2) 介绍文本无目标但命中「需接任务」措辞 → 未接/待接（need_accept=True，去接，不是完成！）
      3) 介绍文本无目标但命中完成措辞    → 已完成（待领奖）
      4) 数据记录仍有类型=107           → 进行中
      5) 以上皆无                       → 任务不存在 = 未接取

    :return: {active, target, count, text, source, need_accept}
    """
    intro = {}
    try:
        intro = _lua_read_mpcg_intro(gateway)
    except Exception:
        intro = {"ok": False}
    if intro.get("ok"):
        text = intro.get("text", "") or ""
        if intro.get("target"):
            return {"active": True, "target": intro["target"], "count": intro.get("count", 0),
                    "text": text, "source": "intro", "need_accept": False}
        # ★「领取任务/使者」= 任务还没接，不是完成！必须去接任务
        if _ACCEPT_INTRO_RE.search(text):
            return {"active": False, "target": None, "count": intro.get("count", 0),
                    "text": text, "source": "intro_accept", "need_accept": True}
        if _DONE_INTRO_RE.search(text):
            return {"active": False, "target": None, "count": intro.get("count", 0),
                    "text": text, "source": "intro_done", "need_accept": False}
    try:
        lu = _lua_read_mpcg(gateway)
    except Exception:
        lu = {"ok": False}
    if lu.get("ok"):
        return {"active": True, "target": None, "count": lu.get("count", 0),
                "text": intro.get("text", "") or "", "source": "record107", "need_accept": False}
    # 无记录 + 无介绍 → 未接任务（与 intro_accept 同义：去接）
    return {"active": False, "target": None, "count": 0,
            "text": intro.get("text", "") or "", "source": "none", "need_accept": True}


def _auto_call_guard(gateway, map_name, verbose) -> dict:
    """传送+CALL+开战（龙宫走特殊分支：先会员卡传送再 CALL）。"""
    if map_name == "龙宫":
        tp = MPCG_teleport_sect(map_name="龙宫", gateway=gateway, verbose=verbose)
        if verbose:
            logger.info(f"MPCG_auto_round: 龙宫传送 {tp.get('message')}")
        return MPCG_call_guard(map_name="龙宫", x=-1, y=-1, gateway=gateway, verbose=verbose)
    return MPCG_call_guard(map_name=map_name, gateway=gateway, verbose=verbose)


def _peek_mission_target(gateway, pid=None):
    """任务记录已激活但恒等/无法映射目标时，主动向使者要当前目标门派。

    场景：本服任务记录「闯关序列」恒等 1..15（不可信），目标门派只可靠地出现在
    使者/护法弹窗文本；而新任务首关的目标只在使者对话「前往#Y/X#W/」里，
    且该文本须点击「准备好了」选项后才弹出（问候对话本身不含目标）。
    因此这里：清理残留 → CALL 使者 → 点「准备好了」→ 读「前往/下一关 X」。

    返回门派名；解析不到或 CALL 失败返回 None。
    """
    hwnd = _bind_hwnd(gateway, pid)
    if not hwnd:
        return None
    # 长安才点使者，避免其它地图误点
    if _cur_map_id(gateway) != "1001":
        return None
    # 1) 清理残留对话框/会员菜单（若有可视弹窗先右键关闭，避免菜单占位盖住使者对话）
    for _ in range(3):
        if _lua_expr(gateway, "tostring(tp.窗口.对话栏.可视 or false)") == "true":
            _click(hwnd, 150, 320, rbutton=True)
            time.sleep(0.5)
        else:
            break
    # 2) 定位使者；对话栏已有选项则免重 CALL，否则事件开始
    npc = _lua_find_npc_substr(gateway, "门派闯关")
    if not npc.get("ok"):
        return None
    opts = _dialog_options(gateway)
    if not any(o["cx"] and o["cy"] for o in opts):
        if not _lua_events_start(gateway, npc["index"]):
            return None
    # 3) 点「准备好了」→ 触发「前往#Y/X#W/」
    clicked = False
    ddl = time.time() + 3.0
    while time.time() < ddl:
        for o in _dialog_options(gateway):
            txt = (o["text"] or "") + "|" + (o["link"] or "")
            if _ACCEPT_OPTION_KEYWORD in txt and o["cx"] and o["cy"]:
                _click(hwnd, int(float(o["cx"])), int(float(o["cy"])))
                clicked = True
                break
        if clicked:
            break
        time.sleep(0.2)
    if not clicked:
        # 无「准备好了」选项 → 使者对话可能已显示目标文本，直接读
        pass
    # 4) 读弹窗文本解析目标
    text = ""
    ddl = time.time() + 3.0
    while time.time() < ddl:
        st = _auto_state(gateway)
        if st.get("可视") == "true" and (st.get("文") or "").strip():
            text = st.get("文")
            break
        time.sleep(0.2)
    tgt = _next_sect(text)
    # 5) 无论是否解析成功，关闭使者对话框（避免残留遮挡）
    try:
        if _lua_expr(gateway, "tostring(tp.窗口.对话栏.可视 or false)") == "true":
            _click(hwnd, 150, 320, rbutton=True)
            time.sleep(0.5)
    except Exception:
        pass
    return tgt


def MPCG_auto_round(
    timeout: int = 5400,
    max_steps: int = 0,
    rounds: int = 1,
    gateway: str = DEFAULT_GATEWAY,
    pid: Optional[int] = None,
    verbose: bool = False,
) -> dict:
    """整轮门派闯关自动聚合（对标 SYBUZ2 的单函数全链路）。

    一次调用自动完成一整轮：
      状态轮询 → 验证码优先暂停避让 → 三态分发（战斗中等待 / 弹窗解析下一关 /
      空闲按任务记录自锚定）→ 传送到目标门派 → CALL 护法 → 请出招吧开战 →
      （循环至完成弹窗）→ 回城长安(193,125) → （rounds>1 自动 CALL 使者接下一轮）。

    任务序列（GUI「函数调用」事件）只需配置一个此函数即可，无需逐个排列
    recognize / teleport_sect / call_guard / goto_city / accept_round。

    :param timeout: 整轮最长等待秒数（默认5400=90分钟，仅时间兜底，不作关卡限制）
    :param max_steps: 【已废弃，默认0=不限】★2026-08-26 用户要求「不看次数，只看门派闯关是否完成」，
       关卡计数不再作为终止条件，steps 仅用于打印进度。传 >0 时也只在日志提示、不再掐断循环。
       终止只由三件事决定：任务完成（完成弹窗 / 任务记录消失）、rounds 跑满、timeout 到时。
    :param rounds: 连续自动跑几轮（默认1，完成后自动回城接下一轮）
    :param gateway/pid: 网关与 PID（缺省按组/绑定）
    :return: dict {ok, rounds, rounds_done, steps, reason, elapsed_ms, message}
    """
    from core.captcha_link import captcha_active, wait_captcha_clear

    t0 = time.time()
    steps = 0
    round_num = 0
    last_target = None
    same_streak = 0
    no_target_streak = 0   # 任务记录在但读不到目标门派的连续轮次（用于完成态兜底核实）
    if max_steps:
        print(f"[提示] max_steps={max_steps} 已废弃：只看门派闯关是否完成，不再按关卡数掐断", flush=True)

    def _finish_round(why: str) -> bool:
        """本轮门派闯关判定完成 → 回城 + （rounds 未跑满时）接下一轮。

        ★唯一的「本轮结束」出口：任务态说完成才算完成，与跑了多少关无关。
        :return: True 表示 rounds 已跑满、应结束整个循环
        """
        nonlocal round_num, steps, last_target, same_streak
        round_num += 1
        print(f"=== 第{round_num}轮完成（{why}，本轮{steps}关），回城 ===", flush=True)
        try:
            gc = MPCG_goto_city(gateway=gateway, verbose=verbose)
            print(f"  回城: {gc.get('message')}", flush=True)
        except Exception as e:
            print(f"  回城[ERR] {e}", flush=True)
        if round_num >= rounds:
            return True
        try:
            ar = MPCG_accept_round(gateway=gateway, pid=pid, do_goto=False, verbose=verbose)
            print(f"  接下一轮: {ar.get('message')}", flush=True)
        except Exception as e:
            print(f"  接下一轮[ERR] {e}", flush=True)
        steps = 0            # 下一轮重新统计（仅进度展示用）
        last_target = None
        same_streak = 0
        time.sleep(2)
        return False

    print("=== MPCG_auto_round 整轮自动开始（终止条件：闯关完成 / rounds 跑满 / 超时）===", flush=True)
    while time.time() - t0 < timeout:
        step_t0 = time.time()
        # ★验证码优先 V7 直解（2026-08-26：MPCG 死循环期间引擎无法介入，必须自足处理）：
        #   Lua 直判弹窗（可视）+ Lua 读答案/按钮坐标 → PostMessage 直点答案按钮，
        #   不依赖 captcha_monitor 状态文件（9968 组2 无 monitor 也能解）。
        try:
            from core.captcha_v7 import solve_v7
            hwnd_c = _bind_hwnd(gateway, pid)
            _ok, _det = solve_v7(hwnd_c, gateway=gateway)
            if _ok:
                print(f"[{int(time.time()-t0)}s] 验证码 V7 直解成功: {_det.get('answer')}", flush=True)
                continue
        except Exception as e:
            print(f"[{int(time.time()-t0)}s] 验证码 V7 直解异常: {e}", flush=True)
        # 兜底：monitor 状态文件等待（有 monitor 绑定的实例）
        if captcha_active():
            print(f"[{int(time.time()-t0)}s] 验证码弹窗，优先暂停避让...", flush=True)
            if not wait_captcha_clear(timeout=58):
                print(f"[{int(time.time()-t0)}s] 等待验证码超时，继续（网关自愈兜底）", flush=True)
            continue
        s = _auto_state(gateway)
        # 1) 战斗中 → 等待
        if s.get("战斗") == "true":
            time.sleep(3)
            continue
        # 2) 有可视弹窗
        if s.get("可视") == "true":
            text = s.get("文") or ""
            name = s.get("名")
            # ★2026-08-25 用户要求：下一关门派一律从「任务信息（任务追踪栏 107 记录/介绍文本）」
            #   读取，不再从弹窗文本解析（弹窗会被会员卡福利等无关文本干扰）。
            #   弹窗仅用于判断「本轮是否完成」；其余一律关闭，目标由下方空闲分支按任务信息自锚定。
            if ("完成" in text or "恭喜" in text
                    or "领取任务" in text or "门派闯关使者" in text
                    or "使者处领取" in text or "领取下一轮" in text):
                # 完成弹窗 / NPC 提示回长安使者处领取任务 → 本轮已结束
                print(f"[{int(time.time()-t0)}s] 弹窗[完成/领奖] {name} | {text}", flush=True)
                _auto_close_dialog(gateway, pid)
                if _finish_round("完成/领奖弹窗"):
                    break
                continue
            # 其它弹窗（护法「请出招吧」/下一关提示/会员卡福利等）：一律只关闭，不从中取目标门派。
            # 关闭后由空闲分支读任务信息确定下一关。
            print(f"[{int(time.time()-t0)}s] 弹窗[关闭] {name} | {text}", flush=True)
            _auto_close_dialog(gateway, pid)
            time.sleep(0.5)
            continue
        # 3) 空闲 → 按任务记录自锚定下一目标
        try:
            rec = MPCG_recognize(gateway=gateway, verbose=False)
            target = rec.get("target_location")
            # 任务已激活判定：直接命中 map_name，或恒等序列下记录仍存在（含 target_index/seq_identity）
            rec_ok = bool(rec.get("map_name") or rec.get("target_index") or rec.get("seq_identity"))
        except Exception as e:
            print(f"[{int(time.time()-t0)}s] [ERR] 识别失败: {e}", flush=True)
            target = None
            rec_ok = False
        if target:
            no_target_streak = 0
            # ★关卡进度语义修正（2026-08-26）：steps 仅统计「已推进到的不同门派数」，
            #   同一门派被重复识别 = 本次 CALL 未推进（坐标/距离导致开战失败）→ 计为同门派重试，
            #   不盲目累加 steps，避免单关失败就把 steps 顶爆后永久卡「轮询等待完成弹窗」死等。
            if target != last_target:
                steps += 1
                last_target = target
                same_streak = 0
            else:
                same_streak += 1
            tag = f"(同门派重试{same_streak})" if same_streak else ""
            print(f"[{int(time.time()-t0)}s] ▶ 空闲按任务记录→ 第{steps}关: {target}{tag}", flush=True)
            # ★2026-08-26 用户要求「不看次数，只看是否完成」：同门派反复失败不再掐断循环。
            #   每 3 次重试核实一次任务态——任务没了才收尾，任务还在就一直重试
            #   （护法坐标自校正每轮都会重读真实坐标，所以重试是有意义的、不是空转）。
            if same_streak and same_streak % 3 == 0:
                q = _mpcg_quest_active(gateway)
                if q.get("need_accept"):
                    print(f"[{int(time.time()-t0)}s] ⚠ 「{target}」CALL 未推进且任务态=未接/待接（{q['source']}）"
                          f"→ 回城接任务 | intro={q['text'][:60]}", flush=True)
                    try:
                        ar = MPCG_accept_round(gateway=gateway, pid=pid, do_goto=True, verbose=verbose)
                        print(f"  接任务: {ar.get('message')}", flush=True)
                    except Exception as e:
                        print(f"  接任务[ERR] {e}", flush=True)
                    steps = 0
                    last_target = None
                    same_streak = 0
                    no_target_streak = 0
                    time.sleep(2)
                    continue
                if not q["active"]:
                    print(f"[{int(time.time()-t0)}s] ✓ 门派闯关任务已不在进行（{q['source']}）→ 判定本轮完成", flush=True)
                    if _finish_round(f"任务态={q['source']}"):
                        break
                    continue
                print(f"[{int(time.time()-t0)}s] ⚠ 「{target}」已重试{same_streak}次未推进，但任务仍在进行 → 继续重试"
                      f"（若持续失败请核对该门派 SECT_GUARD_COORDS / 护法是否刷出）", flush=True)
            try:
                res = _auto_call_guard(gateway, target, verbose)
                print(f"  CALL结果({int(time.time()-step_t0)}s): {json.dumps(res, ensure_ascii=False)}", flush=True)
            except Exception as e:
                print(f"  [ERR] {e}", flush=True)
            # 校验战斗是否真的触发：CALL 返回 ok 但战斗没起 = 坐标/距离问题，必须暴露而非静默当成成功
            _verify_battle_start(gateway, timeout=5)
            time.sleep(2 + min(same_streak, 5))  # 连续失败时退避，避免高频空转刷屏
            continue
        # 任务已激活（类型107在记录里）但暂未从任务信息解析出目标（介绍文本可能刚刷新）
        # → 不从使者弹窗读目标（用户要求：所有信息从任务信息读），短等后重试读取
        if rec_ok:
            # ★完成态兜底：记录还在但介绍文本已无门派目标（如「返回长安领取奖励」），
            #   立刻核实任务态：需接任务 → 去接；已完成 → 收尾。避免在完成态干等到 timeout。
            q = _mpcg_quest_active(gateway)
            if q.get("need_accept"):
                print(f"[{int(time.time()-t0)}s] ⚠ 记录在但任务态=未接/待接（{q['source']}）→ 回城接任务"
                      f" | intro={q['text'][:60]}", flush=True)
                try:
                    ar = MPCG_accept_round(gateway=gateway, pid=pid, do_goto=True, verbose=verbose)
                    print(f"  接任务: {ar.get('message')}", flush=True)
                except Exception as e:
                    print(f"  接任务[ERR] {e}", flush=True)
                steps = 0
                last_target = None
                same_streak = 0
                no_target_streak = 0
                time.sleep(2)
                continue
            if not q["active"]:
                print(f"[{int(time.time()-t0)}s] ✓ 记录在但任务已非进行态（{q['source']}）"
                      f"→ 判定本轮完成 | intro={q['text'][:60]}", flush=True)
                if _finish_round(f"任务态={q['source']}"):
                    break
                no_target_streak = 0
                continue
            no_target_streak += 1
            print(f"[{int(time.time()-t0)}s] 任务进行中但暂无目标门派（{no_target_streak}s）"
                  f"| intro={q['text'][:60]}", flush=True)
            time.sleep(1)
            continue
        no_target_streak = 0
        # 空闲且无目标任务记录 → 任务信息里确认没有门派闯关任务。
        # ★本轮已推进过关卡而任务记录消失 = 本轮闯关已完成（即使完成弹窗被其它窗口吞掉也能正确收尾），
        #   走完成收尾；steps==0 说明压根没接任务，才 CALL 使者接取。
        if steps > 0:
            print(f"[{int(time.time()-t0)}s] ✓ 本轮已跑{steps}关且任务记录消失 → 判定闯关完成", flush=True)
            if _finish_round("任务记录消失"):
                break
            continue
        # 此时自动 CALL 门派使者接任务（需先在长安），接好后下轮循环自会锚定目标开跑。
        print(f"[{int(time.time()-t0)}s] 任务信息无门派闯关任务 → CALL门派使者自动接取", flush=True)
        try:
            ar = MPCG_accept_round(gateway=gateway, pid=pid, do_goto=True, verbose=verbose)
            print(f"  接任务: {ar.get('message')}", flush=True)
        except Exception as e:
            print(f"  接任务[ERR] {e}", flush=True)
        time.sleep(2)
        continue
    # ★终止只有三种：闯关完成跑满 rounds / 时间兜底超时 / 异常退出。不再有「达到关卡上限」。
    if round_num >= rounds:
        reason = "任务完成"
    elif time.time() - t0 >= timeout:
        reason = f"超时({timeout}s，本轮未完成，卡在{last_target or '未知'})"
    else:
        reason = "循环退出"
    print(f"=== 共完成 {round_num} 轮, 最后轮 {steps} 关, 总耗时 {int(time.time()-t0)}s ===", flush=True)
    return {
        "ok": round_num >= 1,
        "quest_done": round_num >= 1,
        "rounds": rounds,
        "rounds_done": round_num,
        "steps": steps,
        "reason": reason,
        "elapsed_ms": round((time.time() - t0) * 1000, 1),
        "message": f"整轮自动结束（{reason}）：完成{round_num}轮, 最后轮{steps}关, 共{int(time.time()-t0)}s",
    }


# ============================================================
# 工具：自动枚举游戏进程（截图回退兜底）
# ============================================================
def _find_game_pid():
    """枚举 十年一梦.exe 进程，返回第一个 PID（None=未找到）。"""
    try:
        import subprocess, csv, io
        r = subprocess.run(["tasklist", "/V", "/FO", "CSV"],
                           capture_output=True, text=True, encoding="gbk", errors="ignore")
        for row in csv.reader(io.StringIO(r.stdout)):
            if len(row) >= 2 and "十年一梦.exe" in row[0]:
                try:
                    return int(row[1])
                except ValueError:
                    continue
    except Exception as e:
        logger.debug(f"枚举游戏进程失败: {e}")
    return None


# ============================================================
# 命令行入口
# ============================================================
def main():
    """命令行: python MPCG.py [-p PID] [--port PORT] [--teleport 门派名] [--open]"""
    import argparse
    ap = argparse.ArgumentParser(description="门派闯关任务识别与配合（Lua 直读）")
    ap.add_argument("-p", "--pid", type=int, default=None, help="游戏PID（回退截图用）")
    ap.add_argument("--port", type=int, default=None, help="网关端口（多组；缺省按组解析）")
    ap.add_argument("--gateway", type=str, default=None, help="完整网关地址")
    ap.add_argument("--teleport", type=str, default=None, help="跳转门派图，传门派名")
    ap.add_argument("--open", action="store_true", help="打开/确认任务栏")
    args = ap.parse_args()

    gw = args.gateway
    if not gw and args.port:
        gw = f"http://127.0.0.1:{args.port}"

    if args.teleport:
        r = MPCG_teleport_sect(map_name=args.teleport, gateway=gw or DEFAULT_GATEWAY, verbose=True)
        print("=" * 50)
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return
    if args.open:
        r = MPCG_open_taskbar(gateway=gw or DEFAULT_GATEWAY, verbose=True)
        print("=" * 50)
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return

    result = MPCG_recognize(pid=args.pid, gateway=gw or DEFAULT_GATEWAY)
    print("=" * 50)
    print(f"识别结果: {result.get('text', '?,?次')}")
    print(f"地图名:   {result.get('map_name')}")
    print(f"次数:     {result.get('count')}")
    print(f"来源:     {result.get('source')}")
    if result.get('source') != 'lua_gateway':
        print(f"匹配分:   {result.get('best_score'):.3f}")
    print("=" * 50)


if __name__ == "__main__":
    main()